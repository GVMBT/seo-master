"""Tests for routers/publishing/scheduler.py — FSM flow, navigation, management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from db.models import Category, PlatformConnection, PlatformSchedule, Project, User
from routers.publishing.scheduler import (
    cb_schedule_count,
    cb_schedule_days_done,
    cb_schedule_delete,
    cb_schedule_start,
    cb_schedule_times_done,
    cb_schedule_toggle,
    cb_schedule_toggle_day,
    cb_schedule_toggle_time,
    cb_scheduler_categories,
    cb_scheduler_platforms,
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
        id=5,
        project_id=1,
        platform_type="wordpress",
        status="active",
        credentials={},
        identifier="test.com",
    )


def _schedule(**overrides) -> PlatformSchedule:
    defaults = {
        "id": 1,
        "category_id": 10,
        "platform_type": "wordpress",
        "connection_id": 5,
        "enabled": True,
        "status": "active",
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
# Navigation: cb_scheduler_categories
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_scheduler_categories_shows_list(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
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
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
) -> None:
    """No categories: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[])

    cb = _callback("project:1:scheduler")
    await cb_scheduler_categories(cb, _user(), MagicMock())

    cb.answer.assert_called_with("Сначала добавьте категорию.", show_alert=True)


# ---------------------------------------------------------------------------
# Navigation: cb_scheduler_platforms
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.SchedulesRepository")
@patch("routers.publishing.scheduler.get_settings")
@patch("routers.publishing.scheduler.CredentialManager")
@patch("routers.publishing.scheduler.ConnectionsRepository")
@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_scheduler_platforms_shows_list(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_sched_cls: MagicMock,
) -> None:
    """sched:cat:X shows platform list with category name."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="k")))
    mock_conn_cls.return_value.get_by_project = AsyncMock(return_value=[_connection()])
    mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])

    cb = _callback("sched:cat:10")
    await cb_scheduler_platforms(cb, _user(), MagicMock())

    call_args = mock_guard.return_value.edit_text.call_args
    assert "Test Category" in call_args[0][0]


@patch("routers.publishing.scheduler.SchedulesRepository")
@patch("routers.publishing.scheduler.get_settings")
@patch("routers.publishing.scheduler.CredentialManager")
@patch("routers.publishing.scheduler.ConnectionsRepository")
@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_scheduler_platforms_no_connections(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_sched_cls: MagicMock,
) -> None:
    """No platform connections: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="k")))
    mock_conn_cls.return_value.get_by_project = AsyncMock(return_value=[])
    mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])

    cb = _callback("sched:cat:10")
    await cb_scheduler_platforms(cb, _user(), MagicMock())

    cb.answer.assert_called_with("Сначала подключите платформу.", show_alert=True)


# ---------------------------------------------------------------------------
# FSM: cb_schedule_start
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.ensure_no_active_fsm", new_callable=AsyncMock, return_value=None)
@patch("routers.publishing.scheduler.get_settings")
@patch("routers.publishing.scheduler.CredentialManager")
@patch("routers.publishing.scheduler.ConnectionsRepository")
@patch("routers.publishing.scheduler.CategoriesRepository")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_schedule_start_enters_select_days(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cat_cls: MagicMock,
    mock_conn_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_settings: MagicMock,
    mock_ensure: MagicMock,
) -> None:
    """Start FSM: transitions to select_days, shows step 1/3."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_category())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())
    mock_settings.return_value = MagicMock(encryption_key=MagicMock(get_secret_value=MagicMock(return_value="k")))
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=_connection())

    state = _state()
    cb = _callback("sched:cat:10:plt:5")
    await cb_schedule_start(cb, state, _user(), MagicMock())

    from routers.publishing.scheduler import ScheduleSetupFSM

    state.set_state.assert_called_with(ScheduleSetupFSM.select_days)
    call_args = mock_guard.return_value.edit_text.call_args
    assert "1/3" in call_args[0][0]


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
# FSM: cb_schedule_days_done
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_days_done_empty_selection_alert(mock_guard: MagicMock) -> None:
    """No days selected: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    state = _state(selected_days=[])

    cb = _callback("sched:days:done")
    await cb_schedule_days_done(cb, state)

    cb.answer.assert_called_with("Выберите хотя бы один день.", show_alert=True)


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_days_done_transitions_to_count(mock_guard: MagicMock) -> None:
    """Valid days: transitions to select_count, shows step 2/3."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    state = _state(selected_days=["mon", "fri"])

    cb = _callback("sched:days:done")
    await cb_schedule_days_done(cb, state)

    from routers.publishing.scheduler import ScheduleSetupFSM

    state.set_state.assert_called_with(ScheduleSetupFSM.select_count)
    call_args = mock_guard.return_value.edit_text.call_args
    assert "2/3" in call_args[0][0]


# ---------------------------------------------------------------------------
# FSM: cb_schedule_count
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_count_transitions_to_times(mock_guard: MagicMock) -> None:
    """Select count: transitions to select_times, shows step 3/3."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    state = _state()

    cb = _callback("sched:count:2")
    await cb_schedule_count(cb, state)

    from routers.publishing.scheduler import ScheduleSetupFSM

    state.set_state.assert_called_with(ScheduleSetupFSM.select_times)
    state.update_data.assert_called_once()
    call_kwargs = state.update_data.call_args[1]
    assert call_kwargs["posts_per_day"] == 2
    call_args = mock_guard.return_value.edit_text.call_args
    assert "3/3" in call_args[0][0]


