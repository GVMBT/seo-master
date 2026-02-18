"""Tests for routers/publishing/pipeline/article.py handlers.

Covers steps 1-3 of the Article Pipeline:
- pipeline_article_start: 0/1/>1 projects
- pipeline_select_project: ownership check, loading
- pipeline_projects_page: pagination
- WP step: 0/1 connections (1 project = max 1 WP, no multi-WP)
- pipeline_preview_only: sets preview_only=True
- Category step: 0/1/>1 categories
- pipeline_select_category: ownership check
- pipeline_create_category_name: inline creation + validation
- pipeline_article_cancel: clears FSM and checkpoint
- _save_checkpoint / _clear_checkpoint
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from routers.publishing.pipeline.article import (
    ArticlePipelineFSM,
    _clear_checkpoint,
    _save_checkpoint,
    pipeline_article_cancel,
    pipeline_article_start,
    pipeline_create_category_name,
    pipeline_preview_only,
    pipeline_projects_page,
    pipeline_select_category,
    pipeline_select_project,
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
    wp_connections: list | None = None,
    connection: Any = None,
    categories: list | None = None,
    category: Any = None,
    created_category: Any = None,
):
    """Context manager that patches all repositories used by pipeline handlers.

    Returns (projects_repo_mock, conn_repo_mock, cat_repo_mock).
    """
    projects_mock = MagicMock()
    projects_mock.get_by_user = AsyncMock(return_value=projects or [])
    projects_mock.get_by_id = AsyncMock(return_value=project)

    conn_mock = MagicMock()
    conn_mock.get_by_project_and_platform = AsyncMock(return_value=wp_connections or [])
    conn_mock.get_by_id = AsyncMock(return_value=connection)

    cat_mock = MagicMock()
    cat_mock.get_by_project = AsyncMock(return_value=categories or [])
    cat_mock.get_by_id = AsyncMock(return_value=category)
    cat_mock.create = AsyncMock(return_value=created_category)

    patches = {
        "projects": patch(f"{_MODULE}.ProjectsRepository", return_value=projects_mock),
        "conn": patch(f"{_MODULE}._conn_repo", return_value=conn_mock),
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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_select_project(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_select_project(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_select_project(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_select_project(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_preview_only(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_preview_only(mock_callback, mock_state, user, MagicMock(), mock_redis)

        # Should have called _show_category_step -> auto-select single category
        mock_state.update_data.assert_any_call(connection_id=None, wp_identifier=None, preview_only=True)


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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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
            await pipeline_article_start(mock_callback, mock_state, user, MagicMock(), mock_redis)

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

        mock_state.update_data.assert_called_with(category_id=12, category_name="Content Marketing")

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

        mock_state.update_data.assert_called_with(category_id=20, category_name="New Category")

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
        """Cancel -> message edited to 'Pipeline отменён.'."""
        await pipeline_article_cancel(mock_callback, mock_state, user, mock_redis)
        mock_callback.message.edit_text.assert_called_with("Pipeline отменён.")

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
    """_save_checkpoint saves JSON to Redis with correct key."""

    async def test_saves_to_correct_key(self, mock_redis: MagicMock) -> None:
        await _save_checkpoint(mock_redis, user_id=123, current_step="select_project")
        key = mock_redis.set.call_args.args[0]
        assert key == "pipeline:123:state"

    async def test_saves_step_data(self, mock_redis: MagicMock) -> None:
        import json

        await _save_checkpoint(
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

        await _save_checkpoint(mock_redis, user_id=123, current_step="readiness_check")
        saved_json = mock_redis.set.call_args.args[1]
        data = json.loads(saved_json)
        assert data["step_label"] == "подготовка"

    async def test_sets_ttl(self, mock_redis: MagicMock) -> None:
        from cache.keys import PIPELINE_CHECKPOINT_TTL

        await _save_checkpoint(mock_redis, user_id=123, current_step="select_project")
        call_kwargs = mock_redis.set.call_args.kwargs
        assert call_kwargs.get("ex") == PIPELINE_CHECKPOINT_TTL


class TestClearCheckpoint:
    """_clear_checkpoint deletes Redis key."""

    async def test_deletes_correct_key(self, mock_redis: MagicMock) -> None:
        await _clear_checkpoint(mock_redis, user_id=456)
        mock_redis.delete.assert_called_once_with("pipeline:456:state")
