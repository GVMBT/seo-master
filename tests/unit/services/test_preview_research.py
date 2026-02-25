"""Tests for research integration in services/preview.py.

Covers: _fetch_research cache hit/miss, graceful degradation (E53),
warmup_research_schema, _gather_websearch_data research parallel execution.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cache.keys import RESEARCH_CACHE_TTL, CacheKeys
from services.ai.articles import RESEARCH_SCHEMA
from services.ai.orchestrator import GenerationResult
from services.preview import PreviewService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SAMPLE_RESEARCH = {
    "facts": [{"claim": "Test fact", "source": "Source", "year": "2025"}],
    "trends": [{"trend": "AI trend", "relevance": "high"}],
    "statistics": [{"metric": "CTR", "value": "3%", "source": "Moz"}],
    "summary": "Test summary",
}


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    orch = AsyncMock()
    orch.generate_without_rate_limit.return_value = GenerationResult(
        content=_SAMPLE_RESEARCH,
        model_used="perplexity/sonar-pro",
        prompt_version="v1",
        fallback_used=False,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        generation_time_ms=500,
    )
    return orch


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get.return_value = None
    redis.set.return_value = True
    return redis


@pytest.fixture
def preview_service(mock_orchestrator: AsyncMock, mock_redis: AsyncMock) -> PreviewService:
    return PreviewService(
        ai_orchestrator=mock_orchestrator,
        db=MagicMock(),
        image_storage=MagicMock(),
        http_client=MagicMock(),
        redis=mock_redis,
    )


@pytest.fixture
def preview_service_no_redis(mock_orchestrator: AsyncMock) -> PreviewService:
    return PreviewService(
        ai_orchestrator=mock_orchestrator,
        db=MagicMock(),
        image_storage=MagicMock(),
        http_client=MagicMock(),
        redis=None,
    )


# ---------------------------------------------------------------------------
# _fetch_research — cache miss (API call)
# ---------------------------------------------------------------------------


class TestFetchResearchCacheMiss:
    async def test_fetches_from_api_on_cache_miss(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """On cache miss, calls generate_without_rate_limit and returns result."""
        result = await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result == _SAMPLE_RESEARCH
        mock_orchestrator.generate_without_rate_limit.assert_awaited_once()
        request = mock_orchestrator.generate_without_rate_limit.call_args[0][0]
        assert request.task == "article_research"
        assert request.response_schema == RESEARCH_SCHEMA

    async def test_caches_result_in_redis(
        self,
        preview_service: PreviewService,
        mock_redis: AsyncMock,
    ) -> None:
        """After API call, result is cached in Redis with correct TTL."""
        await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        mock_redis.set.assert_awaited_once()
        call_args = mock_redis.set.call_args
        # Cache key uses md5 hash
        assert call_args[0][0].startswith("research:")
        # Value is JSON
        cached_value = json.loads(call_args[0][1])
        assert cached_value == _SAMPLE_RESEARCH
        # TTL = 7 days
        assert call_args[1]["ex"] == RESEARCH_CACHE_TTL


# ---------------------------------------------------------------------------
# _fetch_research — cache hit
# ---------------------------------------------------------------------------


class TestFetchResearchCacheHit:
    async def test_returns_cached_data_without_api_call(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """On cache hit, returns cached data and does NOT call API."""
        mock_redis.get.return_value = json.dumps(_SAMPLE_RESEARCH)

        result = await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result == _SAMPLE_RESEARCH
        mock_orchestrator.generate_without_rate_limit.assert_not_awaited()


# ---------------------------------------------------------------------------
# _fetch_research — graceful degradation (E53)
# ---------------------------------------------------------------------------


class TestFetchResearchGracefulDegradation:
    async def test_api_error_returns_none(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """When Sonar Pro API fails, returns None (E53: graceful degradation)."""
        mock_orchestrator.generate_without_rate_limit.side_effect = Exception("Sonar Pro unavailable")

        result = await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result is None

    async def test_non_dict_response_returns_none(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """When API returns non-dict content, returns None."""
        mock_orchestrator.generate_without_rate_limit.return_value = GenerationResult(
            content="not a dict",
            model_used="perplexity/sonar-pro",
            prompt_version="v1",
            fallback_used=False,
            input_tokens=100,
            output_tokens=200,
            cost_usd=0.01,
            generation_time_ms=500,
        )

        result = await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result is None

    async def test_redis_read_error_falls_through_to_api(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Redis read error is swallowed, falls through to API call."""
        mock_redis.get.side_effect = Exception("Redis connection lost")

        result = await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result == _SAMPLE_RESEARCH
        mock_orchestrator.generate_without_rate_limit.assert_awaited_once()

    async def test_redis_write_error_does_not_fail(
        self,
        preview_service: PreviewService,
        mock_redis: AsyncMock,
    ) -> None:
        """Redis write error is swallowed, result is still returned."""
        mock_redis.set.side_effect = Exception("Redis connection lost")

        result = await preview_service._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result == _SAMPLE_RESEARCH


