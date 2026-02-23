"""
Content extractor for Claude Research Gateway.
Extracts readable text from HTML article pages and PDF files.
"""

from __future__ import annotations

import io
import logging
import re
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from portals import PortalConfig

logger = logging.getLogger("claude-research")


class ContentExtractor:
    """Extracts and formats article content from HTML and PDF sources."""

    def __init__(self, max_length: int = 100_000):
        self.max_length = max_length

    # ──────────────────────── HTML Extraction ────────────────────────

    def extract_from_html(
        self,
        html: str,
        portal: "PortalConfig | None" = None,
    ) -> dict:
        """
        Extract article content from an HTML page.

        Returns dict with:
            title, authors, abstract, fulltext, metadata
        """
        soup = BeautifulSoup(html, "lxml")

        # Remove script, style, and nav elements
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()

        result = {
            "title": self._extract_title(soup, portal),
            "authors": self._extract_authors(soup, portal),
            "abstract": self._extract_abstract(soup, portal),
            "fulltext": self._extract_fulltext(soup, portal),
            "metadata": self._extract_metadata(soup, portal),
        }

        # Apply length limits
        if result["fulltext"] and len(result["fulltext"]) > self.max_length:
            result["fulltext"] = self._smart_truncate(result["fulltext"])
            result["truncated"] = True
        else:
            result["truncated"] = False

        return result

    def _extract_title(
        self, soup: BeautifulSoup, portal: "PortalConfig | None"
    ) -> str:
        selector = portal.article_title_selector if portal else "h1"
        el = soup.select_one(selector)
        if el:
            return el.get_text(strip=True)

        # Fallback: try meta tags
        meta_title = soup.find("meta", {"name": "citation_title"})
        if meta_title:
            return meta_title.get("content", "")

        # Last resort: page title
        title_tag = soup.find("title")
        return title_tag.get_text(strip=True) if title_tag else "Unknown Title"

    def _extract_authors(
        self, soup: BeautifulSoup, portal: "PortalConfig | None"
    ) -> list[str]:
        # Try meta tags first (most reliable)
        meta_authors = soup.find_all("meta", {"name": "citation_author"})
        if meta_authors:
            return [m.get("content", "").strip() for m in meta_authors if m.get("content")]

        # Try portal-specific selector
        if portal:
            selectors = portal.author_selector.split(", ")
            for selector in selectors:
                elements = soup.select(selector.strip())
                if elements:
                    return [el.get_text(strip=True) for el in elements]

        return []

    def _extract_abstract(
        self, soup: BeautifulSoup, portal: "PortalConfig | None"
    ) -> str:
        # Try meta description first
        meta_abstract = soup.find("meta", {"name": "citation_abstract"}) or \
                         soup.find("meta", {"name": "description"})

        # Try portal-specific selectors
        if portal:
            selectors = portal.abstract_selector.split(", ")
            for selector in selectors:
                el = soup.select_one(selector.strip())
                if el:
                    return el.get_text(strip=True)

        if meta_abstract:
            return meta_abstract.get("content", "").strip()

        return ""

    def _extract_fulltext(
        self, soup: BeautifulSoup, portal: "PortalConfig | None"
    ) -> str:
        if portal:
            selectors = portal.fulltext_selector.split(", ")
            for selector in selectors:
                elements = soup.select(selector.strip())
                if elements:
                    text_parts = []
                    for el in elements:
                        text_parts.append(el.get_text(separator="\n", strip=True))
                    combined = "\n\n".join(text_parts)
                    if len(combined) > 200:  # Meaningful content threshold
                        return combined

        # Fallback: try to find the main content area
        main_selectors = [
            "article",
            "main",
            "[role='main']",
            ".article-content",
            ".paper-content",
            "#main-content",
        ]
        for selector in main_selectors:
            el = soup.select_one(selector)
            if el:
                text = el.get_text(separator="\n", strip=True)
                if len(text) > 200:
                    return text

        return ""

    def _extract_metadata(
        self, soup: BeautifulSoup, portal: "PortalConfig | None"
    ) -> dict:
        """Extract structured metadata from meta tags."""
        metadata = {}

        meta_mappings = {
            "doi": "citation_doi",
            "journal": "citation_journal_title",
            "volume": "citation_volume",
            "issue": "citation_issue",
            "pages": "citation_firstpage",
            "date": "citation_publication_date",
            "publisher": "citation_publisher",
            "issn": "citation_issn",
            "pdf_url": "citation_pdf_url",
        }

        for key, meta_name in meta_mappings.items():
            meta = soup.find("meta", {"name": meta_name})
            if meta and meta.get("content"):
                metadata[key] = meta["content"].strip()

        # Also grab last page for proper page range
        if "pages" in metadata:
            last_page = soup.find("meta", {"name": "citation_lastpage"})
            if last_page and last_page.get("content"):
                metadata["pages"] = f"{metadata['pages']}-{last_page['content'].strip()}"

        return metadata

    # ──────────────────────── PDF Extraction ────────────────────────

    def extract_from_pdf(self, pdf_bytes: bytes) -> dict:
        """
        Extract text content from a PDF file.

        Returns dict with:
            fulltext, page_count, truncated
        """
        try:
            import pdfplumber

            text_parts = []
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page_count = len(pdf.pages)

                for i, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(f"--- Page {i + 1} ---\n{page_text}")

            fulltext = "\n\n".join(text_parts)
            truncated = False

            if len(fulltext) > self.max_length:
                fulltext = self._smart_truncate(fulltext)
                truncated = True

            return {
                "fulltext": fulltext,
                "page_count": page_count,
                "truncated": truncated,
            }

        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return {
                "fulltext": "",
                "page_count": 0,
                "truncated": False,
                "error": str(e),
            }

    # ──────────────────────── Smart Truncation ────────────────────────

    def _smart_truncate(self, text: str) -> str:
        """
        Intelligently truncate long text, keeping:
        - First ~40% (title, abstract, intro)
        - Last ~20% (conclusion, references)
        - A note about what was truncated
        """
        if len(text) <= self.max_length:
            return text

        front_limit = int(self.max_length * 0.55)
        back_limit = int(self.max_length * 0.35)

        front = text[:front_limit]
        back = text[-back_limit:]

        # Try to break at paragraph boundaries
        front_break = front.rfind("\n\n")
        if front_break > front_limit * 0.8:
            front = front[:front_break]

        back_break = back.find("\n\n")
        if back_break != -1 and back_break < back_limit * 0.2:
            back = back[back_break:]

        truncated_chars = len(text) - len(front) - len(back)

        return (
            f"{front}\n\n"
            f"[... {truncated_chars:,} characters truncated for length ...]\n\n"
            f"{back}"
        )

    # ──────────────────────── Formatting ────────────────────────

    @staticmethod
    def format_article(extracted: dict) -> str:
        """Format extracted article data into a clean readable string."""
        parts = []

        if extracted.get("title"):
            parts.append(f"# {extracted['title']}")

        if extracted.get("authors"):
            authors = extracted["authors"]
            if isinstance(authors, list):
                parts.append(f"**Authors:** {', '.join(authors)}")
            else:
                parts.append(f"**Authors:** {authors}")

        metadata = extracted.get("metadata", {})
        if metadata:
            meta_parts = []
            if metadata.get("journal"):
                meta_parts.append(f"*{metadata['journal']}*")
            if metadata.get("volume"):
                vol = metadata["volume"]
                if metadata.get("issue"):
                    vol += f"({metadata['issue']})"
                meta_parts.append(vol)
            if metadata.get("pages"):
                meta_parts.append(f"pp. {metadata['pages']}")
            if metadata.get("date"):
                meta_parts.append(metadata["date"])
            if metadata.get("doi"):
                meta_parts.append(f"DOI: {metadata['doi']}")
            if meta_parts:
                parts.append(" | ".join(meta_parts))

        parts.append("")  # blank line

        if extracted.get("abstract"):
            parts.append("## Abstract")
            parts.append(extracted["abstract"])
            parts.append("")

        if extracted.get("fulltext"):
            parts.append("## Full Text")
            parts.append(extracted["fulltext"])
        elif not extracted.get("abstract"):
            parts.append("*No content could be extracted from this page.*")

        if extracted.get("truncated"):
            parts.append(
                "\n---\n*Note: This article was truncated for length. "
                "The full text is longer than what's shown above.*"
            )

        return "\n".join(parts)

    @staticmethod
    def clean_text(text: str) -> str:
        """Clean extracted text, removing excess whitespace and artifacts."""
        # Collapse multiple blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Remove leading/trailing whitespace from lines
        lines = [line.strip() for line in text.split("\n")]
        text = "\n".join(lines)
        # Remove common artifacts
        text = re.sub(r"(?i)copyright\s*©.*?\n", "", text)
        text = re.sub(r"(?i)all rights reserved\.?\s*\n?", "", text)
        return text.strip()
