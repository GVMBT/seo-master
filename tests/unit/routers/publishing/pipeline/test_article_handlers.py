"""Tests for routers/publishing/pipeline/article.py handlers.

Covers steps 1-3 of the Article Pipeline:
- pipeline_article_start: 0/1/>1 projects
- pipeline_select_project: ownership check, loading
- pipeline_projects_page: pagination
- Inline project creation: 4 states (name -> company -> spec -> url)
- WP step: 0/1 connections (1 project = max 1 WP, no multi-WP)
- pipeline_preview_only: sets preview_only=True
- Inline WP connection: 3 states (url -> login -> password)
- pipeline_cancel_wp_subflow: returns to step 2
- Category step: 0/1/>1 categories
- pipeline_select_category: ownership check
- pipeline_create_category_name: inline creation + validation
- pipeline_article_cancel: clears FSM and checkpoint
- save_checkpoint / clear_checkpoint
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from keyboards.inline import menu_kb
from routers.publishing.pipeline._common import (
    ArticlePipelineFSM,
    clear_checkpoint,
    save_checkpoint,
)
from routers.publishing.pipeline.article import (
    pipeline_article_cancel,
    pipeline_article_start,
    pipeline_cancel_wp_subflow,
    pipeline_connect_wp_login,
    pipeline_connect_wp_password,
    pipeline_connect_wp_url,
    pipeline_create_category_name,
    pipeline_create_project_company,
    pipeline_create_project_name,
    pipeline_create_project_spec,
    pipeline_create_project_url,
    pipeline_preview_only,
    pipeline_projects_page,
    pipeline_select_category,
    pipeline_select_project,
    pipeline_start_connect_wp,
    pipeline_start_create_project,
)
from tests.unit.routers.conftest import make_category, make_connection, make_project

# ---------------------------------------------------------------------------
# Shared mocking helpers
# ---------------------------------------------------------------------------

_MODULE = "routers.publishing.pipeline.article"


def _patch_repos(
    *,
    projects: list | None = None,
    project: Any = None,
    created_project: Any = None,
    wp_connections: list | None = None,
    connection: Any = None,
    created_connection: Any = None,
    categories: list | None = None,
    category: Any = None,
    created_category: Any = None,
    validate_wp_error: str | None = None,
):
    """Context manager that patches repos and ConnectionService used by pipeline handlers.

    Returns (patches_dict, projects_repo_mock, conn_svc_mock, cat_repo_mock).
    """
    projects_mock = MagicMock()
    projects_mock.get_by_user = AsyncMock(return_value=projects or [])
    projects_mock.get_by_id = AsyncMock(return_value=project)
    projects_mock.create = AsyncMock(return_value=created_project)

    conn_mock = MagicMock()
    conn_mock.get_by_project_and_platform = AsyncMock(return_value=wp_connections or [])
    conn_mock.get_by_id = AsyncMock(return_value=connection)
    conn_mock.create = AsyncMock(return_value=created_connection)
    conn_mock.validate_wordpress = AsyncMock(return_value=validate_wp_error)

    cat_mock = MagicMock()
    cat_mock.get_by_project = AsyncMock(return_value=categories or [])
    cat_mock.get_by_id = AsyncMock(return_value=category)
    cat_mock.create = AsyncMock(return_value=created_category)

    patches = {
        "projects": patch(f"{_MODULE}.ProjectsRepository", return_value=projects_mock),
        "conn": patch(f"{_MODULE}.ConnectionService", return_value=conn_mock),
        "cats": patch(f"{_MODULE}.CategoriesRepository", return_value=cat_mock),
        "fsm_utils": patch(f"{_MODULE}.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None),
    }
    return patches, projects_mock, conn_mock, cat_mock


# ---------------------------------------------------------------------------
# Step 1: pipeline_article_start
# ---------------------------------------------------------------------------


class TestPipelineArticleStart:
    """pipeline_article_start: 0/1/>1 projects."""

    async def test_zero_projects_shows_no_projects_kb(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """0 projects -> shows no_projects_kb, sets FSM to select_project."""
        patches, _, _, _ = _patch_repos(projects=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_callback.message.edit_text.assert_called_once()
        call_kwargs = mock_callback.message.edit_text.call_args
        # Check that no_projects keyboard is passed
        assert call_kwargs.kwargs.get("reply_markup") is not None or (
            len(call_kwargs.args) > 1 or "reply_markup" in (call_kwargs.kwargs or {})
        )
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.select_project)

    async def test_one_project_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """1 project -> auto-select, skip to WP step (calls _show_wp_step)."""
        project = make_project(id=5, name="Solo Project")
        patches, _, _, _ = _patch_repos(projects=[project], wp_connections=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # Should save project data to state
        mock_state.update_data.assert_called_once_with(project_id=5, project_name="Solo Project")

    async def test_multiple_projects_shows_list(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """>1 projects -> show project list keyboard."""
        projects = [make_project(id=1), make_project(id=2)]
        patches, _, _, _ = _patch_repos(projects=projects)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_callback.message.edit_text.assert_called_once()
        call_args = mock_callback.message.edit_text.call_args
        # reply_markup should be set (projects list)
        assert "reply_markup" in call_args.kwargs
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.select_project)

    async def test_inaccessible_message_returns_early(
        self,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """InaccessibleMessage -> just answer callback."""
        from aiogram.types import InaccessibleMessage

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()

        patches, _, _, _ = _patch_repos()
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        callback.answer.assert_called_once()
        mock_state.set_state.assert_not_called()

    async def test_none_message_returns_early(
        self,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """callback.message is None -> just answer callback."""
        callback = MagicMock()
        callback.message = None
        callback.answer = AsyncMock()

        patches, _, _, _ = _patch_repos()
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Step 1b: pipeline_select_project
# ---------------------------------------------------------------------------


class TestPipelineSelectProject:
    """pipeline_select_project: correct project loaded, ownership check."""

    async def test_correct_project_loaded(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Valid project selection -> state updated, proceeds to WP step."""
        project = make_project(id=5, user_id=user.id, name="My Site")
        mock_callback.data = "pipeline:article:5:select"

        patches, _, _, _ = _patch_repos(project=project, wp_connections=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_project(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_state.update_data.assert_called_with(project_id=5, project_name="My Site")

    async def test_ownership_check_fails(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Project owned by different user -> alert, no state change."""
        other_user_project = make_project(id=5, user_id=999999)
        mock_callback.data = "pipeline:article:5:select"

        patches, _, _, _ = _patch_repos(project=other_user_project)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_project(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_callback.answer.assert_called_with("Проект не найден.", show_alert=True)
        mock_state.update_data.assert_not_called()

    async def test_project_not_found(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Project not in DB -> alert."""
        mock_callback.data = "pipeline:article:999:select"

        patches, _, _, _ = _patch_repos(project=None)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_project(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_callback.answer.assert_called_with("Проект не найден.", show_alert=True)

    async def test_no_callback_data_returns_early(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """callback.data is None -> early return."""
        mock_callback.data = None

        patches, _, _, _ = _patch_repos()
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_project(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Step 1c: pipeline_projects_page
# ---------------------------------------------------------------------------


class TestPipelineProjectsPage:
    """pipeline_projects_page: pagination."""

    async def test_page_2_loaded(
        self,
        mock_callback: MagicMock,
        user: Any,
    ) -> None:
        """Pagination page 2 -> edit_text with updated keyboard."""
        mock_callback.data = "page:pipeline_projects:2"
        projects = [make_project(id=i) for i in range(1, 12)]  # > PAGE_SIZE

        patches, _, _, _ = _patch_repos(projects=projects)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_projects_page(mock_callback, user, MagicMock())

        mock_callback.message.edit_text.assert_called_once()
        call_kwargs = mock_callback.message.edit_text.call_args.kwargs
        assert "reply_markup" in call_kwargs


# ---------------------------------------------------------------------------
# Step 1 sub-flow: Inline project creation
# ---------------------------------------------------------------------------


class TestPipelineStartCreateProject:
    """pipeline_start_create_project: enters inline project creation."""

    async def test_enters_create_project_name_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:create_project"
        await pipeline_start_create_project(mock_callback, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.create_project_name)

    async def test_edits_message_with_prompt(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:create_project"
        await pipeline_start_create_project(mock_callback, mock_state)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Как назовём проект" in text

    async def test_inaccessible_message_returns_early(
        self,
        mock_state: MagicMock,
    ) -> None:
        from aiogram.types import InaccessibleMessage

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()

        await pipeline_start_create_project(callback, mock_state)
        callback.answer.assert_called_once()
        mock_state.set_state.assert_not_called()


class TestPipelineCreateProjectName:
    """pipeline_create_project_name: validates 2-100 chars."""

    async def test_valid_name_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "My Project"
        await pipeline_create_project_name(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.create_project_company)
        # Should store the name
        call_kwargs = mock_state.update_data.call_args.kwargs
        assert call_kwargs["new_project_name"] == "My Project"

    async def test_too_short_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "A"
        await pipeline_create_project_name(mock_message, mock_state)
        mock_state.set_state.assert_not_called()
        assert "2 до 100" in mock_message.answer.call_args.args[0]

    async def test_too_long_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "A" * 101
        await pipeline_create_project_name(mock_message, mock_state)
        mock_state.set_state.assert_not_called()


class TestPipelineCreateProjectCompany:
    """pipeline_create_project_company: validates 2-255 chars."""

    async def test_valid_company_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "TestCo Inc"
        await pipeline_create_project_company(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.create_project_spec)
        call_kwargs = mock_state.update_data.call_args.kwargs
        assert call_kwargs["new_company_name"] == "TestCo Inc"

    async def test_too_short_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "A"
        await pipeline_create_project_company(mock_message, mock_state)
        mock_state.set_state.assert_not_called()
        assert "2 до 255" in mock_message.answer.call_args.args[0]


class TestPipelineCreateProjectSpec:
    """pipeline_create_project_spec: validates 2-500 chars."""

    async def test_valid_spec_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "web development"
        await pipeline_create_project_spec(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.create_project_url)
        call_kwargs = mock_state.update_data.call_args.kwargs
        assert call_kwargs["new_specialization"] == "web development"

    async def test_too_short_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "x"
        await pipeline_create_project_spec(mock_message, mock_state)
        mock_state.set_state.assert_not_called()
        assert "2 до 500" in mock_message.answer.call_args.args[0]


class TestPipelineCreateProjectUrl:
    """pipeline_create_project_url: creates project, proceeds to WP step."""

    async def test_valid_url_creates_project(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Valid URL -> project created, proceeds to WP step."""
        mock_message.text = "example.com"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "new_project_name": "Test",
                "new_company_name": "Co",
                "new_specialization": "SEO",
            }
        )
        created = make_project(id=42, name="Test")
        patches, proj_mock, _, _ = _patch_repos(created_project=created, wp_connections=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_create_project_url(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # Project creation called
        proj_mock.create.assert_called_once()
        # State updated with project_id
        update_calls = mock_state.update_data.call_args_list
        proj_call = next(
            (c for c in update_calls if "project_id" in (c.kwargs if c.kwargs else {})),
            None,
        )
        assert proj_call is not None
        assert proj_call.kwargs["project_id"] == 42

    async def test_skip_url_creates_project_without_url(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """'Пропустить' -> project created with website_url=None."""
        mock_message.text = "Пропустить"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "new_project_name": "Test",
                "new_company_name": "Co",
                "new_specialization": "SEO",
            }
        )
        created = make_project(id=42, name="Test")
        patches, proj_mock, _, _ = _patch_repos(created_project=created, wp_connections=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_create_project_url(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # Check that website_url is None in the create call
        create_arg = proj_mock.create.call_args.args[0]
        assert create_arg.website_url is None

    async def test_invalid_url_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Invalid URL -> error message, no project created."""
        mock_message.text = "not a url!!!"
        await pipeline_create_project_url(
            mock_message,
            mock_state,
            user,
            MagicMock(),
            MagicMock(),
            mock_redis,
        )
        assert "Некорректный URL" in mock_message.answer.call_args.args[0]

    async def test_url_gets_https_prefix(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """URL without scheme gets https:// prefix."""
        mock_message.text = "example.com"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "new_project_name": "Test",
                "new_company_name": "Co",
                "new_specialization": "SEO",
            }
        )
        created = make_project(id=42, name="Test")
        patches, proj_mock, _, _ = _patch_repos(created_project=created, wp_connections=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_create_project_url(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        create_arg = proj_mock.create.call_args.args[0]
        assert create_arg.website_url == "https://example.com"


# ---------------------------------------------------------------------------
# Step 2: WP connection selection
# ---------------------------------------------------------------------------


class TestPipelineWpStep:
    """WP step: 0/1 connections via _show_wp_step (tested through pipeline_article_start).

    Rule: 1 project = max 1 WordPress. No multi-WP branch.
    """

    async def test_zero_wp_connections_shows_no_wp_kb(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """0 WP connections -> shows no_wp_kb."""
        project = make_project(id=1)
        patches, _, _, _ = _patch_repos(projects=[project], wp_connections=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # Should set state to select_wp (from _show_wp_step)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.select_wp)

    async def test_one_wp_connection_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """1 WP connection -> auto-select, skip to category step."""
        project = make_project(id=1)
        conn = make_connection(id=5, identifier="site.com")
        patches, _, _, _ = _patch_repos(projects=[project], wp_connections=[conn], categories=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # Should update state with connection_id
        update_calls = mock_state.update_data.call_args_list
        # First call: project data, second: connection data
        conn_call = next(
            (c for c in update_calls if "connection_id" in (c.kwargs if c.kwargs else {})),
            None,
        )
        assert conn_call is not None
        assert conn_call.kwargs["connection_id"] == 5


# ---------------------------------------------------------------------------
# Step 2b: pipeline_preview_only
# ---------------------------------------------------------------------------


class TestPipelinePreviewOnly:
    """pipeline_preview_only sets preview_only=True."""

    async def test_sets_preview_only_true(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        patches, _, _, _ = _patch_repos(categories=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_preview_only(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_state.update_data.assert_called_once_with(connection_id=None, wp_identifier=None, preview_only=True)

    async def test_preview_only_proceeds_to_category_step(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """After preview_only, should proceed to category step."""
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})
        cat = make_category(id=10, project_id=5)

        patches, _, _, _ = _patch_repos(categories=[cat])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_preview_only(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # Should have called _show_category_step -> auto-select single category
        mock_state.update_data.assert_any_call(connection_id=None, wp_identifier=None, preview_only=True)


# ---------------------------------------------------------------------------
# Step 2 sub-flow: Inline WP connection
# ---------------------------------------------------------------------------


class TestPipelineStartConnectWp:
    """pipeline_start_connect_wp: enters inline WP connection."""

    async def test_enters_connect_wp_url_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:connect_wp"
        await pipeline_start_connect_wp(mock_callback, mock_state, MagicMock())
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.connect_wp_url)

    async def test_edits_message_with_url_prompt(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_callback.data = "pipeline:article:connect_wp"
        await pipeline_start_connect_wp(mock_callback, mock_state, MagicMock())
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "адрес" in text.lower()

    async def test_skips_url_when_project_has_website(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        """If project.website_url exists, skip URL step and go to login."""
        mock_callback.data = "pipeline:article:connect_wp"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1})
        project = make_project(website_url="https://example.com")
        patches, _, _, _ = _patch_repos(project=project)
        with patches["projects"]:
            await pipeline_start_connect_wp(mock_callback, mock_state, MagicMock())
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.connect_wp_login)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "example.com" in text
        assert "логин" in text.lower()

    async def test_inaccessible_message_returns_early(
        self,
        mock_state: MagicMock,
    ) -> None:
        from aiogram.types import InaccessibleMessage

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()
        await pipeline_start_connect_wp(callback, mock_state, MagicMock())
        callback.answer.assert_called_once()
        mock_state.set_state.assert_not_called()


class TestPipelineConnectWpUrl:
    """pipeline_connect_wp_url: validates URL, stores, moves to login."""

    async def test_valid_url_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "example.com"
        await pipeline_connect_wp_url(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.connect_wp_login)
        call_kwargs = mock_state.update_data.call_args.kwargs
        assert call_kwargs["wp_url"] == "https://example.com"

    async def test_url_with_https_preserved(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "https://mysite.org"
        await pipeline_connect_wp_url(mock_message, mock_state)
        call_kwargs = mock_state.update_data.call_args.kwargs
        assert call_kwargs["wp_url"] == "https://mysite.org"

    async def test_invalid_url_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "not a url"
        await pipeline_connect_wp_url(mock_message, mock_state)
        mock_state.set_state.assert_not_called()
        assert "Некорректный URL" in mock_message.answer.call_args.args[0]


class TestPipelineConnectWpLogin:
    """pipeline_connect_wp_login: validates login, stores, moves to password."""

    async def test_valid_login_proceeds(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "admin"
        await pipeline_connect_wp_login(mock_message, mock_state)
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.connect_wp_password)
        call_kwargs = mock_state.update_data.call_args.kwargs
        assert call_kwargs["wp_login"] == "admin"

    async def test_too_long_login_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "a" * 101
        await pipeline_connect_wp_login(mock_message, mock_state)
        mock_state.set_state.assert_not_called()
        assert "1 до 100" in mock_message.answer.call_args.args[0]


class TestPipelineConnectWpPassword:
    """pipeline_connect_wp_password: validates WP REST API via service, creates connection."""

    async def test_successful_connection(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Valid password + service validates OK -> connection created, proceeds to category."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 5,
                "project_name": "Test",
            }
        )
        project = make_project(id=5, user_id=user.id)
        created_conn = make_connection(id=99, identifier="example.com")

        patches, _, conn_mock, _ = _patch_repos(
            project=project,
            wp_connections=[],  # no existing WP
            created_connection=created_conn,
            categories=[],
            validate_wp_error=None,  # success
        )
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        # Connection created
        conn_mock.create.assert_called_once()
        # Deletes password message
        mock_message.delete.assert_called_once()

    async def test_auth_error_from_service(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Service returns auth error -> error message shown."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 5,
                "project_name": "Test",
            }
        )

        patches, _, _, _ = _patch_repos(
            validate_wp_error="Неверный логин или пароль. Попробуйте ещё раз.",
        )
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        error_text = mock_message.answer.call_args.args[0]
        assert "логин" in error_text.lower() or "пароль" in error_text.lower()

    async def test_server_error_from_service(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Service returns server error -> error message shown."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 5,
                "project_name": "Test",
            }
        )

        patches, _, _, _ = _patch_repos(
            validate_wp_error="Сайт вернул ошибку (500). Проверьте URL и данные.",
        )
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        error_text = mock_message.answer.call_args.args[0]
        assert "500" in error_text or "ошибк" in error_text.lower()

    async def test_timeout_error_from_service(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Service returns timeout error -> error message shown."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 5,
                "project_name": "Test",
            }
        )

        patches, _, _, _ = _patch_repos(
            validate_wp_error="Сайт не отвечает. Проверьте URL.",
        )
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        error_text = mock_message.answer.call_args.args[0]
        assert "не отвечает" in error_text.lower()

    async def test_connection_error_from_service(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Service returns connection error -> error message shown."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 5,
                "project_name": "Test",
            }
        )

        patches, _, _, _ = _patch_repos(
            validate_wp_error="Не удалось подключиться к сайту. Проверьте URL.",
        )
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        error_text = mock_message.answer.call_args.args[0]
        assert "подключиться" in error_text.lower()

    async def test_short_password_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Password < 10 chars -> error, no service call."""
        mock_message.text = "short"
        mock_message.delete = AsyncMock()

        patches, _, conn_mock, _ = _patch_repos()
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        assert "короткий" in mock_message.answer.call_args.args[0].lower()
        conn_mock.validate_wordpress.assert_not_called()

    async def test_existing_wp_auto_selects(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Already has WP connection -> auto-select existing, no new creation."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 5,
                "project_name": "Test",
            }
        )
        project = make_project(id=5, user_id=user.id)
        existing_conn = make_connection(id=77, identifier="other.com")

        patches, _, conn_mock, _ = _patch_repos(
            project=project,
            wp_connections=[existing_conn],  # already has one
            categories=[],
            validate_wp_error=None,
        )
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        # Should NOT create new connection
        conn_mock.create.assert_not_called()
        # Should auto-select existing
        update_calls = mock_state.update_data.call_args_list
        conn_call = next(
            (c for c in update_calls if "connection_id" in (c.kwargs if c.kwargs else {})),
            None,
        )
        assert conn_call is not None
        assert conn_call.kwargs["connection_id"] == 77

    async def test_stale_session_missing_keys_clears_state(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Missing FSM keys (stale session) -> clears state, shows error."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(return_value={})  # no wp_url/wp_login/project_id

        await pipeline_connect_wp_password(
            mock_message,
            mock_state,
            user,
            MagicMock(),
            mock_redis,
            MagicMock(),
        )

        mock_state.clear.assert_called_once()
        assert "устарела" in mock_message.answer.call_args.args[0].lower()

    async def test_project_not_found_clears_state(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Project not found during re-validation -> clears state."""
        mock_message.text = "xxxx xxxx xxxx xxxx xxxx xxxx"
        mock_message.delete = AsyncMock()
        mock_state.get_data = AsyncMock(
            return_value={
                "wp_url": "https://example.com",
                "wp_login": "admin",
                "project_id": 999,
                "project_name": "Ghost",
            }
        )

        patches, _, _, _ = _patch_repos(project=None, validate_wp_error=None)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_connect_wp_password(
                mock_message,
                mock_state,
                user,
                MagicMock(),
                mock_redis,
                MagicMock(),
            )

        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# Step 2c: pipeline_cancel_wp_subflow
# ---------------------------------------------------------------------------


class TestPipelineCancelWpSubflow:
    """pipeline_cancel_wp_subflow: returns to step 2 or cancels pipeline."""

    async def test_returns_to_wp_step_with_project(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """With project_id -> returns to step 2 (no_wp_kb)."""
        mock_callback.data = "pipeline:article:cancel_wp"
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        await pipeline_cancel_wp_subflow(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_state.set_state.assert_called_with(ArticlePipelineFSM.select_wp)
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "Сайт" in text

    async def test_clears_pipeline_without_project(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """No project_id -> clears state entirely."""
        mock_callback.data = "pipeline:article:cancel_wp"
        mock_state.get_data = AsyncMock(return_value={})

        await pipeline_cancel_wp_subflow(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_state.clear.assert_called_once()
        text = mock_callback.message.edit_text.call_args.args[0]
        assert "отменен" in text.lower()


# ---------------------------------------------------------------------------
# Step 3: Category selection
# ---------------------------------------------------------------------------


class TestPipelineCategoryStep:
    """Category step: 0/1/>1 categories (tested via full flow)."""

    async def test_zero_categories_prompts_create(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """0 categories -> prompt for inline creation, FSM -> create_category_name."""
        project = make_project(id=1)
        conn = make_connection(id=5)
        patches, _, _, _ = _patch_repos(projects=[project], wp_connections=[conn], categories=[])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        # After auto-selecting project and WP, 0 categories -> create_category_name state
        mock_state.set_state.assert_called_with(ArticlePipelineFSM.create_category_name)

    async def test_one_category_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """1 category -> auto-select, proceed to readiness."""
        project = make_project(id=1)
        conn = make_connection(id=5)
        cat = make_category(id=10, name="SEO Tips")
        patches, _, _, _ = _patch_repos(projects=[project], wp_connections=[conn], categories=[cat])
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        update_calls = mock_state.update_data.call_args_list
        cat_call = next(
            (c for c in update_calls if "category_id" in (c.kwargs if c.kwargs else {})),
            None,
        )
        assert cat_call is not None
        assert cat_call.kwargs["category_id"] == 10
        assert cat_call.kwargs["category_name"] == "SEO Tips"

    async def test_multiple_categories_shows_list(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """>1 categories -> show category list."""
        project = make_project(id=1)
        conn = make_connection(id=5)
        cats = [make_category(id=i) for i in range(1, 4)]
        patches, _, _, _ = _patch_repos(projects=[project], wp_connections=[conn], categories=cats)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_article_start(
                mock_callback,
                mock_state,
                user,
                MagicMock(),
                MagicMock(),
                mock_redis,
            )

        mock_state.set_state.assert_called_with(ArticlePipelineFSM.select_category)


class TestPipelineSelectCategory:
    """pipeline_select_category: correct category loaded, ownership check."""

    async def test_valid_category_selected(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Valid category -> state updated."""
        cat = make_category(id=12, project_id=5, name="Content Marketing")
        mock_callback.data = "pipeline:article:5:cat:12"
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        patches, _, _, _ = _patch_repos(category=cat)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_category(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_state.update_data.assert_called_with(category_id=12, category_name="Content Marketing", image_count=4)

    async def test_category_not_found(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Category not in DB -> alert."""
        mock_callback.data = "pipeline:article:5:cat:999"
        mock_state.get_data = AsyncMock(return_value={"project_id": 5})

        patches, _, _, _ = _patch_repos(category=None)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_category(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_callback.answer.assert_called_with("Категория не найдена.", show_alert=True)

    async def test_category_wrong_project_ownership(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Category belongs to different project -> alert."""
        cat = make_category(id=12, project_id=99)  # belongs to project 99
        mock_callback.data = "pipeline:article:5:cat:12"
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        patches, _, _, _ = _patch_repos(category=cat)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_category(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_callback.answer.assert_called_with("Категория не принадлежит проекту.", show_alert=True)


# ---------------------------------------------------------------------------
# Step 3b: pipeline_create_category_name
# ---------------------------------------------------------------------------


class TestPipelineCreateCategoryName:
    """pipeline_create_category_name: creates category, moves to readiness."""

    async def test_valid_name_creates_category(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Valid name -> category created, state updated."""
        mock_message.text = "New Category"
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})
        created_cat = make_category(id=20, project_id=5, name="New Category")

        patches, _, _, _ = _patch_repos(created_category=created_cat)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        mock_state.update_data.assert_called_with(category_id=20, category_name="New Category", image_count=4)

    async def test_empty_name_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Empty name -> error message, no state change."""
        mock_message.text = ""
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        mock_message.answer.assert_called_once()
        assert "100 символов" in mock_message.answer.call_args.args[0]
        mock_state.update_data.assert_not_called()

    async def test_too_long_name_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Name > 100 chars -> error message."""
        mock_message.text = "A" * 101
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        mock_message.answer.assert_called_once()
        assert "100 символов" in mock_message.answer.call_args.args[0]
        mock_state.update_data.assert_not_called()

    async def test_whitespace_only_name_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Whitespace-only name -> error message."""
        mock_message.text = "   "
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        mock_message.answer.assert_called_once()
        mock_state.update_data.assert_not_called()

    async def test_none_text_rejected(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """message.text is None -> error message."""
        mock_message.text = None
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        mock_message.answer.assert_called_once()
        mock_state.update_data.assert_not_called()

    async def test_creation_failure_handled(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Category creation returns None -> error message."""
        mock_message.text = "New Category"
        mock_state.get_data = AsyncMock(return_value={"project_id": 5, "project_name": "Test"})

        patches, _, _, _ = _patch_repos(created_category=None)
        with patches["projects"], patches["conn"], patches["cats"], patches["fsm_utils"]:
            await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        # Should show error message
        error_calls = [c for c in mock_message.answer.call_args_list if "Не удалось" in str(c)]
        assert len(error_calls) > 0
        mock_state.update_data.assert_not_called()


# ---------------------------------------------------------------------------
# Cancel handler
# ---------------------------------------------------------------------------


class TestPipelineArticleCancel:
    """pipeline_article_cancel: clears FSM and checkpoint."""

    async def test_clears_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Cancel -> state.clear() called."""
        await pipeline_article_cancel(mock_callback, mock_state, user, mock_redis)
        mock_state.clear.assert_called_once()

    async def test_clears_checkpoint(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Cancel -> Redis checkpoint deleted."""
        await pipeline_article_cancel(mock_callback, mock_state, user, mock_redis)
        mock_redis.delete.assert_called_once()

    async def test_edits_message(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Cancel -> message edited to 'Публикация отменена.'."""
        await pipeline_article_cancel(mock_callback, mock_state, user, mock_redis)
        mock_callback.message.edit_text.assert_called_with(
            "Публикация отменена.", reply_markup=menu_kb()
        )

    async def test_answers_callback(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """Cancel -> callback.answer() called."""
        await pipeline_article_cancel(mock_callback, mock_state, user, mock_redis)
        mock_callback.answer.assert_called_once()

    async def test_inaccessible_message_no_edit(
        self,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        """InaccessibleMessage -> no edit_text but still clears state."""
        from aiogram.types import InaccessibleMessage

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()

        await pipeline_article_cancel(callback, mock_state, user, mock_redis)

        mock_state.clear.assert_called_once()
        mock_redis.delete.assert_called_once()
        callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


class TestSaveCheckpoint:
    """save_checkpoint saves JSON to Redis with correct key."""

    async def test_saves_to_correct_key(self, mock_redis: MagicMock) -> None:
        await save_checkpoint(mock_redis, user_id=123, current_step="select_project")
        key = mock_redis.set.call_args.args[0]
        assert key == "pipeline:123:state"

    async def test_saves_step_data(self, mock_redis: MagicMock) -> None:
        import json

        await save_checkpoint(
            mock_redis,
            user_id=123,
            current_step="select_wp",
            project_id=5,
            project_name="Test",
        )
        saved_json = mock_redis.set.call_args.args[1]
        data = json.loads(saved_json)
        assert data["pipeline_type"] == "article"
        assert data["current_step"] == "select_wp"
        assert data["project_id"] == 5
        assert data["project_name"] == "Test"

    async def test_includes_step_label(self, mock_redis: MagicMock) -> None:
        import json

        await save_checkpoint(mock_redis, user_id=123, current_step="readiness_check")
        saved_json = mock_redis.set.call_args.args[1]
        data = json.loads(saved_json)
        assert data["step_label"] == "подготовка"

    async def test_sets_ttl(self, mock_redis: MagicMock) -> None:
        from cache.keys import PIPELINE_CHECKPOINT_TTL

        await save_checkpoint(mock_redis, user_id=123, current_step="select_project")
        call_kwargs = mock_redis.set.call_args.kwargs
        assert call_kwargs.get("ex") == PIPELINE_CHECKPOINT_TTL


class TestClearCheckpoint:
    """clear_checkpoint deletes Redis key."""

    async def test_deletes_correct_key(self, mock_redis: MagicMock) -> None:
        await clear_checkpoint(mock_redis, user_id=456)
        mock_redis.delete.assert_called_once_with("pipeline:456:state")
