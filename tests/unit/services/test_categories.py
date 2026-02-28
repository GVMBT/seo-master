"""Tests for services/categories.py — CategoryService.

Covers: ownership checks, CRUD, H17 limit, delete with E24+E42 cleanup,
settings updates, prices/description clear operations.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.categories import MAX_CATEGORIES_PER_PROJECT, CategoryService

_SVC_MODULE = "services.categories"


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def cat_svc(mock_db: MagicMock) -> CategoryService:
    return CategoryService(db=mock_db)


# ---------------------------------------------------------------------------
# get_owned_category
# ---------------------------------------------------------------------------


class TestGetOwnedCategory:
    async def test_returns_category_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)

        result = await cat_svc.get_owned_category(5, 42)
        assert result is category
        cat_svc._cats_repo.get_by_id.assert_awaited_once_with(5)
        cat_svc._projects_repo.get_by_id.assert_awaited_once_with(10)

    async def test_returns_none_when_not_found(self, cat_svc: CategoryService) -> None:
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=None)

        result = await cat_svc.get_owned_category(5, 42)
        assert result is None

    async def test_returns_none_when_project_not_found(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=None)

        result = await cat_svc.get_owned_category(5, 42)
        assert result is None

    async def test_returns_none_when_not_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=99)
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)

        result = await cat_svc.get_owned_category(5, 42)
        assert result is None


# ---------------------------------------------------------------------------
# list_by_project
# ---------------------------------------------------------------------------


class TestListByProject:
    async def test_returns_categories(self, cat_svc: CategoryService) -> None:
        project = MagicMock(user_id=42)
        cats = [MagicMock(), MagicMock()]
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.get_by_project = AsyncMock(return_value=cats)

        result = await cat_svc.list_by_project(1, 42)
        assert result == cats

    async def test_returns_none_when_not_owned(self, cat_svc: CategoryService) -> None:
        project = MagicMock(user_id=99)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)

        result = await cat_svc.list_by_project(1, 42)
        assert result is None

    async def test_returns_none_when_project_missing(self, cat_svc: CategoryService) -> None:
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=None)

        result = await cat_svc.list_by_project(1, 42)
        assert result is None


# ---------------------------------------------------------------------------
# check_category_limit (H17)
# ---------------------------------------------------------------------------


class TestCheckCategoryLimit:
    async def test_under_limit(self, cat_svc: CategoryService) -> None:
        project = MagicMock(user_id=42)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.get_count_by_project = AsyncMock(return_value=10)

        result = await cat_svc.check_category_limit(1, 42)
        assert result is True

    async def test_at_limit(self, cat_svc: CategoryService) -> None:
        project = MagicMock(user_id=42)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.get_count_by_project = AsyncMock(return_value=MAX_CATEGORIES_PER_PROJECT)

        result = await cat_svc.check_category_limit(1, 42)
        assert result is False

    async def test_returns_none_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=None)

        result = await cat_svc.check_category_limit(1, 42)
        assert result is None


# ---------------------------------------------------------------------------
# create_category
# ---------------------------------------------------------------------------


class TestCreateCategory:
    async def test_creates_category(self, cat_svc: CategoryService) -> None:
        project = MagicMock(user_id=42)
        new_cat = MagicMock(id=100, name="Test")
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.create = AsyncMock(return_value=new_cat)

        result = await cat_svc.create_category(1, 42, "Test")
        assert result is new_cat
        cat_svc._cats_repo.create.assert_awaited_once()

    async def test_returns_none_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=None)

        result = await cat_svc.create_category(1, 42, "Test")
        assert result is None


# ---------------------------------------------------------------------------
# delete_category (E24 + E42)
# ---------------------------------------------------------------------------


class TestDeleteCategory:
    async def test_full_delete_flow(self, cat_svc: CategoryService) -> None:
        """E24: cancel QStash + E42: refund previews + delete + return remaining."""
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)
        remaining = [MagicMock()]

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.delete = AsyncMock(return_value=True)
        cat_svc._cats_repo.get_by_project = AsyncMock(return_value=remaining)

        scheduler_svc = MagicMock()
        scheduler_svc.cancel_schedules_for_category = AsyncMock()

        token_svc = MagicMock()
        token_svc.refund_active_previews = AsyncMock()

        active_previews = [MagicMock()]

        with patch(f"{_SVC_MODULE}.PreviewsRepository") as MockPreviews:
            MockPreviews.return_value.get_active_drafts_by_category = AsyncMock(return_value=active_previews)

            deleted, cat, remaining_result = await cat_svc.delete_category(
                category_id=5, user_id=42,
                scheduler_svc=scheduler_svc, token_svc=token_svc,
            )

        assert deleted is True
        assert cat is category
        assert remaining_result == remaining
        scheduler_svc.cancel_schedules_for_category.assert_awaited_once_with(5)
        token_svc.refund_active_previews.assert_awaited_once()

    async def test_returns_false_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=None)

        scheduler_svc = MagicMock()
        token_svc = MagicMock()

        deleted, cat, remaining = await cat_svc.delete_category(5, 42, scheduler_svc, token_svc)
        assert deleted is False
        assert cat is None
        assert remaining == []

    async def test_no_previews_to_refund(self, cat_svc: CategoryService) -> None:
        """When no active previews, skip refund."""
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.delete = AsyncMock(return_value=True)
        cat_svc._cats_repo.get_by_project = AsyncMock(return_value=[])

        scheduler_svc = MagicMock()
        scheduler_svc.cancel_schedules_for_category = AsyncMock()

        token_svc = MagicMock()
        token_svc.refund_active_previews = AsyncMock()

        with patch(f"{_SVC_MODULE}.PreviewsRepository") as MockPreviews:
            MockPreviews.return_value.get_active_drafts_by_category = AsyncMock(return_value=[])

            deleted, _cat, _remaining = await cat_svc.delete_category(
                category_id=5, user_id=42,
                scheduler_svc=scheduler_svc, token_svc=token_svc,
            )

        assert deleted is True
        token_svc.refund_active_previews.assert_not_awaited()


# ---------------------------------------------------------------------------
# get_delete_impact
# ---------------------------------------------------------------------------


class TestGetDeleteImpact:
    async def test_returns_impact(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)
        schedules = [MagicMock(enabled=True), MagicMock(enabled=False), MagicMock(enabled=True)]

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)

        with patch(f"{_SVC_MODULE}.SchedulesRepository") as MockSched:
            MockSched.return_value.get_by_category = AsyncMock(return_value=schedules)
            result = await cat_svc.get_delete_impact(5, 42)

        assert result is not None
        cat_out, active_count = result
        assert cat_out is category
        assert active_count == 2

    async def test_returns_none_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=None)
        result = await cat_svc.get_delete_impact(5, 42)
        assert result is None


# ---------------------------------------------------------------------------
# Update operations
# ---------------------------------------------------------------------------


class TestUpdateTextSettings:
    async def test_updates_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)
        updated = MagicMock()

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.update = AsyncMock(return_value=updated)

        result = await cat_svc.update_text_settings(5, 42, {"min_words": 500})
        assert result is updated

    async def test_returns_none_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=None)
        result = await cat_svc.update_text_settings(5, 42, {"min_words": 500})
        assert result is None


class TestUpdateImageSettings:
    async def test_updates_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)
        updated = MagicMock()

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.update = AsyncMock(return_value=updated)

        result = await cat_svc.update_image_settings(5, 42, {"count": 3})
        assert result is updated


class TestUpdatePrices:
    async def test_updates_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)
        updated = MagicMock()

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.update = AsyncMock(return_value=updated)

        result = await cat_svc.update_prices(5, 42, "Item — 100 руб")
        assert result is updated


class TestClearPrices:
    async def test_clears_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.clear_prices = AsyncMock()

        result = await cat_svc.clear_prices(5, 42)
        assert result is True
        cat_svc._cats_repo.clear_prices.assert_awaited_once_with(5)

    async def test_returns_false_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=None)
        result = await cat_svc.clear_prices(5, 42)
        assert result is False


class TestUpdateDescription:
    async def test_updates_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)
        updated = MagicMock()

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.update = AsyncMock(return_value=updated)

        result = await cat_svc.update_description(5, 42, "Some description")
        assert result is updated


class TestClearDescription:
    async def test_clears_when_owned(self, cat_svc: CategoryService) -> None:
        category = MagicMock(project_id=10)
        project = MagicMock(user_id=42)

        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=category)
        cat_svc._projects_repo.get_by_id = AsyncMock(return_value=project)
        cat_svc._cats_repo.clear_description = AsyncMock()

        result = await cat_svc.clear_description(5, 42)
        assert result is True
        cat_svc._cats_repo.clear_description.assert_awaited_once_with(5)

    async def test_returns_false_when_not_owned(self, cat_svc: CategoryService) -> None:
        cat_svc._cats_repo.get_by_id = AsyncMock(return_value=None)
        result = await cat_svc.clear_description(5, 42)
        assert result is False
