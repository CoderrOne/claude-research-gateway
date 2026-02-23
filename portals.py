"""
Portal configurations for scientific journal publishers.
Each portal defines URLs, CSS selectors, and authentication patterns needed
to search, fetch, and extract papers through institutional access.
"""

from pydantic import BaseModel


class PortalConfig(BaseModel):
    """Configuration for a scientific journal portal."""

    name: str
    key: str
    base_url: str
    login_url: str
    search_url_template: str
    doi_url_template: str = "https://doi.org/{doi}"

    # CSS selectors for content extraction
    article_title_selector: str = "h1"
    abstract_selector: str = ".abstract, #abstract, [class*='abstract']"
    fulltext_selector: str = (
        "article, .article-body, .article__body, "
        "#article-body, .fulltext, .NLM_sec"
    )
    pdf_link_selector: str = "a[href*='.pdf'], a[href*='/pdf/'], a.pdf-link"
    author_selector: str = ".author-name, .contrib-author, .loa__item"
    metadata_selector: str = ".article-citation, .citation, .article-header"

    # Session validation
    cookie_domains: list[str] = []
    session_test_path: str = "/"

    # Institutional login patterns
    institutional_login_selector: str = (
        "a[href*='institution'], a[href*='shibboleth'], "
        "a[href*='login'], .institution-login, "
        "a[href*='wayf'], button[class*='institution']"
    )
    wayf_search_selector: str = (
        "input[type='search'], input[type='text'][name*='institution'], "
        "#institution-search, .search-input"
    )


# ──────────────────────────────── Portal Definitions ────────────────────────────────

ACS_PORTAL = PortalConfig(
    name="ACS Publications",
    key="acs",
    base_url="https://pubs.acs.org",
    login_url="https://pubs.acs.org/action/ssostart?redirectUri=%2F",
    search_url_template="https://pubs.acs.org/action/doSearch?AllField={query}&startPage=0&pageSize=10",
    fulltext_selector=".article_content, .NLM_sec, .article-body",
    pdf_link_selector="a[href*='/doi/pdf/'], a.pdf-button",
    abstract_selector=".articleBody_abstractText, #abstractBox p",
    author_selector=".loa-info .hlFld-ContribAuthor",
    cookie_domains=["pubs.acs.org", ".acs.org"],
    session_test_path="/",
)

SCIFINDER_PORTAL = PortalConfig(
    name="SciFinder-n",
    key="scifinder",
    base_url="https://scifinder-n.cas.org",
    login_url="https://scifinder-n.cas.org/",
    search_url_template="https://scifinder-n.cas.org/search/reference?q={query}",
    fulltext_selector=".result-detail, .substance-detail",
    abstract_selector=".abstract-text",
    author_selector=".author-list",
    cookie_domains=["scifinder-n.cas.org", ".cas.org"],
    session_test_path="/",
)

ELSEVIER_PORTAL = PortalConfig(
    name="Elsevier / ScienceDirect",
    key="elsevier",
    base_url="https://www.sciencedirect.com",
    login_url="https://www.sciencedirect.com/user/institution/login",
    search_url_template="https://www.sciencedirect.com/search?qs={query}&show=10",
    fulltext_selector=".Body, #body, .article-content",
    pdf_link_selector="a.pdf-download, a[href*='/pdfft']",
    abstract_selector=".abstract, #abstracts .abstract",
    author_selector=".author-group .author",
    cookie_domains=["sciencedirect.com", ".elsevier.com"],
    session_test_path="/",
)

SPRINGER_PORTAL = PortalConfig(
    name="Springer / Nature",
    key="springer",
    base_url="https://link.springer.com",
    login_url="https://link.springer.com/signup-login",
    search_url_template="https://link.springer.com/search?query={query}&showAll=false",
    fulltext_selector=".main-content .c-article-body, .main-body",
    pdf_link_selector="a[data-track-action='download pdf'], a[href*='/content/pdf/']",
    abstract_selector="#Abs1-content, .c-article-section__content",
    author_selector=".c-article-author-list .c-author-list__item",
    cookie_domains=["link.springer.com", ".springer.com", ".nature.com"],
    session_test_path="/",
)