# ---------------------------------------------------------------------------
# _fetch_research — no Redis
# ---------------------------------------------------------------------------


class TestFetchResearchNoRedis:
    async def test_works_without_redis(
        self,
        preview_service_no_redis: PreviewService,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """When redis=None, skips cache and calls API directly."""
        result = await preview_service_no_redis._fetch_research(
            main_phrase="SEO optimization",
            specialization="digital marketing",
            company_name="TestCo",
        )

        assert result == _SAMPLE_RESEARCH
        mock_orchestrator.generate_without_rate_limit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _fetch_research — cache key determinism
# ---------------------------------------------------------------------------


class TestFetchResearchCacheKey:
    async def test_same_keyword_and_spec_same_cache_key(
        self,
        preview_service: PreviewService,
        mock_redis: AsyncMock,
    ) -> None:
        """Same main_phrase + specialization produces same cache key."""
        await preview_service._fetch_research("SEO", "marketing", "Co")
        first_key = mock_redis.get.call_args[0][0]

        mock_redis.reset_mock()
        await preview_service._fetch_research("SEO", "marketing", "Different")
        second_key = mock_redis.get.call_args[0][0]

        assert first_key == second_key  # same keyword+spec = same cache key

    async def test_different_keyword_different_cache_key(
        self,
        preview_service: PreviewService,
        mock_redis: AsyncMock,
    ) -> None:
        """Different main_phrase produces different cache key."""
        await preview_service._fetch_research("SEO", "marketing", "Co")
        first_key = mock_redis.get.call_args[0][0]

        mock_redis.reset_mock()
        await preview_service._fetch_research("PPC", "marketing", "Co")
        second_key = mock_redis.get.call_args[0][0]

        assert first_key != second_key

    async def test_different_specialization_different_cache_key(
        self,
        preview_service: PreviewService,
        mock_redis: AsyncMock,
    ) -> None:
        """Different specialization for same keyword produces different cache key."""
        await preview_service._fetch_research("SEO", "marketing", "Co")
        first_key = mock_redis.get.call_args[0][0]

        mock_redis.reset_mock()
        await preview_service._fetch_research("SEO", "medicine", "Co")
        second_key = mock_redis.get.call_args[0][0]

        assert first_key != second_key


# ---------------------------------------------------------------------------
# warmup_research_schema — smoke test
# ---------------------------------------------------------------------------


class TestWarmupResearchSchema:
    async def test_warmup_calls_api(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """warmup_research_schema sends a minimal request to Sonar Pro."""
        await preview_service.warmup_research_schema()

        mock_orchestrator.generate_without_rate_limit.assert_awaited_once()
        request = mock_orchestrator.generate_without_rate_limit.call_args[0][0]
        assert request.task == "article_research"
        assert request.response_schema == RESEARCH_SCHEMA

    async def test_warmup_error_does_not_raise(
        self,
        preview_service: PreviewService,
        mock_orchestrator: AsyncMock,
    ) -> None:
        """warmup_research_schema swallows errors (non-critical)."""
        mock_orchestrator.generate_without_rate_limit.side_effect = Exception("API down")

        # Should not raise
        await preview_service.warmup_research_schema()
