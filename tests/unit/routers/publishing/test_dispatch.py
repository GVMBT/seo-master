"""Tests for routers/publishing/dispatch.py -- publish dispatch handler."""

from unittest.mock import AsyncMock, MagicMock, patch

from db.models import Category, PlatformConnection, Project, User
from routers.publishing.dispatch import cb_publish_dispatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(
    id: int = 1,
    platform_type: str = "wordpress",
    identifier: str = "site.com",
    status: str = "active",
) -> PlatformConnection:
    return PlatformConnection(
        id=id,
        project_id=1,
        platform_type=platform_type,
        identifier=identifier,
        credentials={},
        status=status,
    )



# ---------------------------------------------------------------------------
# cb_publish_dispatch
# ---------------------------------------------------------------------------


class TestCbPublishDispatch:
    async def test_category_not_found_shows_alert(
        self, mock_callback: MagicMock, mock_state: AsyncMock, user: User, mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:99:publish"
        with patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo:
            cat_repo.return_value.get_by_id = AsyncMock(return_value=None)
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_project_ownership_check_rejects_other_user(
        self, mock_callback: MagicMock, mock_state: AsyncMock, user: User, mock_db: MagicMock, category: Category,
    ) -> None:
        """Security: callback_data tampering -- user cannot dispatch for another user's project."""
        mock_callback.data = f"category:{category.id}:publish"
        other_project = Project(id=1, user_id=999, name="Other", company_name="X", specialization="Y")
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=other_project)
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    async def test_zero_connections_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """0 active connections -> alert message."""
        mock_callback.data = f"category:{category.id}:publish"
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.dispatch.get_settings"),
            patch("routers.publishing.dispatch.CredentialManager"),
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            conn_repo.return_value.get_by_project = AsyncMock(return_value=[])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert "платформу" in mock_callback.answer.call_args.args[0].lower()

    async def test_single_wp_dispatches_to_article_flow(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """1 WP connection -> delegates to cb_article_start_with_conn."""
        mock_callback.data = f"category:{category.id}:publish"
        wp_conn = _make_conn(id=5, platform_type="wordpress")
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.dispatch.get_settings"),
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.preview.cb_article_start_with_conn", new_callable=AsyncMock) as mock_article,
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            conn_repo.return_value.get_by_project = AsyncMock(return_value=[wp_conn])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_article.assert_awaited_once()
        assert mock_callback.data == f"category:{category.id}:publish:wp:5"

    async def test_single_telegram_dispatches_to_social_flow(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """1 Telegram connection -> delegates to cb_social_start."""
        mock_callback.data = f"category:{category.id}:publish"
        tg_conn = _make_conn(id=7, platform_type="telegram", identifier="@channel")
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.dispatch.get_settings"),
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.social.cb_social_start", new_callable=AsyncMock) as mock_social,
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            conn_repo.return_value.get_by_project = AsyncMock(return_value=[tg_conn])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_social.assert_awaited_once()

    async def test_multiple_connections_shows_choice_keyboard(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """Multiple active connections -> platform choice keyboard."""
        mock_callback.data = f"category:{category.id}:publish"
        conns = [
            _make_conn(id=1, platform_type="wordpress"),
            _make_conn(id=2, platform_type="telegram", identifier="@ch"),
        ]
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.dispatch.get_settings"),
            patch("routers.publishing.dispatch.CredentialManager"),
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            conn_repo.return_value.get_by_project = AsyncMock(return_value=conns)
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_callback.message.edit_text.assert_awaited_once()
        assert "платформу" in mock_callback.message.edit_text.call_args.args[0].lower()

    async def test_inactive_connections_filtered_out(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """Inactive connections are filtered: if only inactive ones, show alert."""
        mock_callback.data = f"category:{category.id}:publish"
        conns = [_make_conn(id=1, platform_type="wordpress", status="inactive")]
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.dispatch.get_settings"),
            patch("routers.publishing.dispatch.CredentialManager"),
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            conn_repo.return_value.get_by_project = AsyncMock(return_value=conns)
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert "платформу" in mock_callback.answer.call_args.args[0].lower()

    async def test_single_vk_dispatches_to_social(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        project: Project,
        category: Category,
    ) -> None:
        """Single VK connection dispatches to social flow (not article)."""
        mock_callback.data = f"category:{category.id}:publish"
        vk_conn = _make_conn(id=3, platform_type="vk", identifier="group")
        with (
            patch("routers.publishing.dispatch.CategoriesRepository") as cat_repo,
            patch("routers.publishing.dispatch.ProjectsRepository") as proj_repo,
            patch("routers.publishing.dispatch.ConnectionsRepository") as conn_repo,
            patch("routers.publishing.dispatch.get_settings"),
            patch("routers.publishing.dispatch.CredentialManager"),
            patch("routers.publishing.social.cb_social_start", new_callable=AsyncMock) as mock_social,
        ):
            cat_repo.return_value.get_by_id = AsyncMock(return_value=category)
            proj_repo.return_value.get_by_id = AsyncMock(return_value=project)
            conn_repo.return_value.get_by_project = AsyncMock(return_value=[vk_conn])
            await cb_publish_dispatch(mock_callback, mock_state, user, mock_db)
        mock_social.assert_awaited_once()
