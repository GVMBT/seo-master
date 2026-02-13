"""Tests for routers/publishing/scheduler.py — FSM flow, navigation, management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from db.models import Category, PlatformConnection, PlatformSchedule, Project, User
from routers.publishing.scheduler import (
    cb_schedule_delete,
    cb_schedule_toggle,
    cb_schedule_toggle_day,
    cb_scheduler_categories,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _user() -> User:
    return User(id=1)


def _project() -> Project:
    return Project(id=1, user_id=1, name="Test", company_name="Co", specialization="SEO")


def _category() -> Category:
    return Category(id=10, project_id=1, name="Test Category")


def _connection() -> PlatformConnection:
    return PlatformConnection(
        id=5, project_id=1, platform_type="wordpress",
        status="active", credentials={}, identifier="test.com",
    )


def _schedule(**overrides) -> PlatformSchedule:
    defaults = {
        "id": 1, "category_id": 10, "platform_type": "wordpress",
        "connection_id": 5, "enabled": True, "status": "active",
        "qstash_schedule_ids": ["qs_1"],
    }
    defaults.update(overrides)
    return PlatformSchedule(**defaults)


def _callback(data: str) -> MagicMock:
    """Create mock CallbackQuery."""
    cb = MagicMock()
    cb.data = data
    cb.from_user = MagicMock(id=1)
    cb.answer = AsyncMock()
    msg = MagicMock()
    msg.edit_text = AsyncMock()
    msg.edit_reply_markup = AsyncMock()
    msg.answer = AsyncMock()
    cb.message = msg
    return cb


def _state(**data) -> MagicMock:
    """Create mock FSMContext."""
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_scheduler_categories_shows_list(
    mock_guard: MagicMock, mock_proj_cls: MagicMock, mock_cat_cls: MagicMock,
) -> None:
    """project:X:scheduler shows category list."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[_category()])

    cb = _callback("project:1:scheduler")
    await cb_scheduler_categories(cb, _user(), MagicMock())

    mock_guard.return_value.edit_text.assert_called_once()


@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_scheduler_no_categories(
    mock_guard: MagicMock, mock_proj_cls: MagicMock, mock_cat_cls: MagicMock,
) -> None:
    """No categories: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[])

    cb = _callback("project:1:scheduler")
    await cb_scheduler_categories(cb, _user(), MagicMock())

    cb.answer.assert_called_with("Сначала добавьте категорию.", show_alert=True)


# ---------------------------------------------------------------------------
# FSM: day toggle
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_toggle_day_adds(mock_guard: MagicMock) -> None:
    """Toggling a day adds it to selection."""
    mock_guard.return_value = MagicMock(edit_reply_markup=AsyncMock())
    state = _state(selected_days=[])

    cb = _callback("sched:day:mon")
    await cb_schedule_toggle_day(cb, state)

    state.update_data.assert_called_once()
    call_kwargs = state.update_data.call_args[1]
    assert "mon" in call_kwargs["selected_days"]


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_toggle_day_removes(mock_guard: MagicMock) -> None:
    """Toggling an already-selected day removes it."""
    mock_guard.return_value = MagicMock(edit_reply_markup=AsyncMock())
    state = _state(selected_days=["mon", "wed"])

    cb = _callback("sched:day:mon")
    await cb_schedule_toggle_day(cb, state)

    state.update_data.assert_called_once()
    call_kwargs = state.update_data.call_args[1]
    assert "mon" not in call_kwargs["selected_days"]
    assert "wed" in call_kwargs["selected_days"]


# ---------------------------------------------------------------------------
# Schedule toggle
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.get_settings")
@patch("routers.publishing.scheduler.CredentialManager")
@patch("routers.publishing.scheduler.ConnectionsRepository")
@patch("routers.publishing.scheduler.SchedulesRepository")
@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_schedule_toggle(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
    mock_sched_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Toggle schedule calls scheduler_service.toggle_schedule."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_sched_cls.return_value.get_by_id = AsyncMock(return_value=_schedule(enabled=True))
    mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_project = AsyncMock(return_value=[])
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="k")))

    sched_svc = MagicMock()
    sched_svc.toggle_schedule = AsyncMock(return_value=_schedule(enabled=False))

    cb = _callback("schedule:1:toggle")
    await cb_schedule_toggle(cb, _user(), MagicMock(), sched_svc)

    sched_svc.toggle_schedule.assert_called_once()


# ---------------------------------------------------------------------------
# Schedule delete
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.get_settings")
@patch("routers.publishing.scheduler.CredentialManager")
@patch("routers.publishing.scheduler.ConnectionsRepository")
@patch("routers.publishing.scheduler.SchedulesRepository")
@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_schedule_delete(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
    mock_sched_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """Delete schedule calls scheduler_service.delete_schedule."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_sched_cls.return_value.get_by_id = AsyncMock(return_value=_schedule())
    mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_conn_cls.return_value.get_by_project = AsyncMock(return_value=[])
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="k")))

    sched_svc = MagicMock()
    sched_svc.delete_schedule = AsyncMock(return_value=True)

    cb = _callback("schedule:1:delete")
    await cb_schedule_delete(cb, _user(), MagicMock(), sched_svc)

    sched_svc.delete_schedule.assert_called_once_with(1)
    cb.answer.assert_any_call("Расписание удалено.")
