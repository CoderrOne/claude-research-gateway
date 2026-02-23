"""
Session manager for Claude Research Gateway.
Handles encrypted storage and retrieval of authenticated browser sessions (cookies).
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from config import GatewayConfig, load_config
from portals import PortalConfig

logger = logging.getLogger("claude-research")


class SessionManager:
    """Manages persistent authenticated sessions for journal portals."""

    def __init__(self, config: GatewayConfig | None = None):
        self.config = config or load_config()
        self._fernet = self._get_or_create_key()

    # ──────────────────────── Encryption Key ────────────────────────

    def _get_or_create_key(self) -> Fernet:
        """Get or generate a machine-local encryption key for cookie storage."""
        key_file = Path(self.config.data_dir) / ".session_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)

        if key_file.exists():
            key = key_file.read_bytes()
        else:
            key = Fernet.generate_key()
            key_file.write_bytes(key)
            # Restrict permissions on key file (best-effort on Windows)
            try:
                import stat
                key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except Exception:
                pass

        return Fernet(key)

    # ──────────────────────── Session File Paths ────────────────────────

    def _session_path(self, portal_key: str) -> Path:
        return self.config.sessions_dir / f"{portal_key}.session"

    # ──────────────────────── Save / Load ────────────────────────

    def save_cookies(
        self, portal_key: str, cookies: list[dict]
    ) -> None:
        """Save cookies for a portal (encrypted on disk)."""
        session_data = {
            "portal_key": portal_key,
            "cookies": cookies,
            "saved_at": time.time(),
        }
        plaintext = json.dumps(session_data).encode("utf-8")
        encrypted = self._fernet.encrypt(plaintext)

        path = self._session_path(portal_key)
        path.write_bytes(encrypted)
        logger.info(f"Saved session for portal '{portal_key}' ({len(cookies)} cookies)")

    def load_cookies(self, portal_key: str) -> list[dict] | None:
        """Load saved cookies for a portal. Returns None if no session or decryption fails."""
        path = self._session_path(portal_key)
        if not path.exists():
            return None

        try:
            encrypted = path.read_bytes()
            plaintext = self._fernet.decrypt(encrypted)
            session_data = json.loads(plaintext.decode("utf-8"))
            return session_data.get("cookies")
        except Exception as e:
            logger.warning(f"Failed to load session for '{portal_key}': {e}")
            return None

    def delete_session(self, portal_key: str) -> bool:
        """Delete a saved session."""
        path = self._session_path(portal_key)
        if path.exists():
            path.unlink()
            logger.info(f"Deleted session for portal '{portal_key}'")
            return True
        return False

    def has_session(self, portal_key: str) -> bool:
        """Check if a session file exists for a portal."""
        return self._session_path(portal_key).exists()

    def list_sessions(self) -> list[str]:
        """List portal keys that have saved sessions."""
        sessions = []
        for path in self.config.sessions_dir.glob("*.session"):
            sessions.append(path.stem)
        return sessions

    # ──────────────────────── Session Validation ────────────────────────

    async def validate_session(
        self, portal: PortalConfig
    ) -> bool:
        """
        Test if the saved session is still valid by making a request
        to the portal and checking for redirect to login.
        """
        cookies = self.load_cookies(portal.key)
        if not cookies:
            return False

        try:
            async with httpx.AsyncClient(
                follow_redirects=False, timeout=15.0
            ) as client:
                # Convert cookie list to httpx-compatible format
                for cookie in cookies:
                    client.cookies.set(
                        cookie["name"],
                        cookie["value"],
                        domain=cookie.get("domain", ""),
                        path=cookie.get("path", "/"),
                    )

                test_url = portal.base_url.rstrip("/") + portal.session_test_path
                response = await client.get(test_url)

                # If we get redirected to a login page, session is expired
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    if any(
                        kw in location.lower()
                        for kw in ["login", "sso", "shibboleth", "wayf", "auth"]
                    ):
                        logger.info(
                            f"Session for '{portal.key}' expired (redirect to login)"
                        )
                        return False

                # 200 OK = session still valid
                if response.status_code == 200:
                    return True

                return False

        except Exception as e:
            logger.warning(f"Session validation failed for '{portal.key}': {e}")
            return False

    # ──────────────────────── Cookie Injection ────────────────────────

    def inject_cookies(
        self, client: httpx.AsyncClient, portal_key: str
    ) -> bool:
        """Load and inject cookies into an httpx client. Returns True if cookies were loaded."""
        cookies = self.load_cookies(portal_key)
        if not cookies:
            return False

        for cookie in cookies:
            client.cookies.set(
                cookie["name"],
                cookie["value"],
                domain=cookie.get("domain", ""),
                path=cookie.get("path", "/"),
            )

        return True

    def get_session_info(self, portal_key: str) -> dict | None:
        """Get metadata about a saved session (not the cookies themselves)."""
        path = self._session_path(portal_key)
        if not path.exists():
            return None

        try:
            encrypted = path.read_bytes()
            plaintext = self._fernet.decrypt(encrypted)
            session_data = json.loads(plaintext.decode("utf-8"))
            return {
                "portal_key": session_data.get("portal_key"),
                "cookie_count": len(session_data.get("cookies", [])),
                "saved_at": session_data.get("saved_at"),
                "age_hours": round(
                    (time.time() - session_data.get("saved_at", 0)) / 3600, 1
                ),
            }
        except Exception:
            return None
