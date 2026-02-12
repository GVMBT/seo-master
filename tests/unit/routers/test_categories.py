"""Tests for routers/categories/."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, Project, User
from routers.categories import (
    CategoryCreateFSM,
    _format_category_card,
    _validate_category_name,
    cb_category_card,
    cb_category_delete,
    cb_category_delete_confirm,
    cb_category_feature_stub,
    cb_category_list,
    cb_category_new,
    cb_category_page,
    fsm_category_name,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidateCategoryName:
    def test_valid_name(self) -> None:
        assert _validate_category_name("Kitchen furniture") is None

    def test_too_short(self) -> None:
        assert _validate_category_name("A") is not None

    def test_too_long(self) -> None:
        assert _validate_category_name("x" * 101) is not None

    def test_special_chars(self) -> None:
        assert _validate_category_name("Good, name!") is None


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------


class TestFormatCategoryCard:
    def test_includes_name(self, category: Category) -> None:
        text = _format_category_card(category)
        assert category.name in text

    def test_shows_keywords_count(self) -> None:
        cat = Category(id=1, project_id=1, name="Test", keywords=[{"phrase": "test"}])
        text = _format_category_card(cat)
        assert "1" in text


# ---------------------------------------------------------------------------
# Category list
# ---------------------------------------------------------------------------


class TestCbCategoryList:
    @pytest.mark.asyncio
    async def test_shows_categories(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
        project: Project, category: Category
    ) -> None:
        mock_callback.data = f"project:{project.id}:categories"
        with (
            patch("routers.categories.manage.ProjectsRepository") as proj_cls,
            patch("routers.categories.manage.CategoriesRepository") as cat_cls,
        ):
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[category])
            await cb_category_list(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unauthorized_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "project:999:categories"
        with patch("routers.categories.manage.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_category_list(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


class TestCbCategoryPage:
    @pytest.mark.asyncio
    async def test_pagination(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"page:categories:{project.id}:1"
        with (
            patch("routers.categories.manage.ProjectsRepository") as proj_cls,
            patch("routers.categories.manage.CategoriesRepository") as cat_cls,
        ):
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[])
            await cb_category_page(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# Category card
# ---------------------------------------------------------------------------


class TestCbCategoryCard:
    @pytest.mark.asyncio
    async def test_shows_card(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
        project: Project, category: Category
    ) -> None:
        mock_callback.data = f"category:{category.id}:card"
        with (
            patch("routers.categories.manage.CategoriesRepository") as cat_cls,
            patch("routers.categories.manage.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_category_card(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "category:999:card"
        with patch("routers.categories.manage.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_category_card(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# Feature stub
# ---------------------------------------------------------------------------


class TestCbCategoryFeatureStub:
    @pytest.mark.asyncio
    async def test_shows_in_development(self, mock_callback: MagicMock) -> None:
        await cb_category_feature_stub(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Create FSM
# ---------------------------------------------------------------------------


class TestCategoryCreateFSM:
    @pytest.mark.asyncio
    async def test_new_starts_fsm(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project
    ) -> None:
        mock_callback.data = f"project:{project.id}:cat:new"
        mock_state.get_state = AsyncMock(return_value=None)
        with patch("routers.categories.manage.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_category_new(mock_callback, mock_state, user, mock_db)
            mock_state.set_state.assert_awaited_once_with(CategoryCreateFSM.name)

    @pytest.mark.asyncio
    async def test_name_valid_creates(
        self, mock_message: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, category: Category
    ) -> None:
        mock_message.text = "New Category"
        mock_state.get_data.return_value = {"project_id": 1}
        with patch("routers.categories.manage.CategoriesRepository") as cat_cls:
            cat_cls.return_value.create = AsyncMock(return_value=category)
            await fsm_category_name(mock_message, mock_state, user, mock_db)
            mock_state.clear.assert_awaited_once()
            cat_cls.return_value.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_name_invalid_repeats(
        self, mock_message: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock
    ) -> None:
        mock_message.text = "X"
        await fsm_category_name(mock_message, mock_state, user, mock_db)
        mock_state.clear.assert_not_awaited()
        mock_message.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestCategoryDelete:
    @pytest.mark.asyncio
    async def test_shows_confirmation(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
        project: Project, category: Category
    ) -> None:
        mock_callback.data = f"category:{category.id}:delete"
        with (
            patch("routers.categories.manage.CategoriesRepository") as cat_cls,
            patch("routers.categories.manage.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_category_delete(mock_callback, user, mock_db)
            text = mock_callback.message.edit_text.call_args.args[0]
            assert "удалить" in text.lower()

    @pytest.mark.asyncio
    async def test_confirm_deletes(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
        project: Project, category: Category
    ) -> None:
        mock_callback.data = f"category:{category.id}:delete:confirm"
        with (
            patch("routers.categories.manage.CategoriesRepository") as cat_cls,
            patch("routers.categories.manage.ProjectsRepository") as proj_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            cat_cls.return_value.delete = AsyncMock(return_value=True)
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[])
            await cb_category_delete_confirm(mock_callback, user, mock_db)
            cat_cls.return_value.delete.assert_awaited_once_with(category.id)