WILEY_PORTAL = PortalConfig(
    name="Wiley Online Library",
    key="wiley",
    base_url="https://onlinelibrary.wiley.com",
    login_url="https://onlinelibrary.wiley.com/action/ssostart?redirectUri=%2F",
    search_url_template="https://onlinelibrary.wiley.com/action/doSearch?AllField={query}&startPage=0&pageSize=10",
    fulltext_selector=".article-section__content, .article__body",
    pdf_link_selector="a[href*='/doi/epdf/'], a[href*='/doi/pdf/']",
    abstract_selector=".article-section--abstract, #abstract",
    author_selector=".loa-authors .author-info",
    cookie_domains=["onlinelibrary.wiley.com", ".wiley.com"],
    session_test_path="/",
)

IEEE_PORTAL = PortalConfig(
    name="IEEE Xplore",
    key="ieee",
    base_url="https://ieeexplore.ieee.org",
    login_url="https://ieeexplore.ieee.org/servlet/Login",
    search_url_template="https://ieeexplore.ieee.org/search/searchresult.jsp?queryText={query}&rowsPerPage=10",
    fulltext_selector=".section, .article-text",
    pdf_link_selector="a[href*='/stamp/stamp.jsp'], a.pdf-btn",
    abstract_selector=".abstract-text, div[class*='abstract']",
    author_selector=".authors-info span[class*='author']",
    cookie_domains=["ieeexplore.ieee.org", ".ieee.org"],
    session_test_path="/",
)

JSTOR_PORTAL = PortalConfig(
    name="JSTOR",
    key="jstor",
    base_url="https://www.jstor.org",
    login_url="https://www.jstor.org/action/ssostart",
    search_url_template="https://www.jstor.org/action/doBasicSearch?Query={query}&so=rel",
    fulltext_selector=".article-body, .page-scan-content",
    pdf_link_selector="a[data-qa='download-pdf'], a[href*='/pdf/']",
    abstract_selector=".abstract, [data-qa='abstract']",
    author_selector=".contrib, .author-name",
    cookie_domains=["jstor.org", ".jstor.org"],
    session_test_path="/",
)

PMC_PORTAL = PortalConfig(
    name="PubMed Central (PMC)",
    key="pmc",
    base_url="https://www.ncbi.nlm.nih.gov/pmc",
    login_url="https://www.ncbi.nlm.nih.gov/account/",
    search_url_template="https://www.ncbi.nlm.nih.gov/pmc/?term={query}",
    fulltext_selector=".jig-ncbiinpagenav .tsec, .article-body",
    pdf_link_selector="a.pdf-link, a[href*='/pdf/']",
    abstract_selector=".abstract, #abstract",
    author_selector=".contrib-group .contrib",
    cookie_domains=["ncbi.nlm.nih.gov", ".nih.gov"],
    session_test_path="/",
)


# ──────────────────────────────── Registry ────────────────────────────────

PORTALS: dict[str, PortalConfig] = {
    "acs": ACS_PORTAL,
    "scifinder": SCIFINDER_PORTAL,
    "elsevier": ELSEVIER_PORTAL,
    "springer": SPRINGER_PORTAL,
    "wiley": WILEY_PORTAL,
    "ieee": IEEE_PORTAL,
    "jstor": JSTOR_PORTAL,
    "pmc": PMC_PORTAL,
}


def get_portal(key: str) -> PortalConfig | None:
    """Get a portal configuration by its key."""
    return PORTALS.get(key.lower())


def list_portal_keys() -> list[str]:
    """Return all available portal keys."""
    return list(PORTALS.keys())


def list_portal_names() -> list[tuple[str, str]]:
    """Return list of (key, name) tuples for all portals."""
    return [(k, v.name) for k, v in PORTALS.items()]
