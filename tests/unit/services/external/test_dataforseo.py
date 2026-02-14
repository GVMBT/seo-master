"""Tests for services/external/dataforseo.py -- DataForSEO v3 client (stub).

All methods are stubs returning empty results.
Tests verify the stub contract: correct logging and empty returns.
"""

from __future__ import annotations

import httpx
import pytest

from services.external.dataforseo import (
    DataForSEOClient,
    KeywordData,
    KeywordSuggestion,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

LOGIN = "test@example.com"
FAKE_SECRET = "fake-pwd-for-test"  # noqa: S105


def _make_client() -> DataForSEOClient:
    """Create a DataForSEOClient with a mock transport (not used by stubs)."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return DataForSEOClient(login=LOGIN, password=FAKE_SECRET, http_client=http)


# ---------------------------------------------------------------------------
# Dataclass tests
# ---------------------------------------------------------------------------


class TestDataclasses:
    def test_keyword_suggestion_creation(self) -> None:
        ks = KeywordSuggestion(
            phrase="seo optimization",
            volume=1200,
            cpc=1.5,
            competition=0.45,
        )
        assert ks.phrase == "seo optimization"
        assert ks.volume == 1200
        assert ks.cpc == 1.5
        assert ks.competition == 0.45

    def test_keyword_data_creation(self) -> None:
        kd = KeywordData(
            phrase="seo audit",
            volume=800,
            difficulty=45,
            cpc=2.3,
            intent="informational",
        )
        assert kd.phrase == "seo audit"
        assert kd.difficulty == 45
        assert kd.intent == "informational"

    def test_keyword_suggestion_frozen(self) -> None:
        ks = KeywordSuggestion(phrase="test", volume=100, cpc=0.5, competition=0.1)
        with pytest.raises(AttributeError):
            ks.phrase = "changed"  # type: ignore[misc]

    def test_keyword_data_frozen(self) -> None:
        kd = KeywordData(phrase="test", volume=100, difficulty=50, cpc=1.0, intent="commercial")
        with pytest.raises(AttributeError):
            kd.phrase = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# keyword_suggestions (stub)
# ---------------------------------------------------------------------------


class TestKeywordSuggestions:
    async def test_returns_empty_list(self) -> None:
        client = _make_client()
        result = await client.keyword_suggestions("seo")
        assert result == []
        assert isinstance(result, list)

    async def test_with_custom_location(self) -> None:
        client = _make_client()
        result = await client.keyword_suggestions("seo", location_code=2840)  # US
        assert result == []

    async def test_with_custom_limit(self) -> None:
        client = _make_client()
        result = await client.keyword_suggestions("seo", limit=50)
        assert result == []

    async def test_with_all_params(self) -> None:
        client = _make_client()
        result = await client.keyword_suggestions(
            seed="seo optimization",
            location_code=2643,
            language_code="ru",
            limit=200,
        )
        assert result == []


# ---------------------------------------------------------------------------
# related_keywords (stub)
# ---------------------------------------------------------------------------


class TestRelatedKeywords:
    async def test_returns_empty_list(self) -> None:
        client = _make_client()
        result = await client.related_keywords("seo tools")
        assert result == []
        assert isinstance(result, list)

    async def test_with_custom_params(self) -> None:
        client = _make_client()
        result = await client.related_keywords(
            seed="keyword research",
            location_code=2840,
            language_code="en",
            limit=50,
        )
        assert result == []


# ---------------------------------------------------------------------------
# enrich_keywords (stub)
# ---------------------------------------------------------------------------


class TestEnrichKeywords:
    async def test_returns_empty_list(self) -> None:
        client = _make_client()
        result = await client.enrich_keywords(["seo", "seo tools", "seo audit"])
        assert result == []
        assert isinstance(result, list)

    async def test_empty_phrases(self) -> None:
        client = _make_client()
        result = await client.enrich_keywords([])
        assert result == []

    async def test_large_batch(self) -> None:
        """Stubs handle any batch size."""
        client = _make_client()
        phrases = [f"keyword_{i}" for i in range(700)]
        result = await client.enrich_keywords(phrases)
        assert result == []


# ---------------------------------------------------------------------------
# Client initialization
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_stores_credentials(self) -> None:
        client = _make_client()
        assert client._login == LOGIN
        assert client._password == FAKE_SECRET
        assert client._base == "https://api.dataforseo.com/v3"
