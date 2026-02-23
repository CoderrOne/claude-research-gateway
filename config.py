"""
User configuration for Claude Research Gateway.
Handles institution-specific settings and runtime preferences.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger("claude-research")

# Default data directory
DEFAULT_DATA_DIR = Path.home() / ".claude-research"


class InstitutionConfig(BaseModel):
    """Configuration for the user's institution."""

    name: str = ""
    ezproxy_url: str = ""
    shibboleth_idp: str = ""
    wayf_institution_name: str = ""


class GatewayConfig(BaseModel):
    """Top-level configuration for the Research Gateway."""

    institution: InstitutionConfig = Field(default_factory=InstitutionConfig)
    data_dir: str = str(DEFAULT_DATA_DIR)
    rate_limit_seconds: float = 1.0
    max_content_length: int = 100_000  # ~100k chars for Claude context
    headless_after_first_login: bool = True
    browser_timeout_seconds: int = 300  # 5 min for user to complete login
    default_portals: list[str] = Field(
        default_factory=lambda: ["acs", "elsevier", "springer", "wiley"]
    )

    @property
    def sessions_dir(self) -> Path:
        p = Path(self.data_dir) / "sessions"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def cache_dir(self) -> Path:
        p = Path(self.data_dir) / "cache"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def config_file(self) -> Path:
        return Path(self.data_dir) / "config.json"


def load_config() -> GatewayConfig:
    """Load configuration from disk, or return defaults."""
    config_path = DEFAULT_DATA_DIR / "config.json"

    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return GatewayConfig(**data)
        except Exception as e:
            logger.warning(f"Failed to load config from {config_path}: {e}")

    return GatewayConfig()


def save_config(config: GatewayConfig) -> None:
    """Save configuration to disk."""
    config_path = Path(config.data_dir) / "config.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)

    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config.model_dump(), f, indent=2)
    logger.info(f"Configuration saved to {config_path}")


def get_data_dir() -> Path:
    """Get the data directory, creating it if needed."""
    data_dir = Path(os.environ.get("CLAUDE_RESEARCH_DATA_DIR", str(DEFAULT_DATA_DIR)))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
