"""
Browser-based authentication for institutional journal access.
Uses Playwright to handle interactive Shibboleth/SAML SSO flows.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from playwright.async_api import async_playwright, Page, Browser, BrowserContext

if TYPE_CHECKING:
    from portals import PortalConfig
    from config import GatewayConfig

logger = logging.getLogger("claude-research")


class BrowserAuthenticator:
    """
    Handles interactive browser-based authentication to scientific journal portals.

    Flow:
    1. Launch browser (headed for user to see and interact)
    2. Navigate to portal's institutional login page
    3. Optionally auto-select institution on WAYF page
    4. Wait for user to complete SSO login
    5. Capture cookies after successful authentication
    6. Return cookies for session storage
    """

    def __init__(self, config: "GatewayConfig"):
        self.config = config
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None

    async def authenticate(
        self,
        portal: "PortalConfig",
        headless: bool = False,
    ) -> list[dict]:
        """
        Run the interactive authentication flow for a portal.

        Args:
            portal: The portal configuration to authenticate against
            headless: If True, run browser headless (only works with cached cookies)

        Returns:
            List of cookie dicts from the authenticated session

        Raises:
            TimeoutError: If user doesn't complete login in time
            RuntimeError: If authentication fails
        """
        timeout_ms = self.config.browser_timeout_seconds * 1000

        async with async_playwright() as p:
            # Launch a visible browser so the user can enter credentials
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )

            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                java_script_enabled=True,
            )

            page = await context.new_page()

            try:
                # Step 1: Navigate to institutional login
                logger.info(
                    f"Navigating to {portal.name} login: {portal.login_url}"
                )
                await page.goto(portal.login_url, wait_until="networkidle", timeout=30000)

                # Step 2: Try to find and click institutional login link
                await self._click_institutional_login(page, portal)

                # Step 3: If WAYF page, try auto-selecting institution
                if self.config.institution.wayf_institution_name:
                    await self._handle_wayf(page)

                # Step 4: Wait for authentication to complete
                # We detect this by watching for navigation back to the portal domain
                logger.info(
                    f"Waiting for user to complete login (timeout: {self.config.browser_timeout_seconds}s)..."
                )
                cookies = await self._wait_for_auth_completion(
                    page, portal, timeout_ms
                )

                if not cookies:
                    raise RuntimeError(
                        f"Authentication to {portal.name} failed: no cookies captured"
                    )

                logger.info(
                    f"Authentication successful! Captured {len(cookies)} cookies"
                )
                return cookies

            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Login timed out after {self.config.browser_timeout_seconds}s. "
                    f"Please try again and complete the login faster."
                )
            finally:
                await context.close()
                await browser.close()

    async def _click_institutional_login(
        self, page: Page, portal: "PortalConfig"
    ) -> None:
        """Try to find and click the institutional/SSO login button on the page."""
        try:
            # Try multiple selector patterns
            selectors = portal.institutional_login_selector.split(", ")

            for selector in selectors:
                try:
                    element = await page.wait_for_selector(
                        selector.strip(), timeout=3000
                    )
                    if element:
                        await element.click()
                        logger.info(f"Clicked institutional login link: {selector}")
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        return
                except Exception:
                    continue

            # Also try text-based search
            text_patterns = [
                "Institutional",
                "institution",
                "Access through your institution",
                "Log in via your institution",
                "Shibboleth",
                "SSO",
            ]

            for text in text_patterns:
                try:
                    link = page.get_by_text(text, exact=False).first
                    if await link.is_visible(timeout=1000):
                        await link.click()
                        logger.info(f"Clicked institutional login by text: '{text}'")
                        await page.wait_for_load_state("networkidle", timeout=10000)
                        return
                except Exception:
                    continue

            logger.info(
                "No institutional login button found - "
                "user may need to navigate manually"
            )

        except Exception as e:
            logger.debug(f"Institutional login auto-click failed: {e}")

    async def _handle_wayf(self, page: Page) -> None:
        """Try to auto-select institution on a WAYF (Where Are You From) page."""
        institution_name = self.config.institution.wayf_institution_name
        if not institution_name:
            return

        try:
            # Look for search input on WAYF page
            search_selectors = [
                "input[type='search']",
                "input[type='text'][name*='institution']",
                "input[placeholder*='institution']",
                "input[placeholder*='search']",
                "#institution-search",
                ".search-input input",
                "input[id*='wayf']",
            ]

            for selector in search_selectors:
                try:
                    search_input = await page.wait_for_selector(
                        selector, timeout=2000
                    )
                    if search_input:
                        await search_input.fill(institution_name)
                        logger.info(
                            f"Typed institution name '{institution_name}' in WAYF search"
                        )
                        # Wait for results and try to click the first match
                        await page.wait_for_timeout(1500)

                        # Try clicking a result that matches
                        try:
                            result = page.get_by_text(
                                institution_name, exact=False
                            ).first
                            if await result.is_visible(timeout=2000):
                                await result.click()
                                logger.info("Selected institution from WAYF results")
                                await page.wait_for_load_state(
                                    "networkidle", timeout=10000
                                )
                        except Exception:
                            pass
                        return
                except Exception:
                    continue

            logger.info(
                "No WAYF search input found - user may need to select institution manually"
            )

        except Exception as e:
            logger.debug(f"WAYF handling failed: {e}")

    async def _wait_for_auth_completion(
        self,
        page: Page,
        portal: "PortalConfig",
        timeout_ms: int,
    ) -> list[dict]:
        """
        Wait for the user to complete the authentication flow.
        Monitors for navigation back to the portal's domain.
        """
        import urllib.parse

        portal_domain = urllib.parse.urlparse(portal.base_url).netloc
        start_time = asyncio.get_event_loop().time()
        max_time = start_time + (timeout_ms / 1000)

        while asyncio.get_event_loop().time() < max_time:
            current_url = page.url
            current_domain = urllib.parse.urlparse(current_url).netloc

            # Check if we've navigated back to the portal domain
            if portal_domain in current_domain:
                # Also check we're not still on the login page
                if "login" not in current_url.lower() and "sso" not in current_url.lower():
                    # Give a moment for cookies to settle
                    await page.wait_for_timeout(2000)

                    # Capture all cookies from the context
                    context = page.context
                    cookies = await context.cookies()

                    # Convert to serializable format
                    cookie_list = []
                    for cookie in cookies:
                        cookie_list.append({
                            "name": cookie["name"],
                            "value": cookie["value"],
                            "domain": cookie.get("domain", ""),
                            "path": cookie.get("path", "/"),
                            "secure": cookie.get("secure", False),
                            "httpOnly": cookie.get("httpOnly", False),
                            "sameSite": cookie.get("sameSite", "None"),
                            "expires": cookie.get("expires", -1),
                        })

                    if cookie_list:
                        return cookie_list

            # Also check if we're on a page that looks authenticated
            # (some portals don't redirect back)
            try:
                # Check for common "logged in" indicators
                logged_in_indicators = [
                    "[class*='logout']",
                    "[class*='sign-out']",
                    "[class*='user-menu']",
                    "[class*='account']",
                    "a[href*='logout']",
                ]
                for selector in logged_in_indicators:
                    try:
                        el = await page.wait_for_selector(selector, timeout=500)
                        if el:
                            await page.wait_for_timeout(1000)
                            cookies = await page.context.cookies()
                            return [
                                {
                                    "name": c["name"],
                                    "value": c["value"],
                                    "domain": c.get("domain", ""),
                                    "path": c.get("path", "/"),
                                    "secure": c.get("secure", False),
                                    "httpOnly": c.get("httpOnly", False),
                                    "sameSite": c.get("sameSite", "None"),
                                    "expires": c.get("expires", -1),
                                }
                                for c in cookies
                            ]
                    except Exception:
                        continue
            except Exception:
                pass

            await page.wait_for_timeout(1000)  # Poll every second

        raise asyncio.TimeoutError("Authentication timed out")


class EZProxyAuthenticator:
    """
    Handles EZProxy-based institutional access.
    Constructs proxied URLs and manages EZProxy session cookies.
    """

    def __init__(self, ezproxy_url: str):
        self.ezproxy_url = ezproxy_url.rstrip("/")

    def get_proxied_url(self, target_url: str) -> str:
        """Convert a publisher URL to its EZProxy-proxied equivalent."""
        import urllib.parse

        parsed = urllib.parse.urlparse(target_url)
        # Standard EZProxy URL rewriting pattern:
        # https://publisher.com/path -> https://publisher-com.proxy.library.edu/path
        proxied_host = parsed.netloc.replace(".", "-")
        proxy_parsed = urllib.parse.urlparse(self.ezproxy_url)
        proxied_netloc = f"{proxied_host}.{proxy_parsed.netloc}"
        return urllib.parse.urlunparse(
            (proxy_parsed.scheme, proxied_netloc, parsed.path,
             parsed.params, parsed.query, parsed.fragment)
        )

    def get_login_url(self, target_url: str) -> str:
        """Get the EZProxy login URL that will redirect to the target after auth."""
        import urllib.parse

        return (
            f"{self.ezproxy_url}/login?url="
            f"{urllib.parse.quote(target_url, safe='')}"
        )
