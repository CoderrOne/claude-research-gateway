"""
Claude Research Gateway - MCP Server
====================================

An MCP server that enables Claude to access paywalled scientific papers
through institutional authentication (EZProxy, Shibboleth/SAML).

Tools:
    - list_portals:        List available journal portals and session status
    - authenticate_portal: Open browser for institutional login
    - check_session:       Check if a session is still valid
    - search_papers:       Search for papers on a portal
    - fetch_paper:         Fetch and extract full text of a paper
    - configure_institution: Set up institution details for WAYF auto-select
"""

from __future__ import annotations

import asyncio
import logging
import sys

from mcp.server.fastmcp import FastMCP

from browser_auth import BrowserAuthenticator, EZProxyAuthenticator
from config import GatewayConfig, load_config, save_config, InstitutionConfig
from content_extractor import ContentExtractor
from paper_fetcher import PaperFetcher
from portals import PORTALS, get_portal, list_portal_names
from session_manager import SessionManager

# ──────────────────────── Logging ────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,  # MCP requires logging to stderr, NOT stdout
)
logger = logging.getLogger("claude-research")

# ──────────────────────── Initialize MCP Server ────────────────────────

mcp = FastMCP(
    "claude-research-gateway",
    instructions=(
        "Access paywalled scientific papers through institutional authentication. "
        "Supports ACS, SciFinder, Elsevier, Springer, Wiley, IEEE, JSTOR, and PMC."
    ),
)

# ──────────────────────── Global State ────────────────────────

_config: GatewayConfig | None = None
_session_manager: SessionManager | None = None
_content_extractor: ContentExtractor | None = None
_paper_fetcher: PaperFetcher | None = None


def _init() -> tuple[GatewayConfig, SessionManager, ContentExtractor, PaperFetcher]:
    """Lazy initialization of shared components."""
    global _config, _session_manager, _content_extractor, _paper_fetcher

    if _config is None:
        _config = load_config()
    if _session_manager is None:
        _session_manager = SessionManager(_config)
    if _content_extractor is None:
        _content_extractor = ContentExtractor(max_length=_config.max_content_length)
    if _paper_fetcher is None:
        _paper_fetcher = PaperFetcher(_config, _session_manager, _content_extractor)

    return _config, _session_manager, _content_extractor, _paper_fetcher


# ═══════════════════════════════════════════════════════════════════════
#                            MCP TOOLS
# ═══════════════════════════════════════════════════════════════════════


@mcp.tool()
async def list_portals() -> str:
    """
    List all available scientific journal portals and their authentication status.

    Returns a formatted list showing each portal's name, key, and whether
    you have an active authenticated session.
    """
    config, sessions, _, _ = _init()

    lines = [
        "# Available Research Portals\n",
        f"{'Portal':<30} {'Key':<12} {'Session':<15} {'Age'}",
        f"{'─' * 30} {'─' * 12} {'─' * 15} {'─' * 10}",
    ]

    for key, name in list_portal_names():
        has_session = sessions.has_session(key)
        if has_session:
            info = sessions.get_session_info(key)
            age = f"{info['age_hours']}h ago" if info else "unknown"
            status = "✅ Active"
        else:
            status = "❌ None"
            age = "—"

        lines.append(f"{name:<30} {key:<12} {status:<15} {age}")

    lines.append("")
    lines.append(
        "💡 Use `authenticate_portal` with a portal key to log in."
    )

    if config.institution.name:
        lines.append(f"\n🏛️  Institution: {config.institution.name}")

    return "\n".join(lines)


