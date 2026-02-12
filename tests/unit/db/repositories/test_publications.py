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
    async def test_create(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient, pub_row: dict
    ) -> None:
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
    async def test_returns_list(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient, pub_row: dict
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[pub_row]))
        logs = await repo.get_by_user(123456789)
        assert len(logs) == 1

    async def test_empty(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        assert await repo.get_by_user(999) == []


class TestGetByProject:
    async def test_returns_list(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient, pub_row: dict
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[pub_row]))
        logs = await repo.get_by_project(1)
        assert len(logs) == 1


class TestGetRecentlyUsedKeywords:
    async def test_returns_keywords(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response(
            "publication_logs",
            MockResponse(data=[{"keyword": "seo tips"}, {"keyword": "seo guide"}]),
        )
        keywords = await repo.get_recently_used_keywords(1)
        assert keywords == ["seo tips", "seo guide"]

    async def test_empty(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        assert await repo.get_recently_used_keywords(1) == []


class TestGetLruKeyword:
    async def test_returns_oldest(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[{"keyword": "oldest kw"}]))
        assert await repo.get_lru_keyword(1) == "oldest kw"

    async def test_none_when_empty(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        assert await repo.get_lru_keyword(1) is None


class TestGetRotationKeyword:
    """Keyword rotation algorithm (API_CONTRACTS.md §6)."""

    async def test_empty_pool_returns_none(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        kw, warning = await repo.get_rotation_keyword(1, [])
        assert kw is None
        assert warning is True

    async def test_picks_highest_volume_first(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
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

    async def test_skips_recently_used(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response(
            "publication_logs", MockResponse(data=[{"keyword": "high vol"}])
        )
        keywords = [
            {"phrase": "high vol", "volume": 1000, "difficulty": 20},
            {"phrase": "next best", "volume": 500, "difficulty": 10},
        ]
        kw, _ = await repo.get_rotation_keyword(1, keywords)
        assert kw == "next best"

    async def test_low_pool_warning_when_less_than_5(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        keywords = [
            {"phrase": "kw1", "volume": 100, "difficulty": 10},
            {"phrase": "kw2", "volume": 200, "difficulty": 20},
        ]
        _, warning = await repo.get_rotation_keyword(1, keywords)
        assert warning is True

    async def test_no_warning_when_5_or_more(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("publication_logs", MockResponse(data=[]))
        keywords = [{"phrase": f"kw{i}", "volume": i * 100, "difficulty": i} for i in range(5)]
        _, warning = await repo.get_rotation_keyword(1, keywords)
        assert warning is False

    async def test_all_on_cooldown_uses_lru_fallback(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
        """E22: all keywords used in last 7 days -> LRU fallback."""
        # First call (get_recently_used_keywords) returns all keywords as used
        # But our mock returns same response for all calls to same table
        # So we test the fallback path by making all keywords "used"
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


class TestGetStatsByUser:
    async def test_aggregated_stats(
        self, repo: PublicationsRepository, mock_db: MockSupabaseClient
    ) -> None:
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
