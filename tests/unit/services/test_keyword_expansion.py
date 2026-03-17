"""Tests for services/keyword_expansion.py — auto keyword pool expansion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.keyword_expansion import EXPANSION_LOCK_TTL, KeywordExpansionService


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_keyword_service() -> AsyncMock:
    svc = AsyncMock()
    svc.fetch_raw_phrases = AsyncMock(return_value=["phrase1", "phrase2"])
    svc.cluster_phrases = AsyncMock(return_value=[
        {"main_phrase": "new cluster", "phrases": [
            {"phrase": "new cluster"},
            {"phrase": "new phrase 1"},
            {"phrase": "new phrase 2"},
            {"phrase": "new phrase 3"},
            {"phrase": "new phrase 4"},
            {"phrase": "new phrase 5"},
        ]},
    ])
    svc.enrich_clusters = AsyncMock(side_effect=lambda x: x)
    svc.filter_low_quality = MagicMock(side_effect=lambda x: x)
    svc.generate_clusters_direct = AsyncMock(return_value=[])
    return svc


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)  # Lock acquired
    return redis


@pytest.fixture
def service(mock_db: MagicMock, mock_keyword_service: AsyncMock, mock_redis: AsyncMock) -> KeywordExpansionService:
    return KeywordExpansionService(mock_db, mock_keyword_service, mock_redis)


@pytest.fixture
def existing_keywords() -> list[dict]:
    return [
        {
            "cluster_name": "existing",
            "main_phrase": "existing main",
            "phrases": [{"phrase": "existing main"}, {"phrase": "existing sec"}],
        },
    ]


class TestMaybeExpand:
    async def test_acquires_redis_lock(
        self, service: KeywordExpansionService, mock_redis: AsyncMock, existing_keywords: list[dict]
    ) -> None:
        with patch.object(service, "_do_expand", new_callable=AsyncMock, return_value=True):
            await service.maybe_expand(1, 100, 200, existing_keywords)
        mock_redis.set.assert_called_once_with("keyword_expand:1", "1", ex=EXPANSION_LOCK_TTL, nx=True)

    async def test_skips_when_locked(
        self, service: KeywordExpansionService, mock_redis: AsyncMock, existing_keywords: list[dict]
    ) -> None:
        mock_redis.set.return_value = False  # Lock NOT acquired
        result = await service.maybe_expand(1, 100, 200, existing_keywords)
        assert result is False

    async def test_returns_false_on_exception(
        self, service: KeywordExpansionService, existing_keywords: list[dict]
    ) -> None:
        with patch.object(service, "_do_expand", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            result = await service.maybe_expand(1, 100, 200, existing_keywords)
        assert result is False

    async def test_works_without_redis(self, mock_db: MagicMock, mock_keyword_service: AsyncMock) -> None:
        service = KeywordExpansionService(mock_db, mock_keyword_service, redis=None)
        with patch.object(service, "_do_expand", new_callable=AsyncMock, return_value=True):
            result = await service.maybe_expand(1, 100, 200, [{"main_phrase": "x", "phrases": []}])
        assert result is True


class TestDoExpand:
    async def test_no_seeds_returns_false(self, service: KeywordExpansionService) -> None:
        result = await service._do_expand(1, 100, 200, [])
        assert result is False

    async def test_successful_expansion(
        self,
        service: KeywordExpansionService,
        mock_keyword_service: AsyncMock,
        existing_keywords: list[dict],
    ) -> None:
        with (
            patch("services.keyword_expansion.CategoriesRepository") as mock_cats_cls,
            patch("db.repositories.projects.ProjectsRepository") as mock_proj_cls,
        ):
            mock_cats = AsyncMock()
            mock_cats.get_by_id = AsyncMock(return_value=MagicMock(name="test_cat"))
            mock_cats.update_keywords = AsyncMock()
            mock_cats_cls.return_value = mock_cats

            mock_proj = AsyncMock()
            mock_proj.get_by_id = AsyncMock(return_value=MagicMock(company_city="Moscow"))
            mock_proj_cls.return_value = mock_proj

            # Override _cats_repo
            service._cats_repo = mock_cats

            result = await service._do_expand(1, 100, 200, existing_keywords)
            assert result is True
            mock_cats.update_keywords.assert_called_once()

    async def test_deduplicates_existing_phrases(
        self,
        service: KeywordExpansionService,
        mock_keyword_service: AsyncMock,
    ) -> None:
        """New clusters with same main_phrase as existing should be filtered out."""
        existing = [
            {
                "main_phrase": "new cluster",
                "phrases": [{"phrase": "new cluster"}],
            },
        ]
        with (
            patch("services.keyword_expansion.CategoriesRepository") as mock_cats_cls,
            patch("db.repositories.projects.ProjectsRepository") as mock_proj_cls,
        ):
            mock_cats = AsyncMock()
            mock_cats.get_by_id = AsyncMock(return_value=MagicMock(name="test_cat"))
            mock_cats.update_keywords = AsyncMock()
            mock_cats_cls.return_value = mock_cats
            service._cats_repo = mock_cats

            mock_proj = AsyncMock()
            mock_proj.get_by_id = AsyncMock(return_value=MagicMock(company_city=""))
            mock_proj_cls.return_value = mock_proj

            result = await service._do_expand(1, 100, 200, existing)
            # "new cluster" already exists → deduplicated → too few new phrases → False
            assert result is False

    async def test_e03_fallback_when_no_raw_phrases(
        self,
        service: KeywordExpansionService,
        mock_keyword_service: AsyncMock,
        existing_keywords: list[dict],
    ) -> None:
        """E03: DataForSEO returns empty → fallback to generate_clusters_direct."""
        mock_keyword_service.fetch_raw_phrases.return_value = []
        mock_keyword_service.generate_clusters_direct.return_value = []

        with (
            patch("services.keyword_expansion.CategoriesRepository") as mock_cats_cls,
            patch("db.repositories.projects.ProjectsRepository") as mock_proj_cls,
        ):
            mock_cats = AsyncMock()
            mock_cats.get_by_id = AsyncMock(return_value=MagicMock(name="test_cat"))
            mock_cats_cls.return_value = mock_cats
            service._cats_repo = mock_cats

            mock_proj = AsyncMock()
            mock_proj.get_by_id = AsyncMock(return_value=MagicMock(company_city=""))
            mock_proj_cls.return_value = mock_proj

            result = await service._do_expand(1, 100, 200, existing_keywords)
            assert result is False
            mock_keyword_service.generate_clusters_direct.assert_called_once()
