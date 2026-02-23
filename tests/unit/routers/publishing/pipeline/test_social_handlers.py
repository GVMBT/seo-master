"""Tests for routers/publishing/pipeline/social/social.py handlers.

Covers steps 1 and 3 of the Social Pipeline (F6.1):
- pipeline_social_start: 0/1/>1 projects
- pipeline_select_project: ownership check
- pipeline_projects_page: pagination
- Inline project creation: 4 states (name -> company -> spec -> url)
- Category step (via connection stub): 0/1/>1 categories
- pipeline_select_category: ownership check
- pipeline_create_category_name: inline creation + validation
- pipeline_social_cancel: clears FSM and checkpoint
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from routers.publishing.pipeline._common import SocialPipelineFSM, save_checkpoint
from routers.publishing.pipeline.social.social import (
    pipeline_create_category_name,
    pipeline_create_project_company,
    pipeline_create_project_name,
    pipeline_create_project_spec,
    pipeline_create_project_url,
    pipeline_select_category,
    pipeline_select_project,
    pipeline_social_cancel,
    pipeline_social_start,
    pipeline_start_create_project,
)
from tests.unit.routers.conftest import make_category, make_project

# ---------------------------------------------------------------------------
# Shared mocking helpers
# ---------------------------------------------------------------------------

_MODULE = "routers.publishing.pipeline.social.social"


def _patch_repos(
    *,
    projects: list | None = None,
    project: Any = None,
    created_project: Any = None,
    categories: list | None = None,
    category: Any = None,
    created_category: Any = None,
):
    """Patch repos used by social pipeline handlers."""
    projects_mock = MagicMock()
    projects_mock.get_by_user = AsyncMock(return_value=projects or [])
    projects_mock.get_by_id = AsyncMock(return_value=project)
    projects_mock.create = AsyncMock(return_value=created_project)

    cat_mock = MagicMock()
    cat_mock.get_by_project = AsyncMock(return_value=categories or [])
    cat_mock.get_by_id = AsyncMock(return_value=category)
    cat_mock.create = AsyncMock(return_value=created_category)

    patches = {
        "projects": patch(f"{_MODULE}.ProjectsRepository", return_value=projects_mock),
        "cats": patch(f"{_MODULE}.CategoriesRepository", return_value=cat_mock),
        "fsm_utils": patch(
            f"{_MODULE}.ensure_no_active_fsm",
            new_callable=AsyncMock,
            return_value=None,
        ),
        # F6.2: connection step replaced stubs, needs mock for tests focused on step 1/3
        "conn_step": patch(
            f"{_MODULE}._show_connection_step",
            new_callable=AsyncMock,
        ),
        "conn_step_msg": patch(
            f"{_MODULE}._show_connection_step_msg",
            new_callable=AsyncMock,
        ),
    }
    return patches, projects_mock, cat_mock


# ---------------------------------------------------------------------------
# Step 1: pipeline_social_start
# ---------------------------------------------------------------------------


class TestPipelineSocialStart:
    """pipeline_social_start: 0/1/>1 projects."""

    async def test_zero_projects_shows_no_projects_kb(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        patches, _, _ = _patch_repos(projects=[])
        with patches["projects"], patches["cats"], patches["fsm_utils"]:
            await pipeline_social_start(mock_callback, mock_state, user, MagicMock(), mock_redis, MagicMock())

        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.select_project)
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Пост (1/5)" in text

    async def test_one_project_auto_selects(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        p = make_project()
        patches, _, _cat_mock = _patch_repos(projects=[p], categories=[make_category()])
        with patches["projects"], patches["cats"], patches["fsm_utils"], patches["conn_step"]:
            await pipeline_social_start(mock_callback, mock_state, user, MagicMock(), mock_redis, MagicMock())

        mock_state.update_data.assert_any_await(project_id=p.id, project_name=p.name)

    async def test_multiple_projects_shows_list(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        p1 = make_project(id=1, name="P1")
        p2 = make_project(id=2, name="P2")
        patches, _, _ = _patch_repos(projects=[p1, p2])
        with patches["projects"], patches["cats"], patches["fsm_utils"]:
            await pipeline_social_start(mock_callback, mock_state, user, MagicMock(), mock_redis, MagicMock())

        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.select_project)
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Для какого проекта" in text

    async def test_inaccessible_message_returns_early(
        self,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        from aiogram.types import InaccessibleMessage

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()
        patches, _, _ = _patch_repos()
        with patches["projects"], patches["cats"], patches["fsm_utils"]:
            await pipeline_social_start(callback, mock_state, user, MagicMock(), mock_redis, MagicMock())

        mock_state.set_state.assert_not_awaited()


# ---------------------------------------------------------------------------
# Step 1: pipeline_select_project
# ---------------------------------------------------------------------------


class TestPipelineSelectProject:
    async def test_valid_project_selected(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        p = make_project(user_id=user.id)
        mock_callback.data = f"pipeline:social:{p.id}:select"
        patches, _, _cat_mock = _patch_repos(project=p, categories=[make_category()])
        with patches["projects"], patches["cats"], patches["fsm_utils"], patches["conn_step"]:
            await pipeline_select_project(mock_callback, mock_state, user, MagicMock(), mock_redis, MagicMock())

        mock_state.update_data.assert_any_await(project_id=p.id, project_name=p.name)

    async def test_wrong_owner_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        p = make_project(user_id=999999)
        mock_callback.data = f"pipeline:social:{p.id}:select"
        patches, _, _ = _patch_repos(project=p)
        with patches["projects"], patches["cats"], patches["fsm_utils"]:
            await pipeline_select_project(mock_callback, mock_state, user, MagicMock(), mock_redis, MagicMock())

        mock_callback.answer.assert_awaited_once()
        assert "не найден" in mock_callback.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# Step 1 sub-flow: Inline project creation
# ---------------------------------------------------------------------------


class TestInlineProjectCreation:
    async def test_start_create_sets_state(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        await pipeline_start_create_project(mock_callback, mock_state)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.create_project_name)

    async def test_name_too_short(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "X"
        await pipeline_create_project_name(mock_message, mock_state)
        mock_message.answer.assert_awaited_once()
        assert "от 2 до 100" in mock_message.answer.call_args[0][0]

    async def test_name_valid(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "My Project"
        await pipeline_create_project_name(mock_message, mock_state)
        mock_state.update_data.assert_awaited()
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.create_project_company)

    async def test_company_valid(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "TestCo Inc"
        await pipeline_create_project_company(mock_message, mock_state)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.create_project_spec)

    async def test_spec_valid(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_message.text = "SEO services"
        await pipeline_create_project_spec(mock_message, mock_state)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.create_project_url)

    async def test_url_skip_creates_project(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "Пропустить"
        p = make_project()
        mock_state.get_data = AsyncMock(
            return_value={
                "new_project_name": "Test",
                "new_company_name": "Co",
                "new_specialization": "SEO",
            }
        )
        patches, _, _cat_mock = _patch_repos(created_project=p, categories=[make_category()])
        with patches["projects"], patches["cats"], patches["conn_step_msg"]:
            await pipeline_create_project_url(mock_message, mock_state, user, MagicMock(), mock_redis, MagicMock())

        # Should have created the project and updated state
        mock_state.update_data.assert_any_await(project_id=p.id, project_name=p.name)


# ---------------------------------------------------------------------------
# Step 3: Category selection
# ---------------------------------------------------------------------------


class TestCategorySelection:
    async def test_select_valid_category(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        cat = make_category(project_id=1)
        mock_callback.data = f"pipeline:social:1:cat:{cat.id}"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "Test"})
        patches, _, _cat_mock = _patch_repos(category=cat)
        with patches["projects"], patches["cats"]:
            await pipeline_select_category(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_state.update_data.assert_any_await(category_id=cat.id, category_name=cat.name)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.readiness_check)

    async def test_category_wrong_project_shows_alert(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        cat = make_category(project_id=999)
        mock_callback.data = f"pipeline:social:1:cat:{cat.id}"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "Test"})
        patches, _, _ = _patch_repos(category=cat)
        with patches["projects"], patches["cats"]:
            await pipeline_select_category(mock_callback, mock_state, user, MagicMock(), mock_redis)

        mock_callback.answer.assert_awaited_once()
        assert "не принадлежит" in mock_callback.answer.call_args[0][0]

    async def test_inline_category_creation(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        cat = make_category()
        mock_message.text = "New Topic"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "Test"})
        patches, _, _ = _patch_repos(created_category=cat)
        with patches["projects"], patches["cats"]:
            await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        mock_state.update_data.assert_any_await(category_id=cat.id, category_name=cat.name)
        mock_state.set_state.assert_awaited_once_with(SocialPipelineFSM.readiness_check)

    async def test_inline_category_too_short(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        mock_message.text = "X"
        mock_state.get_data = AsyncMock(return_value={"project_id": 1, "project_name": "Test"})
        await pipeline_create_category_name(mock_message, mock_state, user, MagicMock(), mock_redis)

        # Should ask for valid name, NOT set state
        mock_state.set_state.assert_not_awaited()
        mock_message.answer.assert_awaited_once()
        assert "от 2 до 100" in mock_message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------------


class TestPipelineSocialCancel:
    async def test_cancel_clears_fsm_and_checkpoint(
        self,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        mock_redis: MagicMock,
        user: Any,
    ) -> None:
        await pipeline_social_cancel(mock_callback, mock_state, user, mock_redis)

        mock_state.clear.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        assert "отменён" in mock_callback.message.edit_text.call_args[0][0]


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------


class TestSocialCheckpoint:
    async def test_save_checkpoint_social(self, mock_redis: MagicMock) -> None:
        await save_checkpoint(
            mock_redis,
            user_id=123,
            current_step="select_project",
            pipeline_type="social",
        )

        mock_redis.set.assert_awaited_once()
        args = mock_redis.set.call_args
        key = args[0][0]
        import json

        data = json.loads(args[0][1])
        assert "pipeline:123:state" in key
        assert data["pipeline_type"] == "social"
        assert data["current_step"] == "select_project"
        assert data["step_label"] == "выбор проекта"

    async def test_social_step_labels(self, mock_redis: MagicMock) -> None:
        await save_checkpoint(
            mock_redis,
            user_id=123,
            current_step="review",
            pipeline_type="social",
        )
        import json

        data = json.loads(mock_redis.set.call_args[0][1])
        assert data["step_label"] == "ревью"
