# Claude Research Gateway 🔬

An MCP (Model Context Protocol) server that enables Claude to access **paywalled scientific papers** through your **institutional login** (Shibboleth/SAML SSO, EZProxy).

> **How it works:** When you ask Claude to find or read a paper, this tool authenticates to journal portals using your university credentials (via a browser popup), then fetches the full text of papers you have institutional access to.

## Supported Portals

| Portal | Key | Publisher |
|--------|-----|-----------|
| ACS Publications | `acs` | American Chemical Society |
| SciFinder-n | `scifinder` | CAS |
| ScienceDirect | `elsevier` | Elsevier |
| Springer / Nature | `springer` | Springer Nature |
| Wiley Online Library | `wiley` | Wiley |
| IEEE Xplore | `ieee` | IEEE |
| JSTOR | `jstor` | JSTOR |
| PubMed Central | `pmc` | NIH / NLM |

## Prerequisites

- **Python 3.10+**
- **uv** (Python package manager): `pip install uv`
- A valid **institutional login** (university SSO credentials)

## Quick Setup

### 1. Install Dependencies

```bash
cd claude-tool-research
uv sync
```

### 2. Install Playwright Browsers

```bash
uv run playwright install chromium
```

### 3. Add to Claude Desktop

Edit your Claude Desktop config file:

- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Add this MCP server entry:

```json
{
  "mcpServers": {
    "research-gateway": {
      "command": "uv",
      "args": [
        "--directory",
        "C:\\Users\\abdir\\Documents\\projects-code\\claude-tool-research",
        "run",
        "server.py"
      ]
    }
  }
}
```

### 4. Restart Claude Desktop

Close and reopen Claude Desktop. You should see the research tools appear in the tools menu (🔨 icon).

## Usage Examples

### First-Time Setup

```
You: "Configure my institution — I'm at MIT"
Claude: [Calls configure_institution with name="MIT", wayf_name="Massachusetts Institute of Technology"]

You: "Log me into ACS Publications"  
Claude: [Calls authenticate_portal("acs")]
→ A browser window opens → You complete your university SSO login → Session is saved
```

### Searching Papers

```
You: "Search ACS for papers about lithium-ion battery cathodes published recently"
Claude: [Calls search_papers("acs", "lithium-ion battery cathode materials")]
→ Returns formatted search results with titles, authors, DOIs
```

### Reading a Paper

```
You: "Fetch the full text of DOI 10.1021/jacs.3c12345"
Claude: [Calls fetch_paper("acs", doi="10.1021/jacs.3c12345")]
→ Downloads and extracts the full paper text for Claude to read and discuss
```

### Checking Session

```
You: "Is my ACS session still active?"
Claude: [Calls check_session("acs")]
→ Reports session status and age
```

## Available Tools

| Tool | Description |
|------|-------------|
| `list_portals` | Shows all portals and your login status for each |
| `authenticate_portal` | Opens browser for institutional SSO login |
| `check_session` | Verifies if a session is still valid |
| `search_papers` | Searches for papers by keywords, title, etc. |
| `fetch_paper` | Downloads and extracts full paper text (via DOI or URL) |
| `configure_institution` | Sets up your institution name, EZProxy URL, WAYF name |

## How Authentication Works

```
┌─────────────┐    ┌──────────────┐    ┌────────────────┐    ┌──────────────┐
│   Claude     │───▶│  MCP Server  │───▶│  Playwright    │───▶│  Publisher   │
│  (asks for   │    │  (manages    │    │  Browser       │    │  Login Page  │
│   a paper)   │    │   sessions)  │    │  (visible)     │    │  (SSO/SAML)  │
└─────────────┘    └──────────────┘    └────────────────┘    └──────────────┘
                                              │                       │
                                              │    ┌──────────────┐   │
                                              └───▶│  Your Univ.  │◀──┘
                                                   │  IdP (SSO)   │
                                                   └──────────────┘
                                                          │
                                                   You enter your
                                                   credentials here
```

1. Claude calls `authenticate_portal` → a **real browser window** opens
2. The browser navigates to the publisher's institutional login
3. You're redirected to your university's SSO page (Shibboleth/SAML)
4. **You enter your credentials** in the browser
5. After successful login, the tool captures the session cookies
6. Cookies are **encrypted** and stored locally in `~/.claude-research/sessions/`
7. Subsequent requests use these cookies — no browser needed until they expire

## Security Notes

- **No credentials stored**: Only session cookies are saved, never your password
- **Encrypted storage**: Cookies are encrypted with a machine-local key (Fernet)
- **Session expiry**: Sessions follow your institution's expiry policy (typically 8–24h)
- **Local only**: All data stays on your machine in `~/.claude-research/`

## Configuration

Optional: create `~/.claude-research/config.json`:

```json
{
  "institution": {
    "name": "MIT",
    "ezproxy_url": "https://ezproxy.library.mit.edu/login",
    "wayf_institution_name": "Massachusetts Institute of Technology"
  },
  "rate_limit_seconds": 1.0,
  "max_content_length": 100000,
  "browser_timeout_seconds": 300
}
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Browser doesn't open | Run `uv run playwright install chromium` |
| Login times out | Increase `browser_timeout_seconds` in config |
| Session expired quickly | Your institution may have short session limits; re-authenticate |
| Paper text is empty | Some publishers serve content via JavaScript — try the PDF version |
| "Access denied" error | Re-authenticate with `authenticate_portal` |

## License

MIT
