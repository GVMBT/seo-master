"""Firecrawl API v2 client for competitor analysis, branding, and site crawling.

Spec: docs/API_CONTRACTS.md section 8.1
Edge cases:
  E15: Firecrawl unavailable at connection time -> graceful degradation.
  E31: scrape_content timeout -> return None, article generated without competitor data.

Uses native httpx (not firecrawl-py SDK) for full async support.
All public methods return None/empty on failure (graceful degradation).
Retry: C10 — retry on 429/5xx with backoff.

Endpoints used:
  POST /v2/scrape   — competitor content (markdown+summary), 1 credit
  POST /v2/map      — internal link discovery, 1 credit per 5000 URLs
  POST /v2/extract  — structured data via LLM (branding, competitor analysis), 5 credits
  POST /v2/search   — web search + scrape in one call, 2 credits per 10 results
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from services.http_retry import retry_with_backoff

log = structlog.get_logger()

FIRECRAWL_API_BASE = "https://api.firecrawl.dev/v2"
_SCRAPE_TIMEOUT = 30.0  # seconds
_EXTRACT_TIMEOUT = 60.0  # LLM extraction takes longer
_MAP_TIMEOUT = 10.0
_SEARCH_TIMEOUT = 30.0


@dataclass(frozen=True, slots=True)
class ScrapeResult:
    """Result of a /v2/scrape call for competitor content analysis."""

    url: str
    markdown: str
    summary: str | None
    word_count: int
    headings: list[dict[str, str | int]]  # [{level: 2, text: "..."}]
    meta_title: str | None
    meta_description: str | None


@dataclass(frozen=True, slots=True)
class BrandingResult:
    """Result of branding extraction via /v2/extract with LLM."""

    colors: dict[str, str]  # {background, text, accent, primary, secondary}
    fonts: dict[str, str]  # {heading, body}
    logo_url: str | None


@dataclass(frozen=True, slots=True)
class MapResult:
    """Result of /v2/map -- fast URL discovery."""

    urls: list[dict[str, str]]  # [{url, title?, description?}]
    total_found: int


@dataclass(frozen=True, slots=True)
class ExtractResult:
    """Result of /v2/extract -- LLM-structured data from URL."""

    data: dict[str, Any]
    source_url: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Single result from /v2/search."""

    url: str
    title: str
    description: str
    markdown: str | None


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


# Branding extraction schema for /v2/extract
_BRANDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "colors": {
            "type": "object",
            "properties": {
                "background": {"type": "string", "description": "Main background color as hex (#ffffff)"},
                "text": {"type": "string", "description": "Primary text color as hex"},
                "accent": {"type": "string", "description": "Accent/link color as hex"},
                "primary": {"type": "string", "description": "Primary brand color as hex"},
                "secondary": {"type": "string", "description": "Secondary brand color as hex"},
            },
        },
        "fonts": {
            "type": "object",
            "properties": {
                "heading": {"type": "string", "description": "Heading font family name"},
                "body": {"type": "string", "description": "Body text font family name"},
            },
        },
        "logo_url": {"type": "string", "description": "URL of the site logo image"},
    },
}