# ---------------------------------------------------------------------------
# FSM: cb_schedule_toggle_time
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_time_toggle_adds_slot(mock_guard: MagicMock) -> None:
    """Toggle time: adds slot to selection."""
    mock_guard.return_value = MagicMock(edit_reply_markup=AsyncMock())
    state = _state(selected_times=[], posts_per_day=2)

    cb = _callback("sched:time:09:00")
    await cb_schedule_toggle_time(cb, state)

    state.update_data.assert_called_once()
    call_kwargs = state.update_data.call_args[1]
    assert "09:00" in call_kwargs["selected_times"]


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_time_toggle_removes_slot(mock_guard: MagicMock) -> None:
    """Toggle time: removes already-selected slot."""
    mock_guard.return_value = MagicMock(edit_reply_markup=AsyncMock())
    state = _state(selected_times=["09:00", "15:00"], posts_per_day=2)

    cb = _callback("sched:time:09:00")
    await cb_schedule_toggle_time(cb, state)

    state.update_data.assert_called_once()
    call_kwargs = state.update_data.call_args[1]
    assert "09:00" not in call_kwargs["selected_times"]
    assert "15:00" in call_kwargs["selected_times"]


@patch("routers.publishing.scheduler.guard_callback_message")
async def test_time_toggle_max_reached_alert(mock_guard: MagicMock) -> None:
    """Toggle time: max slots reached shows alert."""
    mock_guard.return_value = MagicMock(edit_reply_markup=AsyncMock())
    state = _state(selected_times=["09:00"], posts_per_day=1)

    cb = _callback("sched:time:15:00")
    await cb_schedule_toggle_time(cb, state)

    cb.answer.assert_called_with("Максимум 1 слотов.", show_alert=True)
    state.update_data.assert_not_called()


# ---------------------------------------------------------------------------
# FSM: cb_schedule_times_done
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.SchedulerService")
@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_times_done_wrong_count_alert(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
    mock_svc_cls: MagicMock,
) -> None:
    """Wrong number of time slots: show alert."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    state = _state(selected_times=["09:00"], posts_per_day=2, project_id=1)

    cb = _callback("sched:times:done")
    sched_svc = MagicMock()
    await cb_schedule_times_done(cb, state, _user(), MagicMock(), sched_svc)

    cb.answer.assert_called_with("Выберите ровно 2 слотов.", show_alert=True)
    state.clear.assert_not_called()


@patch("routers.publishing.scheduler.ProjectsRepository")
@patch("routers.publishing.scheduler.guard_callback_message")
async def test_times_done_creates_schedule(
    mock_guard: MagicMock,
    mock_proj_cls: MagicMock,
) -> None:
    """Valid times: clears FSM, creates schedule, shows summary."""
    mock_guard.return_value = MagicMock(edit_text=AsyncMock())
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_project())

    state = _state(
        selected_times=["09:00", "15:00"],
        selected_days=["mon", "wed"],
        posts_per_day=2,
        category_id=10,
        connection_id=5,
        platform_type="wordpress",
        project_id=1,
    )

    sched_svc = MagicMock()
    sched_svc.create_schedule = AsyncMock(return_value=_schedule(id=42))

    cb = _callback("sched:times:done")
    await cb_schedule_times_done(cb, state, _user(), MagicMock(), sched_svc)

    state.clear.assert_called_once()
    sched_svc.create_schedule.assert_called_once()
    call_args = mock_guard.return_value.edit_text.call_args
    assert "Расписание создано" in call_args[0][0]
    cb.answer.assert_any_call("Расписание создано!")


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
