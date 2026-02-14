"""Tests for services/external/firecrawl.py -- Firecrawl API v2 client.

Covers: scrape_content (success, timeout E31, API error, non-success response),
map_site (success, error, empty), scrape_branding via /extract (success, error),
extract (success, timeout, error), extract_competitor, search,
helper functions (_count_words, _extract_headings).
"""

from __future__ import annotations

import json

import httpx

from services.external.firecrawl import (
    BrandingResult,
    ExtractResult,
    FirecrawlClient,
    MapResult,
    ScrapeResult,
    SearchResult,
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

    def test_extract_result_creation(self) -> None:
        result = ExtractResult(
            data={"title": "Test"},
            source_url="https://example.com",
        )
        assert result.data["title"] == "Test"
        assert result.source_url == "https://example.com"

    def test_search_result_creation(self) -> None:
        result = SearchResult(
            url="https://example.com",
            title="Example",
            description="An example page",
            markdown="# Example",
        )
        assert result.url == "https://example.com"
        assert result.markdown == "# Example"


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
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "markdown": "# Test Article\n\nThis is content with multiple words here.",
                            "metadata": {
                                "title": "Test Article",
                                "description": "A test article about SEO",
                            },
                        },
                    },
                )
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

    async def test_uses_v2_endpoint(self) -> None:
        """Verify requests go to /v2/scrape (not /v1)."""
        captured_url: str = ""

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"markdown": "content", "metadata": {}},
                },
            )

        client = _make_client(handler)
        await client.scrape_content("https://example.com")
        assert "/v2/scrape" in captured_url

    async def test_sends_correct_headers_and_body(self) -> None:
        captured_request: httpx.Request | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            if "/scrape" in str(request.url):
                captured_request = request
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"markdown": "content", "metadata": {}},
                    },
                )
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
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "error": "RATE_LIMIT_EXCEEDED",
                },
            )

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
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"markdown": "", "metadata": {}},
                },
            )

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com")
        assert result is not None
        assert result.markdown == ""
        assert result.word_count == 0

    async def test_summary_from_data_field(self) -> None:
        """When Firecrawl returns summary in data (not metadata), use it."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "markdown": "# Article\n\nSome content here.",
                        "summary": "AI-generated summary of the article",
                        "metadata": {
                            "title": "Article",
                            "description": "Meta description",
                        },
                    },
                },
            )

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com/article")
        assert result is not None
        assert result.summary == "AI-generated summary of the article"
        assert result.meta_description == "Meta description"

    async def test_summary_fallback_to_meta_description(self) -> None:
        """When no summary in data, fall back to metadata.description."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "markdown": "# Article\n\nContent.",
                        "metadata": {
                            "description": "Meta desc fallback",
                        },
                    },
                },
            )

        client = _make_client(handler)
        result = await client.scrape_content("https://example.com/article")
        assert result is not None
        assert result.summary == "Meta desc fallback"

    async def test_sends_summary_format(self) -> None:
        """Verify that scrape_content requests 'summary' format."""
        captured_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            if "/scrape" in str(request.url):
                captured_body = json.loads(request.content.decode())
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"markdown": "x", "metadata": {}},
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        await client.scrape_content("https://example.com")

        assert captured_body is not None
        assert "summary" in captured_body["formats"]
        assert "markdown" in captured_body["formats"]


# ---------------------------------------------------------------------------
# map_site
# ---------------------------------------------------------------------------


class TestMapSite:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/map" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "links": [
                            "https://example.com/page1",
                            "https://example.com/page2",
                            "https://example.com/page3",
                        ],
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.map_site("https://example.com")
        assert result is not None
        assert result.total_found == 3
        assert len(result.urls) == 3
        assert result.urls[0]["url"] == "https://example.com/page1"

    async def test_api_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "error": "Invalid URL",
                },
            )

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
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "links": [],
                },
            )

        client = _make_client(handler)
        result = await client.map_site("https://example.com")
        assert result is not None
        assert result.total_found == 0


# ---------------------------------------------------------------------------
# extract (generic)
# ---------------------------------------------------------------------------


class TestExtract:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/extract" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {"title": "Extracted Title", "price": 99.99},
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.extract(
            urls=["https://example.com"],
            prompt="Extract the title and price",
            schema={"type": "object", "properties": {"title": {"type": "string"}}},
        )
        assert result is not None
        assert result.data["title"] == "Extracted Title"
        assert result.source_url == "https://example.com"

    async def test_uses_v2_endpoint(self) -> None:
        captured_url: str = ""

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"result": "ok"},
                },
            )

        client = _make_client(handler)
        await client.extract(urls=["https://example.com"], prompt="test")
        assert "/v2/extract" in captured_url

    async def test_sends_schema_and_prompt(self) -> None:
        captured_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {},
                },
            )

        client = _make_client(handler)
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        await client.extract(
            urls=["https://example.com"],
            prompt="Extract name",
            schema=schema,
        )
        assert captured_body is not None
        assert captured_body["prompt"] == "Extract name"
        assert captured_body["schema"] == schema
        assert captured_body["urls"] == ["https://example.com"]

    async def test_without_schema(self) -> None:
        captured_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"answer": "42"},
                },
            )

        client = _make_client(handler)
        result = await client.extract(
            urls=["https://example.com"],
            prompt="What is the answer?",
        )
        assert result is not None
        assert captured_body is not None
        assert "schema" not in captured_body

    async def test_timeout_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timed out")

        client = _make_client(handler)
        result = await client.extract(urls=["https://slow.com"], prompt="test")
        assert result is None

    async def test_api_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "error": "Rate limit exceeded",
                },
            )

        client = _make_client(handler)
        result = await client.extract(urls=["https://example.com"], prompt="test")
        assert result is None

    async def test_http_error_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal error")

        client = _make_client(handler)
        result = await client.extract(urls=["https://example.com"], prompt="test")
        assert result is None