class FirecrawlClient:
    """Client for Firecrawl API v2.

    Uses shared httpx.AsyncClient (never creates its own).
    Cost: 1 credit/scrape, 1 credit/map (5000 URLs), 5 credits/extract, 2 credits/10 search results.
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

    async def _post(
        self,
        endpoint: str,
        json_data: dict[str, Any],
        timeout: float,
        operation: str,
    ) -> httpx.Response:
        """POST to a Firecrawl endpoint with retry on 429/5xx (C10)."""
        return await retry_with_backoff(
            lambda: self._http.post(
                f"{self._base}/{endpoint}",
                headers=self._headers(),
                json=json_data,
                timeout=timeout,
            ),
            max_retries=2,
            base_delay=1.0,
            operation=f"firecrawl_{operation}",
        )

    # ------------------------------------------------------------------
    # /v2/scrape — competitor content (markdown + summary)
    # ------------------------------------------------------------------

    async def scrape_content(self, url: str) -> ScrapeResult | None:
        """Scrape a single URL for competitor analysis.

        POST /v2/scrape with formats: ['markdown', 'summary'].
        Returns ScrapeResult on success, None on timeout (E31).
        Cost: 1 credit/page.
        """
        try:
            resp = await self._post(
                "scrape",
                {"url": url, "formats": ["markdown", "summary"], "onlyMainContent": True},
                timeout=_SCRAPE_TIMEOUT,
                operation="scrape_content",
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
            summary = data.get("summary") or metadata.get("description")

            return ScrapeResult(
                url=url,
                markdown=markdown,
                summary=summary,
                word_count=_count_words(markdown),
                headings=_extract_headings(markdown),
                meta_title=metadata.get("title"),
                meta_description=metadata.get("description"),
            )

        except httpx.TimeoutException:
            log.warning("firecrawl.scrape_content_timeout", url=url)
            return None
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.scrape_content_error", url=url, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # /v2/map — fast internal link discovery
    # ------------------------------------------------------------------

    async def map_site(self, url: str, limit: int = 5000) -> MapResult | None:
        """Get internal links via /v2/map endpoint.

        POST /v2/map with url and limit. Returns MapResult on success, None on failure.
        Cost: 1 credit per 5000 URLs.
        """
        try:
            resp = await self._post(
                "map",
                {"url": url, "limit": limit},
                timeout=_MAP_TIMEOUT,
                operation="map_site",
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

    # ------------------------------------------------------------------
    # /v2/extract — LLM-structured data extraction
    # ------------------------------------------------------------------

    async def extract(
        self,
        urls: list[str],
        prompt: str,
        schema: dict[str, Any] | None = None,
    ) -> ExtractResult | None:
        """Extract structured data from URLs via Firecrawl LLM.

        POST /v2/extract with urls, prompt, and optional JSON schema.
        Cost: ~5 credits per URL (1 scrape + 4 JSON mode).
        Returns ExtractResult on success, None on failure.
        """
        try:
            payload: dict[str, Any] = {
                "urls": urls,
                "prompt": prompt,
            }
            if schema:
                payload["schema"] = schema

            resp = await self._post(
                "extract",
                payload,
                timeout=_EXTRACT_TIMEOUT,
                operation="extract",
            )
            resp.raise_for_status()
            body = resp.json()

            if not body.get("success"):
                log.warning(
                    "firecrawl.extract_failed",
                    urls=urls,
                    error=body.get("error"),
                )
                return None

            data = body.get("data", {})
            return ExtractResult(
                data=data,
                source_url=urls[0] if urls else "",
            )

        except httpx.TimeoutException:
            log.warning("firecrawl.extract_timeout", urls=urls)
            return None
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.extract_error", urls=urls, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # /v2/extract — branding (replaces hardcoded scrape_branding)
    # ------------------------------------------------------------------

    async def scrape_branding(self, url: str) -> BrandingResult | None:
        """Extract branding (colors, fonts, logo) via /v2/extract with LLM.

        Uses structured extraction with _BRANDING_SCHEMA to get real CSS colors
        and fonts instead of hardcoded fallbacks.
        Cost: ~5 credits. Result -> site_brandings table.
        Returns BrandingResult on success, None on failure (E15).
        """
        try:
            result = await self.extract(
                urls=[url],
                prompt=(
                    "Extract the visual branding of this website: "
                    "main colors (background, text, accent/links, primary brand color, secondary), "
                    "font families for headings and body text, "
                    "and the URL of the site logo. "
                    "Return hex color codes (e.g. #ffffff)."
                ),
                schema=_BRANDING_SCHEMA,
            )

            if not result or not result.data:
                return None

            data = result.data
            colors = data.get("colors", {})
            fonts = data.get("fonts", {})

            return BrandingResult(
                colors={
                    "background": colors.get("background", "#ffffff"),
                    "text": colors.get("text", "#333333"),
                    "accent": colors.get("accent", "#0066cc"),
                    "primary": colors.get("primary", colors.get("accent", "#0066cc")),
                    "secondary": colors.get("secondary", "#666666"),
                },
                fonts={
                    "heading": fonts.get("heading", "sans-serif"),
                    "body": fonts.get("body", "sans-serif"),
                },
                logo_url=data.get("logo_url"),
            )

        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.scrape_branding_error", url=url, error=str(exc))
            return None

    # ------------------------------------------------------------------
    # /v2/search — web search + scrape (potential Serper replacement)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 5,
    ) -> list[SearchResult]:
        """Search the web and get scraped content in one call.

        POST /v2/search with query and limit.
        Cost: 2 credits per 10 results + 1 credit per scraped page.
        Returns list of SearchResult (empty on failure).

        Note: Does not provide People Also Ask (PAA) — Serper still needed for that.
        """
        try:
            resp = await self._post(
                "search",
                {
                    "query": query,
                    "limit": limit,
                    "scrapeOptions": {
                        "formats": ["markdown"],
                        "onlyMainContent": True,
                    },
                },
                timeout=_SEARCH_TIMEOUT,
                operation="search",
            )
            resp.raise_for_status()
            body = resp.json()

            if not body.get("success"):
                log.warning("firecrawl.search_failed", query=query, error=body.get("error"))
                return []

            results: list[SearchResult] = []
            for item in body.get("data", []):
                results.append(
                    SearchResult(
                        url=item.get("url", ""),
                        title=item.get("metadata", {}).get("title", ""),
                        description=item.get("metadata", {}).get("description", ""),
                        markdown=item.get("markdown"),
                    ),
                )
            return results

        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("firecrawl.search_error", query=query, error=str(exc))
            return []
