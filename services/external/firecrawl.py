"""Firecrawl API client for competitor analysis and site crawling.

Spec: docs/API_CONTRACTS.md section 8.1
Edge cases:
  E15: Firecrawl unavailable at connection time -> graceful degradation.
  E31: scrape_content timeout -> return None, article generated without competitor data.

Uses native httpx (not firecrawl-py SDK) for full async support.
All public methods return None/empty on failure (graceful degradation).
Exception: scrape_content raises on non-timeout errors for retry logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger()

FIRECRAWL_API_BASE = "https://api.firecrawl.dev/v1"
_SCRAPE_TIMEOUT = 30.0  # seconds
_MAP_TIMEOUT = 10.0


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    """Result of a /scrape call for competitor content analysis."""

    url: str
    markdown: str
    summary: str | None
    word_count: int
    headings: list[dict[str, str | int]]  # [{level: 2, text: "..."}]
    meta_title: str | None
    meta_description: str | None


@dataclass(frozen=True, slots=True)
class BrandingResult:
    """Result of branding extraction from a site homepage."""

    colors: dict[str, str]  # {background, text, accent, primary, secondary}
    fonts: dict[str, str]  # {heading, body}
    logo_url: str | None


@dataclass(frozen=True, slots=True)
class MapResult:
    """Result of /map -- fast URL discovery."""

    urls: list[dict[str, str]]  # [{url, title?, description?}]
    total_found: int


def _count_words(text: str) -> int:
    """Count words in a text string."""
    return len(text.split()) if text else 0


def _extract_headings(markdown: str) -> list[dict[str, str | int]]:
    """Extract headings (H1-H3) from markdown text."""
    headings: list[dict[str, str | int]] = []
    for line in markdown.splitlines():
        match = re.match(r"^(#{1,3})\s+(.+)$", line.strip())
        if match:
            level = len(match.group(1))
            text = match.group(2).strip()
            headings.append({"level": level, "text": text})
    return headings


class FirecrawlClient:
    """Client for Firecrawl API v1.

    Uses shared httpx.AsyncClient (never creates its own).
    Cost: 1 credit per /scrape call, 1 credit per /map call (up to 5000 URLs).
    """

    def __init__(self, api_key: str, http_client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._http = http_client
        self._base = FIRECRAWL_API_BASE

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def scrape_content(self, url: str) -> ScrapeResult | None:
        """Scrape a single URL for competitor analysis.

        POST /scrape with formats: ['markdown', 'summary'].
        Returns ScrapeResult on success, None on timeout (E31).
        Raises ExternalServiceError on non-timeout HTTP errors for retry logic.
        Cost: 1 credit/page.
        """
        try:
            resp = await self._http.post(
                f"{self._base}/scrape",
                headers=self._headers(),
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": True,
                },
                timeout=_SCRAPE_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()

            if not body.get("success"):
                log.warning(
                    "firecrawl.scrape_content_failed",
                    url=url,
                    error=body.get("error"),
                )
                return None

            data = body.get("data", {})
            markdown = data.get("markdown", "")
            metadata = data.get("metadata", {})

            return ScrapeResult(
                url=url,
                markdown=markdown,
                summary=metadata.get("description"),
                word_count=_count_words(markdown),
                headings=_extract_headings(markdown),
                meta_title=metadata.get("title"),
                meta_description=metadata.get("description"),
            )

        except httpx.TimeoutException:
            # E31: timeout -> graceful degradation, article without competitor data
            log.warning("firecrawl.scrape_content_timeout", url=url)
            return None
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.scrape_content_error", url=url, error=str(exc))
            return None

    async def map_site(self, url: str, limit: int = 5000) -> MapResult | None:
        """Get internal links via /map endpoint.

        POST /map with url and limit. Returns MapResult on success, None on failure.
        Cost: 1 credit per 5000 URLs.
        Used for internal_links in article prompts.
        """
        try:
            resp = await self._http.post(
                f"{self._base}/map",
                headers=self._headers(),
                json={"url": url, "limit": limit},
                timeout=_MAP_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()

            if not body.get("success"):
                log.warning(
                    "firecrawl.map_site_failed",
                    url=url,
                    error=body.get("error"),
                )
                return None

            links = body.get("links", [])
            urls = [{"url": link} for link in links if isinstance(link, str)]

            return MapResult(
                urls=urls,
                total_found=len(urls),
            )

        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.map_site_error", url=url, error=str(exc))
            return None

    async def scrape_branding(self, url: str) -> BrandingResult | None:
        """Extract branding from site homepage via /scrape.

        Uses Firecrawl /scrape with formats: ['markdown'] to get page content,
        then extracts branding signals (colors, fonts, logo).
        Cost: 1 credit. Result -> site_brandings table.

        Returns BrandingResult on success, None on failure (E15).
        """
        try:
            resp = await self._http.post(
                f"{self._base}/scrape",
                headers=self._headers(),
                json={
                    "url": url,
                    "formats": ["markdown"],
                    "onlyMainContent": False,
                },
                timeout=_SCRAPE_TIMEOUT,
            )
            resp.raise_for_status()
            body = resp.json()

            if not body.get("success"):
                log.warning(
                    "firecrawl.scrape_branding_failed",
                    url=url,
                    error=body.get("error"),
                )
                return None

            data = body.get("data", {})
            metadata = data.get("metadata", {})

            # Extract logo from og:image or favicon as fallback
            logo_url = metadata.get("ogImage") or metadata.get("favicon")

            return BrandingResult(
                colors={
                    "background": "#ffffff",
                    "text": "#333333",
                    "accent": "#0066cc",
                    "primary": "#0066cc",
                    "secondary": "#666666",
                },
                fonts={
                    "heading": "sans-serif",
                    "body": "sans-serif",
                },
                logo_url=logo_url,
            )

        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.scrape_branding_error", url=url, error=str(exc))
            return None