@mcp.tool()
async def authenticate_portal(portal_key: str) -> str:
    """
    Open a browser window for institutional login to a scientific journal portal.

    A browser window will appear where you can enter your institutional
    credentials (Shibboleth/SAML SSO). After successful login, the session
    is saved so you don't need to log in again until the session expires.

    Args:
        portal_key: The portal to authenticate (e.g. 'acs', 'elsevier', 'springer').
                     Use list_portals to see available options.
    """
    config, sessions, _, _ = _init()

    portal = get_portal(portal_key)
    if not portal:
        available = ", ".join(k for k, _ in list_portal_names())
        return f"❌ Unknown portal: '{portal_key}'. Available: {available}"

    # Check if already authenticated
    if sessions.has_session(portal_key):
        info = sessions.get_session_info(portal_key)
        if info and info["age_hours"] < 12:  # Less than 12 hours old
            return (
                f"✅ You already have an active session for {portal.name} "
                f"({info['age_hours']}h old, {info['cookie_count']} cookies).\n"
                f"Use `check_session` to verify it's still valid, or "
                f"proceed with `search_papers` or `fetch_paper`."
            )

    try:
        auth = BrowserAuthenticator(config)

        logger.info(f"Starting authentication for {portal.name}...")

        # Determine if we should use EZProxy
        login_url = portal.login_url
        if config.institution.ezproxy_url:
            ezproxy = EZProxyAuthenticator(config.institution.ezproxy_url)
            login_url = ezproxy.get_login_url(portal.base_url)
            logger.info(f"Using EZProxy login: {login_url}")

        cookies = await auth.authenticate(portal, headless=False)

        # Save the session
        sessions.save_cookies(portal_key, cookies)

        return (
            f"✅ Successfully authenticated to {portal.name}!\n"
            f"📦 Saved {len(cookies)} session cookies.\n\n"
            f"You can now:\n"
            f"  • `search_papers('{portal_key}', 'your query')` — Search for papers\n"
            f"  • `fetch_paper('{portal_key}', doi='10.xxxx/...')` — Fetch a specific paper\n"
        )

    except TimeoutError as e:
        return f"⏰ {str(e)}"
    except Exception as e:
        logger.error(f"Authentication failed: {e}", exc_info=True)
        return (
            f"❌ Authentication to {portal.name} failed: {str(e)}\n"
            f"Please try again. Make sure to complete the login in the browser window."
        )


@mcp.tool()
async def check_session(portal_key: str) -> str:
    """
    Check if your authenticated session for a portal is still valid.

    Args:
        portal_key: The portal to check (e.g. 'acs', 'elsevier').
    """
    config, sessions, _, _ = _init()

    portal = get_portal(portal_key)
    if not portal:
        return f"❌ Unknown portal: '{portal_key}'"

    if not sessions.has_session(portal_key):
        return (
            f"❌ No session found for {portal.name}.\n"
            f"Use `authenticate_portal('{portal_key}')` to log in."
        )

    info = sessions.get_session_info(portal_key)
    is_valid = await sessions.validate_session(portal)

    if is_valid:
        return (
            f"✅ Session for {portal.name} is **valid**.\n"
            f"📦 {info['cookie_count']} cookies | "
            f"Saved {info['age_hours']}h ago"
        )
    else:
        sessions.delete_session(portal_key)
        return (
            f"❌ Session for {portal.name} has **expired**.\n"
            f"Use `authenticate_portal('{portal_key}')` to log in again."
        )


