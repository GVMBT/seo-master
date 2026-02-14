"""Tests for services/external/firecrawl.py -- Firecrawl API client.

Covers: scrape_content (success, timeout E31, API error, non-success response),
map_site (success, error, empty), scrape_branding (success, error),
helper functions (_count_words, _extract_headings).
"""

from __future__ import annotations

import httpx

from services.external.firecrawl import (
    BrandingResult,
    FirecrawlClient,
    MapResult,
    ScrapeResult,
    _count_words,
    _extract_headings,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API_KEY = "fc-test-key"


def _make_client(handler: object) -> FirecrawlClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.AsyncClient(transport=transport)
    return FirecrawlClient(api_key=API_KEY, http_client=http)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_scrape_result_creation(self) -> None:
        result = ScrapeResult(
            url="https://example.com",
            markdown="# Hello",
            summary="A greeting",
            word_count=1,
            headings=[{"level": 1, "text": "Hello"}],
            meta_title="Hello Page",
            meta_description="desc",
        )
        assert result.url == "https://example.com"
        assert result.word_count == 1

    def test_branding_result_creation(self) -> None:
        result = BrandingResult(
            colors={"text": "#000", "accent": "#f00"},
            fonts={"heading": "Arial", "body": "Helvetica"},
            logo_url="https://example.com/logo.png",
        )
        assert result.logo_url == "https://example.com/logo.png"

    def test_map_result_creation(self) -> None:
        result = MapResult(
            urls=[{"url": "https://example.com/page1"}],
            total_found=1,
        )
        assert result.total_found == 1


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_count_words_normal(self) -> None:
        assert _count_words("hello world foo bar") == 4

    def test_count_words_empty(self) -> None:
        assert _count_words("") == 0

    def test_extract_headings_h1_h2_h3(self) -> None:
        md = "# Title\n## Section\n### Subsection\nParagraph text"
        headings = _extract_headings(md)
        assert len(headings) == 3
        assert headings[0] == {"level": 1, "text": "Title"}
        assert headings[1] == {"level": 2, "text": "Section"}
        assert headings[2] == {"level": 3, "text": "Subsection"}

    def test_extract_headings_no_headings(self) -> None:
        md = "Just some text\nMore text"
        headings = _extract_headings(md)
        assert headings == []

    def test_extract_headings_ignores_h4_plus(self) -> None:
        md = "#### Not captured\n##### Also not"
        headings = _extract_headings(md)
        assert headings == []


# ---------------------------------------------------------------------------
# scrape_content
# ---------------------------------------------------------------------------


class TestScrapeContent:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/scrape" in str(request.url):
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "markdown": "# Test Article\n\nThis is content with multiple words here.",
                        "metadata": {
                            "title": "Test Article",
                            "description": "A test article about SEO",
                        },
                    },
                })
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com/article")
        assert result is not None
        assert result.url == "https://example.com/article"
        assert "Test Article" in result.markdown
        assert result.meta_title == "Test Article"
        assert result.word_count > 0
        assert len(result.headings) == 1
        assert result.headings[0]["text"] == "Test Article"

    async def test_sends_correct_headers_and_body(self) -> None:
        captured_request: httpx.Request | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            if "/scrape" in str(request.url):
                captured_request = request
                return httpx.Response(200, json={
                    "success": True,
                    "data": {"markdown": "content", "metadata": {}},
                })
            return httpx.Response(404)

        client = _make_client(handler)
        await client.scrape_content("https://example.com")

        assert captured_request is not None
        assert captured_request.headers["Authorization"] == f"Bearer {API_KEY}"
        assert captured_request.headers["Content-Type"] == "application/json"

    async def test_timeout_returns_none_e31(self) -> None:
        """E31: Firecrawl /scrape timeout -> return None."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timed out")

        client = _make_client(handler)
        result = await client.scrape_content("https://slow-site.com")
        assert result is None

    async def test_api_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": False,
                "error": "RATE_LIMIT_EXCEEDED",
            })

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com")
        assert result is None

    async def test_http_500_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com")
        assert result is None

    async def test_network_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Connection refused")

        client = _make_client(handler)
        result = await client.scrape_content("https://unreachable.com")
        assert result is None

    async def test_empty_markdown(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": True,
                "data": {"markdown": "", "metadata": {}},
            })

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com")
        assert result is not None
        assert result.markdown == ""
        assert result.word_count == 0


# ---------------------------------------------------------------------------
# map_site
# ---------------------------------------------------------------------------


class TestMapSite:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/map" in str(request.url):
                return httpx.Response(200, json={
                    "success": True,
                    "links": [
                        "https://example.com/page1",
                        "https://example.com/page2",
                        "https://example.com/page3",
                    ],
                })
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.map_site("https://example.com")
        assert result is not None
        assert result.total_found == 3
        assert len(result.urls) == 3
        assert result.urls[0]["url"] == "https://example.com/page1"

    async def test_api_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": False,
                "error": "Invalid URL",
            })

        client = _make_client(handler)
        result = await client.map_site("https://bad.com")
        assert result is None

    async def test_network_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        result = await client.map_site("https://unreachable.com")
        assert result is None

    async def test_empty_links(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": True,
                "links": [],
            })

        client = _make_client(handler)
        result = await client.map_site("https://example.com")
        assert result is not None
        assert result.total_found == 0


# ---------------------------------------------------------------------------
# scrape_branding
# ---------------------------------------------------------------------------


class TestScrapeBranding:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/scrape" in str(request.url):
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "markdown": "<html>...</html>",
                        "metadata": {
                            "ogImage": "https://example.com/og-image.png",
                            "favicon": "https://example.com/favicon.ico",
                        },
                    },
                })
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is not None
        assert result.logo_url == "https://example.com/og-image.png"
        assert "background" in result.colors
        assert "heading" in result.fonts

    async def test_fallback_to_favicon(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": True,
                "data": {
                    "markdown": "content",
                    "metadata": {
                        "favicon": "https://example.com/favicon.ico",
                    },
                },
            })

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is not None
        assert result.logo_url == "https://example.com/favicon.ico"

    async def test_error_returns_none_e15(self) -> None:
        """E15: Firecrawl unavailable -> return None."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is None

    async def test_api_failure_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "success": False,
                "error": "Blocked",
            })

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is None
