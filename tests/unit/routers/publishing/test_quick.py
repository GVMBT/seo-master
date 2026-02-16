"""Tests for routers/publishing/quick.py + dispatch.py -- publish dispatch + legacy handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, PlatformConnection, Project, User
from routers.publishing.dispatch import cb_publish_dispatch
from routers.publishing.quick import (
    cb_quick_combo_page,
    cb_quick_proj_page,
    cb_quick_project,
    cb_quick_publish_target,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def wp_connection() -> PlatformConnection:
    return PlatformConnection(
        id=5, project_id=1, platform_type="wordpress",
        identifier="blog.example.com", credentials={}, status="active",
    )


@pytest.fixture
def tg_connection() -> PlatformConnection:
    return PlatformConnection(
        id=6, project_id=1, platform_type="telegram",
        identifier="@mychannel", credentials={}, status="active",
    )


# ---------------------------------------------------------------------------
# cb_publish_dispatch (category card -> [Опубликовать])
# ---------------------------------------------------------------------------


class TestCbPublishDispatch:
    """Tests for category:{id}:publish -> platform dispatch."""

    async def test_no_connections_shows_alert(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:publish"
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_cls,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_cls,
            patch("routers.publishing.dispatch.get_settings") as settings_mock,
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert "платформу" in mock_callback.answer.call_args.args[0].lower()

    async def test_single_wp_delegates_to_article(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
        wp_connection: PlatformConnection,
    ) -> None:
        mock_callback.data = f"category:{category.id}:publish"
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_cls,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_cls,
            patch("routers.publishing.dispatch.get_settings") as settings_mock,
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_cls,
            patch("routers.publishing.preview.cb_article_start_with_conn", new_callable=AsyncMock) as delegate,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[wp_connection])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
            delegate.assert_awaited_once()

    async def test_single_social_delegates_to_social(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
        tg_connection: PlatformConnection,
    ) -> None:
        mock_callback.data = f"category:{category.id}:publish"
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_cls,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_cls,
            patch("routers.publishing.dispatch.get_settings") as settings_mock,
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_cls,
            patch("routers.publishing.social.cb_social_start", new_callable=AsyncMock) as delegate,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[tg_connection])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
            delegate.assert_awaited_once()

    async def test_multiple_connections_shows_platform_choice(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
        wp_connection: PlatformConnection, tg_connection: PlatformConnection,
    ) -> None:
        mock_callback.data = f"category:{category.id}:publish"
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_cls,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_cls,
            patch("routers.publishing.dispatch.get_settings") as settings_mock,
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_cls,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[wp_connection, tg_connection])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()
            assert "платформу" in mock_callback.message.edit_text.call_args.args[0].lower()

    async def test_unauthorized_category_shows_alert(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:999:publish"
        with patch("routers.publishing.dispatch.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# Legacy quick publish handlers (deprecated)
# ---------------------------------------------------------------------------


class TestLegacyQuickProject:
    async def test_shows_deprecation_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "quick:project:1"
        await cb_quick_project(mock_callback, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


class TestLegacyQuickPublishTarget:
    async def test_wp_delegates_to_article(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
    ) -> None:
        mock_callback.data = f"quick:cat:{category.id}:wp:5"
        with (
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.preview.cb_article_start_with_conn", new_callable=AsyncMock) as delegate,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_quick_publish_target(mock_callback, mock_state, user, mock_db)
            delegate.assert_awaited_once()

    async def test_tg_delegates_to_social(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
    ) -> None:
        mock_callback.data = f"quick:cat:{category.id}:tg:6"
        with (
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.social.cb_social_start", new_callable=AsyncMock) as delegate,
        ):
            cat_cls.return_value.get_by_id = AsyncMock(return_value=category)
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            await cb_quick_publish_target(mock_callback, mock_state, user, mock_db)
            delegate.assert_awaited_once()

    async def test_unauthorized_category(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "quick:cat:999:wp:5"
        with patch("routers.publishing.quick.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_quick_publish_target(mock_callback, mock_state, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


class TestLegacyPagination:
    async def test_project_pagination_shows_deprecation(
        self, mock_callback: MagicMock,
    ) -> None:
        mock_callback.data = "page:quick_proj:1"
        await cb_quick_proj_page(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_combo_pagination_shows_deprecation(
        self, mock_callback: MagicMock,
    ) -> None:
        mock_callback.data = "page:quick_combo:1:0"
        await cb_quick_combo_page(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