@mcp.tool()
async def search_papers(
    portal_key: str,
    query: str,
    max_results: int = 10,
) -> str:
    """
    Search for scientific papers on an authenticated portal.

    Args:
        portal_key: The portal to search (e.g. 'acs', 'elsevier', 'springer').
        query: Search query - keywords, title, author name, etc.
        max_results: Maximum number of results to return (default: 10, max: 25).
    """
    config, sessions, _, fetcher = _init()

    portal = get_portal(portal_key)
    if not portal:
        return f"❌ Unknown portal: '{portal_key}'"

    if not sessions.has_session(portal_key):
        return (
            f"❌ Not authenticated to {portal.name}.\n"
            f"Use `authenticate_portal('{portal_key}')` first."
        )

    max_results = min(max_results, 25)

    results = await fetcher.search(portal, query, max_results)

    if not results:
        return f"No results found for '{query}' on {portal.name}."

    if results and "error" in results[0]:
        return f"❌ Search error: {results[0]['error']}"

    # Format results
    lines = [
        f"# Search Results: '{query}' on {portal.name}\n",
        f"Found {len(results)} result(s):\n",
    ]

    for i, r in enumerate(results, 1):
        lines.append(f"## {i}. {r.get('title', 'Untitled')}")
        if r.get("authors"):
            lines.append(f"   **Authors:** {r['authors']}")
        if r.get("journal"):
            lines.append(f"   **Journal:** {r['journal']}")
        if r.get("doi"):
            lines.append(f"   **DOI:** {r['doi']}")
        if r.get("url"):
            lines.append(f"   **URL:** {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        lines.append("")

    lines.append(
        "💡 Use `fetch_paper` with a DOI or URL to get the full text."
    )

    return "\n".join(lines)


@mcp.tool()
async def fetch_paper(
    portal_key: str,
    doi: str = "",
    url: str = "",
) -> str:
    """
    Fetch the full text of a scientific paper using your institutional access.

    Provide either a DOI or direct URL. The tool will download the paper,
    extract the text (from HTML or PDF), and return it formatted for reading.

    Args:
        portal_key: The portal the paper is from (e.g. 'acs', 'elsevier').
                     If unsure, the tool will try to auto-detect from the URL.
        doi: The DOI of the paper (e.g. '10.1021/jacs.3c12345').
        url: Direct URL to the paper page.
    """
    config, sessions, extractor, fetcher = _init()

    if not doi and not url:
        return "❌ Please provide either a DOI or URL for the paper."

    # Try auto-detecting portal from URL/DOI
    if not portal_key and url:
        detected = PaperFetcher.detect_portal_from_url(url)
        if detected:
            portal_key = detected

    if not portal_key and doi:
        resolved_url = await fetcher.resolve_doi(doi)
        if resolved_url:
            detected = PaperFetcher.detect_portal_from_url(resolved_url)
            if detected:
                portal_key = detected
                url = resolved_url

    portal = get_portal(portal_key)
    if not portal:
        return (
            f"❌ Could not determine portal. Please specify portal_key.\n"
            f"Available: {', '.join(k for k, _ in list_portal_names())}"
        )

    if not sessions.has_session(portal_key):
        return (
            f"❌ Not authenticated to {portal.name}.\n"
            f"Use `authenticate_portal('{portal_key}')` first."
        )

    result = await fetcher.fetch_paper(
        portal,
        url=url or None,
        doi=doi or None,
    )

    if "error" in result:
        return f"❌ {result['error']}"

    # Format the output
    formatted = ContentExtractor.format_article(result)

    # Add source info header
    source_info = f"📄 **Source:** {portal.name}"
    if result.get("doi"):
        source_info += f" | DOI: {result['doi']}"
    if result.get("source"):
        source_info += f" | Extracted from: {result['source'].upper()}"
    if result.get("truncated"):
        source_info += " | ⚠️ Truncated for length"

    return f"{source_info}\n\n{formatted}"


@mcp.tool()
async def configure_institution(
    name: str = "",
    ezproxy_url: str = "",
    wayf_name: str = "",
) -> str:
    """
    Configure your institutional details for automatic WAYF selection
    and EZProxy integration.

    Args:
        name: Your institution's name (e.g. 'MIT', 'Stanford University').
        ezproxy_url: Your library's EZProxy URL (e.g. 'https://ezproxy.library.edu/login').
                     Leave empty if your institution uses Shibboleth directly.
        wayf_name: Institution name as it appears in WAYF dropdowns.
                   Often the full formal name (e.g. 'Massachusetts Institute of Technology').
    """
    config, _, _, _ = _init()
    global _config

    if name:
        config.institution.name = name
    if ezproxy_url:
        config.institution.ezproxy_url = ezproxy_url
    if wayf_name:
        config.institution.wayf_institution_name = wayf_name

    save_config(config)
    _config = config

    lines = ["✅ Institution configuration updated:\n"]
    lines.append(f"  🏛️  Name: {config.institution.name or '(not set)'}")
    lines.append(f"  🔗 EZProxy: {config.institution.ezproxy_url or '(not set)'}")
    lines.append(f"  🏷️  WAYF Name: {config.institution.wayf_institution_name or '(not set)'}")
    lines.append("")
    lines.append(
        "This will be used to auto-select your institution during login flows."
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#                            ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════


def main():
    """Run the Claude Research Gateway MCP server."""
    logger.info("Starting Claude Research Gateway MCP server...")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
