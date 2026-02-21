"""Tests for pipeline resume/restart handlers in routers/start.py (F5.5, E49).

Covers:
- pipeline:resume — restore FSM from checkpoint, route to correct screen
- pipeline:restart — clear checkpoint, show dashboard
- _route_to_step — routing to various step screens
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from db.models import ArticlePreview
from routers.publishing.pipeline._common import ArticlePipelineFSM
from routers.start import (
    _route_to_step,
    pipeline_restart,
    pipeline_resume,
)
from tests.unit.routers.conftest import make_category, make_project, make_user

_MODULE = "routers.start"


def _make_preview(**overrides: Any) -> ArticlePreview:
    defaults: dict[str, Any] = {
        "id": 99,
        "user_id": 123456,
        "project_id": 1,
        "category_id": 10,
        "connection_id": 5,
        "telegraph_url": "https://telegra.ph/test",
        "title": "Test Article",
        "keyword": "test keyword",
        "word_count": 2000,
        "images_count": 4,
        "tokens_charged": 320,
        "regeneration_count": 0,
        "status": "draft",
    }
    defaults.update(overrides)
    return ArticlePreview(**defaults)


# ---------------------------------------------------------------------------
# pipeline:resume
# ---------------------------------------------------------------------------


async def test_resume_no_checkpoint_shows_alert(
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Resume with no checkpoint shows alert."""
    user = make_user()
    mock_redis.get = AsyncMock(return_value=None)

    await pipeline_resume(mock_callback, mock_state, user, MagicMock(), mock_redis)

    mock_callback.answer.assert_called_once_with("Нет активного pipeline.", show_alert=True)