# ---------------------------------------------------------------------------
# scrape_branding (now via /extract with LLM)
# ---------------------------------------------------------------------------


class TestScrapeBranding:
    async def test_success_with_real_colors(self) -> None:
        """Branding now uses /extract to get real CSS colors via LLM."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "/extract" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "colors": {
                                "background": "#f5f5f5",
                                "text": "#1a1a1a",
                                "accent": "#e74c3c",
                                "primary": "#2c3e50",
                                "secondary": "#95a5a6",
                            },
                            "fonts": {
                                "heading": "Montserrat",
                                "body": "Open Sans",
                            },
                            "logo_url": "https://example.com/logo.svg",
                        },
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is not None
        assert result.colors["background"] == "#f5f5f5"
        assert result.colors["text"] == "#1a1a1a"
        assert result.colors["accent"] == "#e74c3c"
        assert result.colors["primary"] == "#2c3e50"
        assert result.fonts["heading"] == "Montserrat"
        assert result.fonts["body"] == "Open Sans"
        assert result.logo_url == "https://example.com/logo.svg"

    async def test_fallback_colors_on_partial_data(self) -> None:
        """Missing color fields get sensible defaults."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {
                        "colors": {"accent": "#ff0000"},
                        "fonts": {},
                    },
                },
            )

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is not None
        assert result.colors["background"] == "#ffffff"
        assert result.colors["text"] == "#333333"
        assert result.colors["accent"] == "#ff0000"
        assert result.colors["primary"] == "#ff0000"  # fallback to accent
        assert result.fonts["heading"] == "sans-serif"

    async def test_error_returns_none_e15(self) -> None:
        """E15: Firecrawl unavailable -> return None."""

        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is None

    async def test_api_failure_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "error": "Blocked",
                },
            )

        client = _make_client(handler)
        result = await client.scrape_branding("https://example.com")
        assert result is None


# ---------------------------------------------------------------------------
# extract_competitor (F39)
# ---------------------------------------------------------------------------


class TestExtractCompetitor:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/extract" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": {
                            "company_name": "Competitor Corp",
                            "main_topics": ["SEO", "Content Marketing", "PPC"],
                            "content_types": ["blog", "landing pages"],
                            "unique_selling_points": ["Free tools", "Large blog"],
                            "content_gaps": ["No video content", "Missing local SEO"],
                            "estimated_pages": 150,
                            "primary_keywords": ["seo tools", "keyword research"],
                        },
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        result = await client.extract_competitor("https://competitor.com")
        assert result is not None
        assert result.data["company_name"] == "Competitor Corp"
        assert "SEO" in result.data["main_topics"]
        assert len(result.data["content_gaps"]) == 2
        assert result.source_url == "https://competitor.com"

    async def test_sends_competitor_schema(self) -> None:
        captured_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"company_name": "Test", "main_topics": []},
                },
            )

        client = _make_client(handler)
        await client.extract_competitor("https://example.com")
        assert captured_body is not None
        assert "schema" in captured_body
        assert "company_name" in captured_body["schema"]["properties"]
        assert "content_gaps" in captured_body["schema"]["properties"]

    async def test_failure_returns_none(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timed out")

        client = _make_client(handler)
        result = await client.extract_competitor("https://slow-competitor.com")
        assert result is None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


class TestSearch:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/search" in str(request.url):
                return httpx.Response(
                    200,
                    json={
                        "success": True,
                        "data": [
                            {
                                "url": "https://result1.com",
                                "markdown": "# Result 1\n\nContent here.",
                                "metadata": {
                                    "title": "Result One",
                                    "description": "First result",
                                },
                            },
                            {
                                "url": "https://result2.com",
                                "markdown": "# Result 2",
                                "metadata": {
                                    "title": "Result Two",
                                    "description": "Second result",
                                },
                            },
                        ],
                    },
                )
            return httpx.Response(404)

        client = _make_client(handler)
        results = await client.search("SEO tips 2026", limit=5)
        assert len(results) == 2
        assert results[0].url == "https://result1.com"
        assert results[0].title == "Result One"
        assert results[0].markdown is not None
        assert "Result 1" in results[0].markdown

    async def test_uses_v2_endpoint(self) -> None:
        captured_url: str = ""

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_url
            captured_url = str(request.url)
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [],
                },
            )

        client = _make_client(handler)
        await client.search("test query")
        assert "/v2/search" in captured_url

    async def test_sends_correct_body(self) -> None:
        captured_body: dict | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_body
            captured_body = json.loads(request.content.decode())
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [],
                },
            )

        client = _make_client(handler)
        await client.search("SEO audit", limit=3)
        assert captured_body is not None
        assert captured_body["query"] == "SEO audit"
        assert captured_body["limit"] == 3
        assert "scrapeOptions" in captured_body

    async def test_api_error_returns_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": False,
                    "error": "Rate limit",
                },
            )

        client = _make_client(handler)
        results = await client.search("test")
        assert results == []

    async def test_network_error_returns_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Down")

        client = _make_client(handler)
        results = await client.search("test")
        assert results == []

    async def test_empty_results(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": [],
                },
            )

        client = _make_client(handler)
        results = await client.search("obscure query with no results")
        assert results == []
