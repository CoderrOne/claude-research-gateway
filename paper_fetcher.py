"""
Paper fetcher for Claude Research Gateway.
Fetches papers from publisher websites using authenticated sessions.
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
from typing import TYPE_CHECKING

import httpx
from bs4 import BeautifulSoup

from content_extractor import ContentExtractor
from session_manager import SessionManager

if TYPE_CHECKING:
    from config import GatewayConfig
    from portals import PortalConfig

logger = logging.getLogger("claude-research")

# Common user agent to avoid bot detection
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


class PaperFetcher:
    """Fetches and extracts content from scientific papers using authenticated sessions."""

    def __init__(
        self,
        config: "GatewayConfig",
        session_manager: SessionManager,
        content_extractor: ContentExtractor,
    ):
        self.config = config
        self.sessions = session_manager
        self.extractor = content_extractor
        self._rate_limiter = asyncio.Semaphore(1)
        self._last_request_time = 0.0

    # ──────────────────────── Rate Limiting ────────────────────────

    async def _rate_limit(self) -> None:
        """Enforce rate limiting between requests."""
        async with self._rate_limiter:
            now = asyncio.get_event_loop().time()
            elapsed = now - self._last_request_time
            if elapsed < self.config.rate_limit_seconds:
                await asyncio.sleep(self.config.rate_limit_seconds - elapsed)
            self._last_request_time = asyncio.get_event_loop().time()

    # ──────────────────────── HTTP Client ────────────────────────

    def _create_client(self, portal_key: str) -> httpx.AsyncClient:
        """Create an HTTP client with session cookies injected."""
        client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": (
                    "text/html,application/xhtml+xml,application/xml;"
                    "q=0.9,*/*;q=0.8"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        # Inject authenticated cookies
        self.sessions.inject_cookies(client, portal_key)
        return client

    # ──────────────────────── DOI Resolution ────────────────────────

    async def resolve_doi(self, doi: str) -> str | None:
        """Resolve a DOI to its publisher URL."""
        await self._rate_limit()

        async with httpx.AsyncClient(
            follow_redirects=False, timeout=15.0,
            headers={"User-Agent": USER_AGENT}
        ) as client:
            try:
                response = await client.get(f"https://doi.org/{doi}")
                if response.status_code in (301, 302, 303, 307, 308):
                    return response.headers.get("location")
                elif response.status_code == 200:
                    return str(response.url)
            except Exception as e:
                logger.error(f"DOI resolution failed for {doi}: {e}")

        return None

    # ──────────────────────── Search ────────────────────────

    async def search(
        self,
        portal: "PortalConfig",
        query: str,
        max_results: int = 10,
    ) -> list[dict]:
        """
        Search for papers on a portal.

        Returns list of result dicts with: title, authors, doi, url, snippet
        """
        await self._rate_limit()

        search_url = portal.search_url_template.format(
            query=urllib.parse.quote(query)
        )

        client = self._create_client(portal.key)
        try:
            response = await client.get(search_url)
            response.raise_for_status()

            results = self._parse_search_results(
                response.text, portal, max_results
            )
            return results

        except httpx.HTTPStatusError as e:
            logger.error(f"Search failed on {portal.name}: {e.response.status_code}")
            return [{"error": f"Search failed: HTTP {e.response.status_code}"}]
        except Exception as e:
            logger.error(f"Search error on {portal.name}: {e}")
            return [{"error": f"Search error: {str(e)}"}]
        finally:
            await client.aclose()

    def _parse_search_results(
        self,
        html: str,
        portal: "PortalConfig",
        max_results: int,
    ) -> list[dict]:
        """Parse search results from a publisher's search page."""
        soup = BeautifulSoup(html, "lxml")
        results = []

        # Try to find result items using common patterns
        result_selectors = [
            ".search-result",
            ".result-item",
            ".searchResultItem",
            ".article-entry",
            ".issue-item",
            "li.result",
            ".search-results-item",
            ".card-item",
        ]

        items = []
        for selector in result_selectors:
            items = soup.select(selector)
            if items:
                break

        if not items:
            # Fallback: look for h2/h3 links that look like article titles
            items = soup.select("h2 a, h3 a, .title a")
            items = [item.parent for item in items[:max_results]]

        for item in items[:max_results]:
            result = self._parse_single_result(item, portal)
            if result:
                results.append(result)

        return results

    def _parse_single_result(
        self, item: "BeautifulSoup", portal: "PortalConfig"
    ) -> dict | None:
        """Parse a single search result item."""
        result = {}

        # Title
        title_el = (
            item.select_one("h2 a, h3 a, .title a, .result-title a") or
            item.select_one("h2, h3, .title, .result-title")
        )
        if title_el:
            result["title"] = title_el.get_text(strip=True)
            if title_el.name == "a" or title_el.find("a"):
                link = title_el if title_el.name == "a" else title_el.find("a")
                href = link.get("href", "")
                if href and not href.startswith("http"):
                    href = portal.base_url.rstrip("/") + "/" + href.lstrip("/")
                result["url"] = href
        else:
            return None  # Skip results without titles

        # DOI
        doi_el = item.select_one("a[href*='doi.org'], [data-doi]")
        if doi_el:
            if doi_el.get("data-doi"):
                result["doi"] = doi_el["data-doi"]
            else:
                href = doi_el.get("href", "")
                doi_match = re.search(r"10\.\d{4,}/[^\s]+", href)
                if doi_match:
                    result["doi"] = doi_match.group()

        # Authors
        author_el = item.select_one(
            ".author, .authors, .contrib, .result-author"
        )
        if author_el:
            result["authors"] = author_el.get_text(strip=True)

        # Snippet/abstract
        snippet_el = item.select_one(
            ".snippet, .abstract, .description, p"
        )
        if snippet_el:
            result["snippet"] = snippet_el.get_text(strip=True)[:300]

        # Journal
        journal_el = item.select_one(
            ".journal, .source, .publication"
        )
        if journal_el:
            result["journal"] = journal_el.get_text(strip=True)

        return result

    # ──────────────────────── Paper Fetching ────────────────────────

    async def fetch_paper(
        self,
        portal: "PortalConfig",
        url: str | None = None,
        doi: str | None = None,
    ) -> dict:
        """
        Fetch and extract the full text of a paper.

        Provide either a direct URL or a DOI. If DOI is given,
        it will be resolved to a URL first.

        Returns dict with extracted article content.
        """
        if not url and not doi:
            return {"error": "Either url or doi must be provided"}

        # Resolve DOI to URL if needed
        if doi and not url:
            url = await self.resolve_doi(doi)
            if not url:
                return {"error": f"Could not resolve DOI: {doi}"}

        # Try HTML extraction first
        result = await self._fetch_html(portal, url)

        # If HTML extraction got minimal content, try PDF
        if not result.get("fulltext") or len(result.get("fulltext", "")) < 500:
            pdf_result = await self._fetch_pdf(portal, url, result)
            if pdf_result and pdf_result.get("fulltext"):
                result.update(pdf_result)
                result["source"] = "pdf"
            else:
                result["source"] = "html"
        else:
            result["source"] = "html"

        result["url"] = url
        if doi:
            result["doi"] = doi

        return result

    async def _fetch_html(
        self, portal: "PortalConfig", url: str
    ) -> dict:
        """Fetch and extract content from the HTML article page."""
        await self._rate_limit()

        client = self._create_client(portal.key)
        try:
            response = await client.get(url)
            response.raise_for_status()

            # Check if we were redirected to a login page
            final_url = str(response.url).lower()
            if any(kw in final_url for kw in ["login", "sso", "shibboleth", "wayf"]):
                return {
                    "error": (
                        "Session expired - redirected to login page. "
                        "Please re-authenticate using authenticate_portal."
                    )
                }

            extracted = self.extractor.extract_from_html(response.text, portal)
            return extracted

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                return {
                    "error": (
                        "Access denied (403). Your session may have expired. "
                        "Try re-authenticating with authenticate_portal."
                    )
                }
            return {"error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            return {"error": f"Fetch error: {str(e)}"}
        finally:
            await client.aclose()

    async def _fetch_pdf(
        self,
        portal: "PortalConfig",
        article_url: str,
        html_result: dict,
    ) -> dict | None:
        """Try to find and download the PDF version of the article."""
        await self._rate_limit()

        # First, try to find PDF URL from the HTML metadata
        pdf_url = html_result.get("metadata", {}).get("pdf_url")

        if not pdf_url:
            # Try to find PDF link on the article page
            client = self._create_client(portal.key)
            try:
                response = await client.get(article_url)
                soup = BeautifulSoup(response.text, "lxml")

                selectors = portal.pdf_link_selector.split(", ")
                for selector in selectors:
                    link = soup.select_one(selector.strip())
                    if link:
                        pdf_url = link.get("href", "")
                        if pdf_url and not pdf_url.startswith("http"):
                            pdf_url = (
                                portal.base_url.rstrip("/")
                                + "/"
                                + pdf_url.lstrip("/")
                            )
                        break
            except Exception as e:
                logger.debug(f"PDF link search failed: {e}")
                return None
            finally:
                await client.aclose()

        if not pdf_url:
            return None

        # Download PDF
        await self._rate_limit()
        client = self._create_client(portal.key)
        try:
            response = await client.get(pdf_url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "pdf" in content_type or pdf_url.endswith(".pdf"):
                return self.extractor.extract_from_pdf(response.content)
            else:
                logger.debug(f"PDF URL returned non-PDF content: {content_type}")
                return None

        except Exception as e:
            logger.debug(f"PDF download failed: {e}")
            return None
        finally:
            await client.aclose()

    # ──────────────────────── Utility ────────────────────────

    @staticmethod
    def detect_portal_from_url(url: str) -> str | None:
        """Try to detect which portal a URL belongs to based on domain."""
        from portals import PORTALS

        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.lower()

        domain_map = {
            "pubs.acs.org": "acs",
            "acs.org": "acs",
            "scifinder-n.cas.org": "scifinder",
            "cas.org": "scifinder",
            "sciencedirect.com": "elsevier",
            "elsevier.com": "elsevier",
            "link.springer.com": "springer",
            "springer.com": "springer",
            "nature.com": "springer",
            "onlinelibrary.wiley.com": "wiley",
            "wiley.com": "wiley",
            "ieeexplore.ieee.org": "ieee",
            "ieee.org": "ieee",
            "jstor.org": "jstor",
            "ncbi.nlm.nih.gov": "pmc",
        }

        for domain_pattern, portal_key in domain_map.items():
            if domain_pattern in domain:
                return portal_key

        return None
