"""Tests for routers/publishing/quick.py — Quick Publish flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, PlatformConnection, Project, User
from routers.publishing.quick import (
    _build_combos,
    cb_publish_dispatch,
    cb_quick_combo_page,
    cb_quick_proj_page,
    cb_quick_project,
    cb_quick_publish_target,
    send_quick_publish_menu,
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
# send_quick_publish_menu
# ---------------------------------------------------------------------------


class TestSendQuickPublishMenu:
    async def test_no_projects_shows_message(
        self, mock_message: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        with patch("routers.publishing.quick.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await send_quick_publish_menu(mock_message, user, mock_db)
            mock_message.answer.assert_awaited_once()
            assert "нет проектов" in mock_message.answer.call_args.args[0].lower()

    async def test_single_project_shows_combos(
        self, mock_message: MagicMock, user: User, mock_db: MagicMock,
        project: Project, category: Category, wp_connection: PlatformConnection,
    ) -> None:
        with (
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick._build_combos", new_callable=AsyncMock) as build_combos,
        ):
            proj_cls.return_value.get_by_user = AsyncMock(return_value=[project])
            build_combos.return_value = [
                {"cat_id": 10, "cat_name": "SEO", "platform": "wordpress", "conn_id": 5, "conn_name": "blog"},
            ]
            await send_quick_publish_menu(mock_message, user, mock_db)
            # Should show combo list, not project list
            mock_message.answer.assert_awaited()
            call_kwargs = mock_message.answer.call_args.kwargs
            assert "reply_markup" in call_kwargs

    async def test_multiple_projects_shows_project_list(
        self, mock_message: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        p1 = Project(id=1, user_id=user.id, name="A", company_name="A", specialization="A")
        p2 = Project(id=2, user_id=user.id, name="B", company_name="B", specialization="B")
        with patch("routers.publishing.quick.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_user = AsyncMock(return_value=[p1, p2])
            await send_quick_publish_menu(mock_message, user, mock_db)
            mock_message.answer.assert_awaited()
            assert "проект" in mock_message.answer.call_args.args[0].lower()

    async def test_single_project_no_combos(
        self, mock_message: MagicMock, user: User, mock_db: MagicMock, project: Project,
    ) -> None:
        with (
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick._build_combos", new_callable=AsyncMock) as build_combos,
        ):
            proj_cls.return_value.get_by_user = AsyncMock(return_value=[project])
            build_combos.return_value = []
            await send_quick_publish_menu(mock_message, user, mock_db)
            assert "нет доступных" in mock_message.answer.call_args.args[0].lower()


# ---------------------------------------------------------------------------
# cb_publish_dispatch (category card → [Опубликовать])
# ---------------------------------------------------------------------------


class TestCbPublishDispatch:
    """Tests for category:{id}:publish → platform dispatch."""

    async def test_no_connections_shows_alert(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
    ) -> None:
        mock_callback.data = f"category:{category.id}:publish"
        with (
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
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
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
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
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
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
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
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
        with patch("routers.publishing.quick.CategoriesRepository") as cat_cls:
            cat_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# cb_quick_project
# ---------------------------------------------------------------------------


class TestCbQuickProject:
    async def test_shows_combos(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project,
    ) -> None:
        mock_callback.data = f"quick:project:{project.id}"
        with (
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick._build_combos", new_callable=AsyncMock) as build_combos,
        ):
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            build_combos.return_value = [
                {"cat_id": 1, "cat_name": "A", "platform": "wordpress", "conn_id": 5, "conn_name": "x"},
            ]
            await cb_quick_project(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    async def test_unauthorized_project(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "quick:project:999"
        with patch("routers.publishing.quick.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_quick_project(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_no_combos_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project,
    ) -> None:
        mock_callback.data = f"quick:project:{project.id}"
        with (
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick._build_combos", new_callable=AsyncMock) as build_combos,
        ):
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            build_combos.return_value = []
            await cb_quick_project(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# cb_quick_publish_target
# ---------------------------------------------------------------------------


class TestCbQuickPublishTarget:
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

    async def test_vk_delegates_to_social(
        self, mock_callback: MagicMock, mock_state: AsyncMock,
        user: User, mock_db: MagicMock, project: Project, category: Category,
    ) -> None:
        mock_callback.data = f"quick:cat:{category.id}:vk:7"
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


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TestPagination:
    async def test_project_pagination(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "page:quick_proj:1"
        projects = [
            Project(id=i, user_id=user.id, name=f"P{i}", company_name="C", specialization="S")
            for i in range(12)
        ]
        with patch("routers.publishing.quick.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
            await cb_quick_proj_page(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    async def test_combo_pagination(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock, project: Project,
    ) -> None:
        mock_callback.data = f"page:quick_combo:{project.id}:1"
        with (
            patch("routers.publishing.quick.ProjectsRepository") as proj_cls,
            patch("routers.publishing.quick._build_combos", new_callable=AsyncMock) as build_combos,
        ):
            proj_cls.return_value.get_by_id = AsyncMock(return_value=project)
            build_combos.return_value = [
                {"cat_id": i, "cat_name": f"C{i}", "platform": "wordpress", "conn_id": 1, "conn_name": "x"}
                for i in range(12)
            ]
            await cb_quick_combo_page(mock_callback, user, mock_db)
            mock_callback.message.edit_text.assert_awaited_once()

    async def test_combo_pagination_unauthorized(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "page:quick_combo:999:0"
        with patch("routers.publishing.quick.ProjectsRepository") as proj_cls:
            proj_cls.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_quick_combo_page(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True


# ---------------------------------------------------------------------------
# _build_combos helper
# ---------------------------------------------------------------------------


class TestBuildCombos:
    async def test_builds_combos_from_categories_and_connections(self, mock_db: MagicMock) -> None:
        project = Project(id=1, user_id=100, name="P", company_name="C", specialization="S")
        cat = Category(id=10, project_id=1, name="SEO")
        conn = PlatformConnection(
            id=5, project_id=1, platform_type="wordpress",
            identifier="blog.com", credentials={}, status="active",
        )
        with (
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
        ):
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[cat])
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[conn])
            combos = await _build_combos(project, mock_db)
            assert len(combos) == 1
            assert combos[0]["cat_id"] == 10
            assert combos[0]["platform"] == "wordpress"

    async def test_empty_when_no_categories(self, mock_db: MagicMock) -> None:
        project = Project(id=1, user_id=100, name="P", company_name="C", specialization="S")
        with (
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
        ):
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[])
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[])
            combos = await _build_combos(project, mock_db)
            assert combos == []

    async def test_skips_inactive_connections(self, mock_db: MagicMock) -> None:
        project = Project(id=1, user_id=100, name="P", company_name="C", specialization="S")
        cat = Category(id=10, project_id=1, name="SEO")
        inactive = PlatformConnection(
            id=5, project_id=1, platform_type="wordpress",
            identifier="x", credentials={}, status="inactive",
        )
        with (
            patch("routers.publishing.quick.get_settings") as settings_mock,
            patch("routers.publishing.quick.CredentialManager"),
            patch("routers.publishing.quick.CategoriesRepository") as cat_cls,
            patch("routers.publishing.quick.ConnectionsRepository") as conn_cls,
        ):
            settings_mock.return_value.encryption_key.get_secret_value.return_value = "k" * 44
            cat_cls.return_value.get_by_project = AsyncMock(return_value=[cat])
            conn_cls.return_value.get_by_project = AsyncMock(return_value=[inactive])
            combos = await _build_combos(project, mock_db)
            assert combos == []
