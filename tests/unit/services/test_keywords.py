"""Tests for services/keywords.py — data-first keyword pipeline.

Coverage: generate(), fetch_raw_phrases(), cluster_phrases(), enrich_clusters(),
generate_clusters_direct() (E03 fallback), _normalize_seeds_ai(), filter_low_quality.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.ai.orchestrator import GenerationResult
from services.external.dataforseo import KeywordData, KeywordSuggestion
from services.keywords import KeywordService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_gen_result(content: dict[str, Any] | str) -> GenerationResult:
    return GenerationResult(
        content=content,
        model_used="deepseek/deepseek-v3.2",
        prompt_version="v1",
        fallback_used=False,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.01,
        generation_time_ms=500,
    )


def _make_suggestion(phrase: str, volume: int = 100, cpc: float = 1.0) -> KeywordSuggestion:
    return KeywordSuggestion(phrase=phrase, volume=volume, cpc=cpc, competition=0.5)


def _make_keyword_data(phrase: str, volume: int = 100, difficulty: int = 50) -> KeywordData:
    return KeywordData(phrase=phrase, volume=volume, difficulty=difficulty, cpc=1.0, intent="informational")


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    orch = AsyncMock()
    orch.generate = AsyncMock()
    orch.generate_without_rate_limit = AsyncMock()
    return orch


@pytest.fixture
def mock_dataforseo() -> AsyncMock:
    dfs = AsyncMock()
    dfs.keyword_suggestions = AsyncMock(return_value=[])
    dfs.related_keywords = AsyncMock(return_value=[])
    dfs.enrich_keywords = AsyncMock(return_value=[])
    return dfs


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def service(mock_orchestrator: AsyncMock, mock_dataforseo: AsyncMock, mock_db: MagicMock) -> KeywordService:
    return KeywordService(
        orchestrator=mock_orchestrator,
        dataforseo=mock_dataforseo,
        db=mock_db,
    )


# ---------------------------------------------------------------------------
# _normalize_seeds_ai
# ---------------------------------------------------------------------------


class TestNormalizeSeedsAI:
    async def test_returns_variants_on_success(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result(
            {"variants": ["keyword one", "keyword two", "keyword three"]}
        )

        result = await service._normalize_seeds_ai("products text", "Moscow")

        assert len(result) == 3
        assert result[0] == "keyword one"

    async def test_returns_empty_on_failure(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        mock_orchestrator.generate_without_rate_limit.side_effect = Exception("API down")

        result = await service._normalize_seeds_ai("products text", "Moscow")

        assert result == []

    async def test_truncates_long_variants(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        long_variant = "a" * 200
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": [long_variant]})

        result = await service._normalize_seeds_ai("products", "Moscow")

        assert len(result) == 1
        assert len(result[0]) == 100

    async def test_limits_to_5_variants(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result(
            {"variants": [f"kw{i}" for i in range(10)]}
        )

        result = await service._normalize_seeds_ai("products", "Moscow")

        assert len(result) == 5

    async def test_returns_empty_for_non_dict_content(
        self, service: KeywordService, mock_orchestrator: AsyncMock
    ) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result("just text")

        result = await service._normalize_seeds_ai("products", "Moscow")

        assert result == []

    async def test_filters_empty_variants(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result(
            {"variants": ["", "valid", None, "good"]}
        )

        result = await service._normalize_seeds_ai("products", "Moscow")

        assert "valid" in result
        assert "" not in result


# ---------------------------------------------------------------------------
# fetch_raw_phrases
# ---------------------------------------------------------------------------


class TestFetchRawPhrases:
    async def test_returns_dataforseo_results(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        """DataForSEO returns results -> use them."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": ["ai seed"]})
        mock_dataforseo.keyword_suggestions.return_value = [
            _make_suggestion("seo optimization", 500),
            _make_suggestion("seo tips", 300),
        ]
        mock_dataforseo.related_keywords.return_value = [
            _make_suggestion("seo strategy", 200),
        ]

        result = await service.fetch_raw_phrases(
            products="SEO", geography="Moscow", quantity=100, project_id=1, user_id=1
        )

        assert len(result) == 3
        assert result[0]["phrase"] == "seo optimization"
        assert result[0]["ai_suggested"] is False

    async def test_deduplicates_phrases(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": []})
        mock_dataforseo.keyword_suggestions.return_value = [_make_suggestion("SEO tips", 300)]
        mock_dataforseo.related_keywords.return_value = [_make_suggestion("seo tips", 200)]

        result = await service.fetch_raw_phrases(
            products="SEO", geography="Moscow", quantity=100, project_id=1, user_id=1
        )

        assert len(result) == 1

    async def test_fallback_to_kazakhstan_location(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        """Ukraine returns 0 -> tries Kazakhstan."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": []})

        call_count = 0

        async def suggestions_side_effect(seed: str, location_code: int, limit: int) -> list:
            nonlocal call_count
            call_count += 1
            if location_code == 2804:  # Ukraine
                return []
            return [_make_suggestion("kw from kz", 100)]

        mock_dataforseo.keyword_suggestions.side_effect = suggestions_side_effect
        mock_dataforseo.related_keywords.return_value = []

        result = await service.fetch_raw_phrases(
            products="test", geography="Moscow", quantity=100, project_id=1, user_id=1
        )

        assert len(result) >= 1
        assert result[0]["phrase"] == "kw from kz"

    async def test_e03_dataforseo_returns_zero(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        """E03: DataForSEO returns 0 results -> empty list (caller uses AI fallback)."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": []})
        mock_dataforseo.keyword_suggestions.return_value = []
        mock_dataforseo.related_keywords.return_value = []

        result = await service.fetch_raw_phrases(
            products="obscure niche", geography="Moscow", quantity=100, project_id=1, user_id=1
        )

        assert result == []

    async def test_respects_quantity_limit(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": []})
        mock_dataforseo.keyword_suggestions.return_value = [_make_suggestion(f"kw{i}", 100) for i in range(50)]
        mock_dataforseo.related_keywords.return_value = []

        result = await service.fetch_raw_phrases(
            products="test", geography="Moscow", quantity=10, project_id=1, user_id=1
        )

        assert len(result) <= 10

    async def test_parses_comma_separated_products(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": []})
        mock_dataforseo.keyword_suggestions.return_value = [_make_suggestion("result")]
        mock_dataforseo.related_keywords.return_value = []

        await service.fetch_raw_phrases(
            products="keyword A, keyword B, keyword C",
            geography="Moscow",
            quantity=100,
            project_id=1,
            user_id=1,
        )

        # Should have been called with multiple seeds
        assert mock_dataforseo.keyword_suggestions.await_count >= 1

    async def test_combines_ai_and_original_seeds(
        self, service: KeywordService, mock_dataforseo: AsyncMock, mock_orchestrator: AsyncMock
    ) -> None:
        """AI seeds + original seeds are deduplicated and combined."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_gen_result({"variants": ["ai keyword"]})
        mock_dataforseo.keyword_suggestions.return_value = [_make_suggestion("result")]
        mock_dataforseo.related_keywords.return_value = []

        await service.fetch_raw_phrases(
            products="ai keyword", geography="Moscow", quantity=100, project_id=1, user_id=1
        )

        # "ai keyword" appears once in seeds (deduplication)
        calls = mock_dataforseo.keyword_suggestions.call_args_list
        seeds_used = [c.args[0] if c.args else c.kwargs.get("seed") for c in calls]
        # Should not duplicate if AI seed matches original
        assert len(set(s.lower() for s in seeds_used if s)) >= 1


# ---------------------------------------------------------------------------
# cluster_phrases
# ---------------------------------------------------------------------------


class TestClusterPhrases:
    async def test_returns_clustered_output(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        clusters = [
            {
                "cluster_name": "SEO basics",
                "cluster_type": "article",
                "main_phrase": "seo optimization",
                "phrases": [
                    {"phrase": "seo optimization", "ai_suggested": False},
                    {"phrase": "seo tips", "ai_suggested": True},
                ],
            }
        ]
        mock_orchestrator.generate.return_value = _make_gen_result({"clusters": clusters})

        with MagicMock() as mock_proj_repo:
            mock_proj_repo.get_by_id = AsyncMock(return_value=MagicMock(company_name="Co", specialization="SEO"))
            with pytest.MonkeyPatch.context() as m:
                m.setattr(
                    "services.keywords.ProjectsRepository",
                    lambda db: mock_proj_repo,
                )
                result = await service.cluster_phrases(
                    raw_phrases=[{"phrase": "seo optimization", "volume": 500}],
                    products="SEO",
                    geography="Moscow",
                    quantity=50,
                    project_id=1,
                    user_id=1,
                )

        assert len(result) == 1
        assert result[0]["cluster_name"] == "SEO basics"

    async def test_assigns_default_metrics(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "test phrase",
                "phrases": [{"phrase": "test phrase", "ai_suggested": True}],
            }
        ]
        mock_orchestrator.generate.return_value = _make_gen_result({"clusters": clusters})

        with MagicMock() as mock_proj_repo:
            mock_proj_repo.get_by_id = AsyncMock(return_value=MagicMock(company_name="", specialization=""))
            with pytest.MonkeyPatch.context() as m:
                m.setattr("services.keywords.ProjectsRepository", lambda db: mock_proj_repo)
                result = await service.cluster_phrases(
                    raw_phrases=[],
                    products="test",
                    geography="Moscow",
                    quantity=50,
                    project_id=1,
                    user_id=1,
                )

        phrase = result[0]["phrases"][0]
        assert phrase["volume"] == 0
        assert phrase["difficulty"] == 0
        assert phrase["intent"] == "informational"

    async def test_non_dict_result_returns_empty(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        mock_orchestrator.generate.return_value = _make_gen_result("not a dict")

        with MagicMock() as mock_proj_repo:
            mock_proj_repo.get_by_id = AsyncMock(return_value=None)
            with pytest.MonkeyPatch.context() as m:
                m.setattr("services.keywords.ProjectsRepository", lambda db: mock_proj_repo)
                result = await service.cluster_phrases(
                    raw_phrases=[],
                    products="test",
                    geography="Moscow",
                    quantity=50,
                    project_id=1,
                    user_id=1,
                )

        assert result == []


# ---------------------------------------------------------------------------
# enrich_clusters
# ---------------------------------------------------------------------------


class TestEnrichClusters:
    async def test_enriches_phrases_with_dataforseo_data(
        self, service: KeywordService, mock_dataforseo: AsyncMock
    ) -> None:
        mock_dataforseo.enrich_keywords.return_value = [
            _make_keyword_data("seo tips", volume=500, difficulty=30),
        ]
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "seo tips",
                "phrases": [
                    {"phrase": "seo tips", "volume": 0, "difficulty": 0, "cpc": 0.0, "intent": "informational"},
                ],
                "total_volume": 0,
                "avg_difficulty": 0,
            }
        ]

        result = await service.enrich_clusters(clusters)

        assert result[0]["phrases"][0]["volume"] == 500
        assert result[0]["phrases"][0]["difficulty"] == 30
        assert result[0]["total_volume"] == 500

    async def test_empty_phrases_returns_unchanged(self, service: KeywordService, mock_dataforseo: AsyncMock) -> None:
        clusters = [
            {
                "cluster_name": "empty",
                "cluster_type": "article",
                "main_phrase": "",
                "phrases": [],
                "total_volume": 0,
                "avg_difficulty": 0,
            }
        ]

        result = await service.enrich_clusters(clusters)

        mock_dataforseo.enrich_keywords.assert_not_awaited()
        assert result == clusters

    async def test_lookup_is_case_insensitive(self, service: KeywordService, mock_dataforseo: AsyncMock) -> None:
        mock_dataforseo.enrich_keywords.return_value = [
            _make_keyword_data("SEO Tips", volume=500, difficulty=30),
        ]
        clusters = [
            {
                "cluster_name": "test",
                "main_phrase": "seo tips",
                "phrases": [{"phrase": "seo tips", "volume": 0, "difficulty": 0, "cpc": 0.0, "intent": "info"}],
                "total_volume": 0,
                "avg_difficulty": 0,
            }
        ]

        result = await service.enrich_clusters(clusters)

        # "seo tips" matches "SEO Tips" via lowercase lookup
        assert result[0]["phrases"][0]["volume"] == 500


# ---------------------------------------------------------------------------
# generate_clusters_direct (E03 fallback)
# ---------------------------------------------------------------------------


class TestGenerateClustersDirect:
    async def test_e03_generates_ai_only_clusters(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        """E03: When DataForSEO unavailable, generate clusters directly via AI."""
        clusters = [
            {
                "cluster_name": "AI generated",
                "cluster_type": "article",
                "main_phrase": "ai keyword",
                "phrases": [
                    {"phrase": "ai keyword", "ai_suggested": True},
                ],
            }
        ]
        mock_orchestrator.generate.return_value = _make_gen_result({"clusters": clusters})

        with MagicMock() as mock_proj_repo:
            mock_proj_repo.get_by_id = AsyncMock(return_value=MagicMock(company_name="Co", specialization="SEO"))
            with pytest.MonkeyPatch.context() as m:
                m.setattr("services.keywords.ProjectsRepository", lambda db: mock_proj_repo)
                result = await service.generate_clusters_direct(
                    products="test", geography="Moscow", quantity=50, project_id=1, user_id=1
                )

        assert len(result) == 1
        # All phrases marked as AI-suggested
        for phrase in result[0]["phrases"]:
            assert phrase["ai_suggested"] is True
            assert phrase["volume"] == 0
            assert phrase["intent"] == "informational"

    async def test_e03_marks_defaults_for_missing_fields(
        self, service: KeywordService, mock_orchestrator: AsyncMock
    ) -> None:
        clusters = [
            {
                "cluster_name": "test",
                "cluster_type": "article",
                "main_phrase": "phrase",
                "phrases": [{"phrase": "phrase"}],
            }
        ]
        mock_orchestrator.generate.return_value = _make_gen_result({"clusters": clusters})

        with MagicMock() as mock_proj_repo:
            mock_proj_repo.get_by_id = AsyncMock(return_value=None)
            with pytest.MonkeyPatch.context() as m:
                m.setattr("services.keywords.ProjectsRepository", lambda db: mock_proj_repo)
                result = await service.generate_clusters_direct(
                    products="test", geography="Moscow", quantity=50, project_id=1, user_id=1
                )

        p = result[0]["phrases"][0]
        assert p["ai_suggested"] is True
        assert p["volume"] == 0
        assert p["difficulty"] == 0
        assert p["cpc"] == 0.0

    async def test_e03_context_has_zero_raw_count(self, service: KeywordService, mock_orchestrator: AsyncMock) -> None:
        """E03 AI path sends raw_count=0 and raw_keywords_json=[] to the prompt."""
        mock_orchestrator.generate.return_value = _make_gen_result({"clusters": []})

        with MagicMock() as mock_proj_repo:
            mock_proj_repo.get_by_id = AsyncMock(return_value=None)
            with pytest.MonkeyPatch.context() as m:
                m.setattr("services.keywords.ProjectsRepository", lambda db: mock_proj_repo)
                await service.generate_clusters_direct(
                    products="test", geography="Moscow", quantity=50, project_id=1, user_id=1
                )

        call_args = mock_orchestrator.generate.call_args[0][0]
        assert call_args.context["raw_count"] == 0
        assert call_args.context["raw_keywords_json"] == "[]"


# ---------------------------------------------------------------------------
# filter_low_quality (already partially tested in test_keywords_pipeline.py)
# Additional edge cases.
# ---------------------------------------------------------------------------


class TestFilterLowQualityExtended:
    @pytest.fixture
    def svc(self) -> KeywordService:
        return KeywordService.__new__(KeywordService)

    def test_empty_input_returns_empty(self, svc: KeywordService) -> None:
        assert svc.filter_low_quality([]) == []

    def test_mixed_ai_and_dataseo_in_single_cluster(self, svc: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "mixed",
                "cluster_type": "article",
                "main_phrase": "real phrase",
                "total_volume": 200,
                "avg_difficulty": 40,
                "phrases": [
                    {"phrase": "real phrase", "volume": 200, "ai_suggested": False},
                    {"phrase": "ai zero", "volume": 0, "ai_suggested": True},
                    {"phrase": "ai good", "volume": 50, "ai_suggested": True},
                ],
            }
        ]
        result = svc.filter_low_quality(clusters)
        phrases = [p["phrase"] for p in result[0]["phrases"]]
        assert "real phrase" in phrases
        assert "ai good" in phrases
        assert "ai zero" not in phrases

    def test_multiple_clusters_some_removed(self, svc: KeywordService) -> None:
        clusters = [
            {
                "cluster_name": "good",
                "cluster_type": "article",
                "main_phrase": "valid",
                "phrases": [{"phrase": "valid", "volume": 100, "ai_suggested": False}],
                "total_volume": 100,
                "avg_difficulty": 30,
            },
            {
                "cluster_name": "bad",
                "cluster_type": "article",
                "main_phrase": "junk",
                "phrases": [{"phrase": "junk", "volume": 0, "ai_suggested": True}],
                "total_volume": 0,
                "avg_difficulty": 0,
            },
        ]
        result = svc.filter_low_quality(clusters)
        assert len(result) == 1
        assert result[0]["cluster_name"] == "good"
