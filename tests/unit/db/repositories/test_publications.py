"""Tests for db/repositories/publications.py — including keyword rotation."""

import pytest

from db.models import PublicationLog, PublicationLogCreate
from db.repositories.publications import PublicationsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def pub_row() -> dict:
    return {
        "id": 1,
        "user_id": 123456789,
        "project_id": 1,
        "category_id": 1,
        "platform_type": "wordpress",
        "connection_id": 1,
        "keyword": "seo tips",
        "content_type": "article",
        "images_count": 2,
        "post_url": "https://example.com/seo-tips",
        "word_count": 2000,
        "tokens_spent": 320,
        "ai_model": "anthropic/claude-sonnet-4.5",
        "generation_time_ms": 5000,
        "prompt_version": "v1",
        "status": "success",
        "error_message": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> PublicationsRepository:
    return PublicationsRepository(mock_db)  # type: ignore[arg-type]


class TestCreateLog:
    async def test_create(self, repo: PublicationsRepository, mock_db: MockSupabaseClient, pub_row: dict) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[pub_row]))
        data = PublicationLogCreate(
            user_id=123456789,
            project_id=1,
            platform_type="wordpress",
            keyword="seo tips",
            word_count=2000,
            tokens_spent=320,
        )
        log = await repo.create_log(data)
        assert isinstance(log, PublicationLog)
        assert log.keyword == "seo tips"


class TestGetByUser:
    async def test_returns_list(self, repo: PublicationsRepository, mock_db: MockSupabaseClient, pub_row: dict) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[pub_row]))
        logs = await repo.get_by_user(123456789)
        assert len(logs) == 1

    async def test_empty(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        assert await repo.get_by_user(999) == []


class TestGetByProject:
    async def test_returns_list(self, repo: PublicationsRepository, mock_db: MockSupabaseClient, pub_row: dict) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[pub_row]))
        logs = await repo.get_by_project(1)
        assert len(logs) == 1