async def test_resume_invalid_json_shows_alert(
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Resume with corrupted JSON shows alert."""
    user = make_user()
    mock_redis.get = AsyncMock(return_value="not-json{{{")

    await pipeline_resume(mock_callback, mock_state, user, MagicMock(), mock_redis)

    mock_callback.answer.assert_called_once_with("Нет активного pipeline.", show_alert=True)


@patch(f"{_MODULE}.CategoriesRepository")
@patch(f"{_MODULE}._route_to_step", new_callable=AsyncMock)
async def test_resume_valid_checkpoint(
    mock_route: AsyncMock,
    _mock_cats_cls: MagicMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Resume with valid checkpoint restores FSM data and routes to step."""
    user = make_user()
    checkpoint = {
        "pipeline_type": "article",
        "current_step": "preview",
        "project_id": 1,
        "project_name": "Test",
        "connection_id": 5,
        "category_id": 10,
        "preview_id": 99,
    }
    mock_redis.get = AsyncMock(return_value=json.dumps(checkpoint))
    _mock_cats_cls.return_value.get_by_id = AsyncMock(
        return_value=make_category(id=10, name="Test Cat"),
    )

    await pipeline_resume(mock_callback, mock_state, user, MagicMock(), mock_redis)

    mock_state.update_data.assert_called_once_with(
        project_id=1,
        project_name="Test",
        connection_id=5,
        category_id=10,
        category_name="Test Cat",
        preview_id=99,
    )
    mock_route.assert_called_once()
    call_kwargs = mock_route.call_args[1]
    assert call_kwargs["step"] == "preview"
    assert call_kwargs["preview_id"] == 99


async def test_resume_inaccessible_message(
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Resume with inaccessible message returns early."""
    from aiogram.types import InaccessibleMessage

    user = make_user()
    callback = MagicMock()
    callback.message = MagicMock(spec=InaccessibleMessage)
    callback.answer = AsyncMock()

    await pipeline_resume(callback, mock_state, user, MagicMock(), mock_redis)

    callback.answer.assert_called_once()
    mock_state.update_data.assert_not_called()


# ---------------------------------------------------------------------------
# pipeline:restart
# ---------------------------------------------------------------------------


@patch(f"{_MODULE}._build_dashboard", new_callable=AsyncMock)
async def test_restart_clears_checkpoint_and_fsm(
    mock_dashboard: AsyncMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Restart clears checkpoint, FSM, and shows dashboard."""
    user = make_user()
    mock_dashboard.return_value = ("Dashboard", MagicMock())

    await pipeline_restart(mock_callback, mock_state, user, False, MagicMock(), mock_redis)

    mock_redis.delete.assert_called_once()
    mock_state.clear.assert_called_once()
    mock_callback.message.edit_text.assert_called_once()
    mock_callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# _route_to_step — various steps
# ---------------------------------------------------------------------------


@patch(f"{_MODULE}.ProjectsRepository")
async def test_route_to_step_select_project(
    mock_repo_cls: MagicMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to select_project shows project list."""
    user = make_user()
    projects = [make_project(), make_project(id=2, name="P2")]
    mock_repo_cls.return_value.get_by_user = AsyncMock(return_value=projects)

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="select_project",
        project_id=None,
        project_name="",
        category_id=None,
        connection_id=None,
        preview_id=None,
    )

    mock_callback.message.edit_text.assert_called_once()
    text = mock_callback.message.edit_text.call_args[0][0]
    assert "Проект" in text
    mock_state.set_state.assert_called_once_with(ArticlePipelineFSM.select_project)


@patch(f"{_MODULE}.CategoriesRepository")
async def test_route_to_step_select_category_multi(
    mock_repo_cls: MagicMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to select_category with multiple categories shows list."""
    user = make_user()
    cats = [make_category(), make_category(id=11, name="Cat 2")]
    mock_repo_cls.return_value.get_by_project = AsyncMock(return_value=cats)

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="select_category",
        project_id=1,
        project_name="Test",
        category_id=None,
        connection_id=None,
        preview_id=None,
    )

    mock_callback.message.edit_text.assert_called_once()
    text = mock_callback.message.edit_text.call_args[0][0]
    assert "Тема" in text
    mock_state.set_state.assert_called_once_with(ArticlePipelineFSM.select_category)


async def test_route_to_step_select_wp(
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to select_wp shows WP connection screen."""
    user = make_user()

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="select_wp",
        project_id=1,
        project_name="Test",
        category_id=None,
        connection_id=None,
        preview_id=None,
    )

    mock_callback.message.edit_text.assert_called_once()
    text = mock_callback.message.edit_text.call_args[0][0]
    assert "WordPress" in text
    mock_state.set_state.assert_called_once_with(ArticlePipelineFSM.select_wp)


@patch(f"{_MODULE}.PreviewsRepository")
async def test_route_to_step_preview_with_connection(
    mock_repo_cls: MagicMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to preview step loads preview and shows publish button."""
    user = make_user()
    preview = _make_preview()
    mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="preview",
        project_id=1,
        project_name="Test",
        category_id=10,
        connection_id=5,
        preview_id=99,
    )

    mock_callback.message.edit_text.assert_called_once()
    text = mock_callback.message.edit_text.call_args[0][0]
    assert "Test Article" in text
    mock_state.set_state.assert_called_once_with(ArticlePipelineFSM.preview)


@patch(f"{_MODULE}.PreviewsRepository")
async def test_route_to_step_preview_expired(
    mock_repo_cls: MagicMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to preview with expired preview clears checkpoint."""
    user = make_user()
    preview = _make_preview(status="expired")
    mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="preview",
        project_id=1,
        project_name="Test",
        category_id=10,
        connection_id=5,
        preview_id=99,
    )

    mock_callback.message.edit_text.assert_called_once()
    assert "устарело" in mock_callback.message.edit_text.call_args[0][0]
    mock_redis.delete.assert_called_once()


@patch(f"{_MODULE}.PreviewsRepository")
async def test_route_to_step_preview_no_connection(
    mock_repo_cls: MagicMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to preview without connection_id shows preview without publish."""
    user = make_user()
    preview = _make_preview()
    mock_repo_cls.return_value.get_by_id = AsyncMock(return_value=preview)

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="preview",
        project_id=1,
        project_name="Test",
        category_id=10,
        connection_id=None,
        preview_id=99,
    )

    mock_callback.message.edit_text.assert_called_once()
    kb = mock_callback.message.edit_text.call_args[1]["reply_markup"]
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row if btn.callback_data]
    # No "publish" button when connection_id is None
    assert "pipeline:article:publish" not in callbacks


@patch("routers.publishing.pipeline.readiness.show_readiness_check", new_callable=AsyncMock)
async def test_route_to_step_readiness(
    mock_readiness: AsyncMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to readiness_check calls show_readiness_check."""
    user = make_user()

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="readiness_check",
        project_id=1,
        project_name="Test",
        category_id=10,
        connection_id=5,
        preview_id=None,
    )

    mock_readiness.assert_called_once()


@patch("routers.publishing.pipeline.readiness.show_readiness_check", new_callable=AsyncMock)
async def test_route_to_step_confirm_cost_shows_readiness(
    mock_readiness: AsyncMock,
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Route to confirm_cost goes back to readiness (simplest safe resume)."""
    user = make_user()

    await _route_to_step(
        mock_callback,
        mock_state,
        user,
        MagicMock(),
        mock_redis,
        step="confirm_cost",
        project_id=1,
        project_name="Test",
        category_id=10,
        connection_id=5,
        preview_id=None,
    )

    mock_readiness.assert_called_once()
