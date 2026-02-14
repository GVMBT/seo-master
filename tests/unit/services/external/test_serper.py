"""Tests for services/external/serper.py -- Serper.dev API client.

Covers: search (success, cache hit/miss, retry, E04 graceful degradation),
PAA parsing (dict and string formats), related searches parsing,
Redis cache get/set errors.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import httpx

from services.external.serper import SerperClient, SerperResult, _cache_key, _empty_result

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

API_KEY = "serper-test-key"


def _make_client(
    handler: object,
    redis: Any = None,
) -> SerperClient:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.AsyncClient(transport=transport)
    return SerperClient(api_key=API_KEY, http_client=http, redis=redis)


def _make_redis_mock(cached_data: dict[str, str] | None = None) -> AsyncMock:
    """Create a mock Redis client with optional cached data."""
    redis = AsyncMock()
    if cached_data:
        async def get_side_effect(key: str) -> str | None:
            return cached_data.get(key)
        redis.get = AsyncMock(side_effect=get_side_effect)
    else:
        redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    return redis


# ---------------------------------------------------------------------------
# Dataclass / helper tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_empty_result(self) -> None:
        result = _empty_result()
        assert result.organic == []
        assert result.people_also_ask == []
        assert result.related_searches == []

    def test_cache_key_deterministic(self) -> None:
        key1 = _cache_key("test query")
        key2 = _cache_key("test query")
        assert key1 == key2
        assert key1.startswith("serper:")

    def test_cache_key_different_queries(self) -> None:
        key1 = _cache_key("query one")
        key2 = _cache_key("query two")
        assert key1 != key2

    def test_serper_result_creation(self) -> None:
        result = SerperResult(
            organic=[{"title": "Test", "link": "https://example.com"}],
            people_also_ask=[{"question": "What is SEO?"}],
            related_searches=["seo tips"],
        )
        assert len(result.organic) == 1
        assert len(result.people_also_ask) == 1


# ---------------------------------------------------------------------------
# search -- happy path
# ---------------------------------------------------------------------------


class TestSearchSuccess:
    async def test_basic_search(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "/search" in str(request.url):
                return httpx.Response(200, json={
                    "organic": [
                        {"title": "SEO Guide", "link": "https://example.com/seo", "snippet": "...", "position": 1},
                        {"title": "SEO Tips", "link": "https://example.com/tips", "snippet": "...", "position": 2},
                    ],
                    "peopleAlsoAsk": [
                        {"question": "What is SEO?", "snippet": "SEO stands for...", "link": "https://example.com"},
                    ],
                    "relatedSearches": [
                        {"query": "seo tools"},
                        {"query": "seo checklist"},
                    ],
                })
            return httpx.Response(404)

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("seo guide")

        assert len(result.organic) == 2
        assert result.organic[0]["title"] == "SEO Guide"
        assert len(result.people_also_ask) == 1
        assert result.people_also_ask[0]["question"] == "What is SEO?"
        assert len(result.related_searches) == 2
        assert "seo tools" in result.related_searches

    async def test_sends_correct_headers(self) -> None:
        captured_request: httpx.Request | None = None

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(200, json={
                "organic": [],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        await client.search("test")

        assert captured_request is not None
        assert captured_request.headers["X-API-KEY"] == API_KEY

    async def test_paa_string_format(self) -> None:
        """PAA can come as plain strings (legacy format)."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [],
                "peopleAlsoAsk": ["What is SEO?", "How to do SEO?"],
                "relatedSearches": [],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("seo")

        assert len(result.people_also_ask) == 2
        assert result.people_also_ask[0] == {"question": "What is SEO?"}

    async def test_related_searches_string_format(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [],
                "peopleAlsoAsk": [],
                "relatedSearches": ["seo tips", "seo tools"],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("seo")

        assert result.related_searches == ["seo tips", "seo tools"]


# ---------------------------------------------------------------------------
# search -- cache
# ---------------------------------------------------------------------------


class TestSearchCache:
    async def test_cache_hit(self) -> None:
        """Cached result should be returned without API call."""
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json={"organic": [], "peopleAlsoAsk": [], "relatedSearches": []})

        cached_data = {
            _cache_key("cached query"): json.dumps({
                "organic": [{"title": "Cached", "link": "https://cached.com"}],
                "people_also_ask": [],
                "related_searches": [],
            }),
        }
        redis = _make_redis_mock(cached_data=cached_data)
        client = _make_client(handler, redis=redis)
        result = await client.search("cached query")

        assert call_count == 0  # No API call made
        assert len(result.organic) == 1
        assert result.organic[0]["title"] == "Cached"

    async def test_cache_miss_triggers_api_call(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [{"title": "Fresh"}],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("fresh query")

        assert len(result.organic) == 1
        assert result.organic[0]["title"] == "Fresh"
        # Verify cache was set
        redis.set.assert_called_once()

    async def test_cache_set_on_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [{"title": "Result"}],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        await client.search("test query")

        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[1]["ex"] == 86400  # 24h TTL

    async def test_cache_not_set_on_empty_result(self) -> None:
        """Do not cache empty results."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        await client.search("empty query")

        redis.set.assert_not_called()

    async def test_cache_error_falls_through(self) -> None:
        """Redis errors should not break search."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [{"title": "Works"}],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        redis = AsyncMock()
        redis.get = AsyncMock(side_effect=Exception("Redis down"))
        redis.set = AsyncMock(side_effect=Exception("Redis down"))
        client = _make_client(handler, redis=redis)
        result = await client.search("test")

        assert len(result.organic) == 1

    async def test_no_redis(self) -> None:
        """Search should work without Redis."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "organic": [{"title": "No cache"}],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        client = _make_client(handler, redis=None)
        result = await client.search("query")

        assert len(result.organic) == 1


# ---------------------------------------------------------------------------
# search -- error handling (E04)
# ---------------------------------------------------------------------------


class TestSearchErrors:
    async def test_http_error_returns_empty_e04(self) -> None:
        """E04: Serper unavailable -> empty result."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, text="Rate limit exceeded")

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("test")

        assert result.organic == []
        assert result.people_also_ask == []
        assert result.related_searches == []

    async def test_network_error_returns_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Down")

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("test")

        assert result.organic == []

    async def test_timeout_returns_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Timed out")

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("test")

        assert result.organic == []

    async def test_retry_succeeds_on_second_attempt(self) -> None:
        """Retry logic: first attempt fails, second succeeds."""
        attempt = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                return httpx.Response(500, text="Server Error")
            return httpx.Response(200, json={
                "organic": [{"title": "Second try"}],
                "peopleAlsoAsk": [],
                "relatedSearches": [],
            })

        redis = _make_redis_mock()
        client = _make_client(handler, redis=redis)
        result = await client.search("retry test")

        assert len(result.organic) == 1
        assert result.organic[0]["title"] == "Second try"