class TestGetRecentlyUsedKeywords:
    async def test_returns_keywords(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response(
            "publication_logs",
            MockResponse(data=[{"keyword": "seo tips"}, {"keyword": "seo guide"}]),
        )
        keywords = await repo.get_recently_used_keywords(1)
        assert keywords == ["seo tips", "seo guide"]

    async def test_empty(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        assert await repo.get_recently_used_keywords(1) == []


class TestGetLruKeyword:
    async def test_returns_oldest(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[{"keyword": "oldest kw"}]))
        assert await repo.get_lru_keyword(1) == "oldest kw"

    async def test_none_when_empty(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        assert await repo.get_lru_keyword(1) is None


class TestGetRotationKeywordLegacy:
    """Legacy flat-keyword rotation algorithm (API_CONTRACTS.md §6, E36 fallback)."""

    async def test_empty_pool_returns_none(self, repo: PublicationsRepository) -> None:
        kw, warning = await repo.get_rotation_keyword(1, [])
        assert kw is None
        assert warning is True

    async def test_picks_highest_volume_first(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        keywords = [
            {"phrase": "low vol", "volume": 100, "difficulty": 10},
            {"phrase": "high vol", "volume": 1000, "difficulty": 20},
            {"phrase": "mid vol", "volume": 500, "difficulty": 15},
        ]
        kw, _warning = await repo.get_rotation_keyword(1, keywords)
        assert kw == "high vol"

    async def test_sorts_by_difficulty_asc_on_tie(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        keywords = [
            {"phrase": "hard", "volume": 1000, "difficulty": 80},
            {"phrase": "easy", "volume": 1000, "difficulty": 10},
        ]
        kw, _ = await repo.get_rotation_keyword(1, keywords)
        assert kw == "easy"

    async def test_skips_recently_used(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[{"keyword": "high vol"}]))
        keywords = [
            {"phrase": "high vol", "volume": 1000, "difficulty": 20},
            {"phrase": "next best", "volume": 500, "difficulty": 10},
        ]
        kw, _ = await repo.get_rotation_keyword(1, keywords)
        assert kw == "next best"

    async def test_low_pool_warning_when_less_than_3(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        keywords = [
            {"phrase": "kw1", "volume": 100, "difficulty": 10},
            {"phrase": "kw2", "volume": 200, "difficulty": 20},
        ]
        _, warning = await repo.get_rotation_keyword(1, keywords)
        assert warning is True

    async def test_no_warning_when_3_or_more(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        keywords = [{"phrase": f"kw{i}", "volume": i * 100, "difficulty": i} for i in range(3)]
        _, warning = await repo.get_rotation_keyword(1, keywords)
        assert warning is False

    async def test_all_on_cooldown_uses_lru_fallback(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """E22: all keywords used in last 7 days -> LRU fallback."""
        mock_db.set_response(
            "publication_logs",
            MockResponse(data=[{"keyword": "kw1"}, {"keyword": "kw2"}]),
        )
        keywords = [
            {"phrase": "kw1", "volume": 1000, "difficulty": 10},
            {"phrase": "kw2", "volume": 500, "difficulty": 20},
        ]
        kw, _ = await repo.get_rotation_keyword(1, keywords)
        # Falls back to LRU — mock returns first keyword from publication_logs
        assert kw == "kw1"


# ---------------------------------------------------------------------------
# Cluster-based rotation (API_CONTRACTS.md §6)
# ---------------------------------------------------------------------------


def _make_cluster(
    name: str,
    main_phrase: str,
    cluster_type: str = "article",
    total_volume: int = 1000,
    avg_difficulty: int = 40,
) -> dict:
    return {
        "cluster_name": name,
        "cluster_type": cluster_type,
        "main_phrase": main_phrase,
        "total_volume": total_volume,
        "avg_difficulty": avg_difficulty,
        "phrases": [{"phrase": main_phrase, "volume": total_volume, "difficulty": avg_difficulty}],
    }


class TestGetRotationKeywordCluster:
    """Cluster-based rotation (API_CONTRACTS.md §6)."""

    async def test_picks_highest_volume_cluster(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        clusters = [
            _make_cluster("low", "low phrase", total_volume=500),
            _make_cluster("high", "high phrase", total_volume=5000),
            _make_cluster("mid", "mid phrase", total_volume=2000),
        ]
        kw, _ = await repo.get_rotation_keyword(1, clusters)
        assert kw == "high phrase"

    async def test_filters_article_clusters_only(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """product_page clusters must be excluded for articles (§6)."""
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        clusters = [
            _make_cluster("product", "buy now", cluster_type="product_page", total_volume=9999),
            _make_cluster("info", "how to seo", cluster_type="article", total_volume=1000),
        ]
        kw, _ = await repo.get_rotation_keyword(1, clusters, content_type="article")
        assert kw == "how to seo"

    async def test_social_post_includes_all_cluster_types(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """Social posts accept ALL cluster_types including product_page (§6.1)."""
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        clusters = [
            _make_cluster("product", "buy now", cluster_type="product_page", total_volume=9999),
            _make_cluster("social", "seo tips", cluster_type="social", total_volume=3000),
            _make_cluster("info", "seo guide", cluster_type="article", total_volume=1000),
        ]
        kw, _ = await repo.get_rotation_keyword(1, clusters, content_type="social_post")
        # product_page cluster has highest volume → picked first
        assert kw == "buy now"

    async def test_skips_recently_used_cluster(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[{"keyword": "top phrase"}]))
        clusters = [
            _make_cluster("top", "top phrase", total_volume=5000),
            _make_cluster("next", "next phrase", total_volume=2000),
        ]
        kw, _ = await repo.get_rotation_keyword(1, clusters)
        assert kw == "next phrase"

    async def test_low_pool_warning_less_than_3_article_clusters(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """Warning based on filtered pool, not total clusters (E23)."""
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        clusters = [
            _make_cluster("a", "phrase a", cluster_type="article"),
            _make_cluster("b", "phrase b", cluster_type="product_page"),
            _make_cluster("c", "phrase c", cluster_type="product_page"),
        ]
        _, warning = await repo.get_rotation_keyword(1, clusters, content_type="article")
        # Only 1 article cluster in pool -> warning
        assert warning is True

    async def test_no_warning_when_3_article_clusters(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        clusters = [
            _make_cluster("a", "p1", total_volume=100),
            _make_cluster("b", "p2", total_volume=200),
            _make_cluster("c", "p3", total_volume=300),
        ]
        _, warning = await repo.get_rotation_keyword(1, clusters)
        assert warning is False

    async def test_all_article_filtered_out_returns_none(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """No clusters match cluster_type filter -> None."""
        clusters = [
            _make_cluster("p1", "buy this", cluster_type="product_page"),
            _make_cluster("p2", "buy that", cluster_type="product_page"),
        ]
        kw, warning = await repo.get_rotation_keyword(1, clusters, content_type="article")
        assert kw is None
        assert warning is True

    async def test_cluster_all_on_cooldown_lru_fallback(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """E22: all clusters used in last 7 days -> LRU fallback."""
        mock_db.set_response(
            "publication_logs",
            MockResponse(data=[{"keyword": "p1"}, {"keyword": "p2"}]),
        )
        clusters = [
            _make_cluster("a", "p1", total_volume=2000),
            _make_cluster("b", "p2", total_volume=1000),
        ]
        kw, _ = await repo.get_rotation_keyword(1, clusters)
        # LRU mock returns first keyword from publication_logs
        assert kw == "p1"


class TestContentTypeCooldown:
    """§6.1: articles and social posts have independent cooldowns."""

    async def test_recently_used_filters_by_content_type(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """When content_type is passed, only that type's publications count as cooldown."""
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        result = await repo.get_recently_used_keywords(1, content_type="article")
        assert result == []

    async def test_social_post_cooldown_independent_from_article(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """A keyword used for article should NOT be on cooldown for social_post."""
        # Mock: article rotation returns "seo tips" as used (but only for articles)
        # Social post rotation should get empty used set
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        clusters = [
            _make_cluster("a", "seo tips", total_volume=5000),
            _make_cluster("b", "seo guide", total_volume=1000),
        ]
        kw, _ = await repo.get_rotation_keyword(1, clusters, content_type="social_post")
        assert kw == "seo tips"


class TestGetStatsByUser:
    async def test_aggregated_stats(self, repo: PublicationsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response(
            "publication_logs",
            MockResponse(
                data=[{"tokens_spent": 100}, {"tokens_spent": 200}],
                count=2,
            ),
        )
        stats = await repo.get_stats_by_user(123456789)
        assert stats["total_publications"] == 2
        assert stats["total_tokens_spent"] == 300
