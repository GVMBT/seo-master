"""Integration tests for ScheduleSetupFSM — 3-step schedule creation flow.

Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.integration.conftest import (
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
)
from tests.integration.fsm.conftest import (
    DEFAULT_CATEGORY,
    DEFAULT_CONNECTION_WP,
    DEFAULT_PROJECT,
    DEFAULT_SCHEDULE,
    make_mock_settings,
)

pytestmark = pytest.mark.integration

_mock_settings = make_mock_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_schedule_db(mock_db: Any) -> None:
    """Set up DB mocks for schedule flow."""
    mock_db.set_response("users", MockResponse(data=DEFAULT_USER))
    mock_db.set_response("categories", MockResponse(data=DEFAULT_CATEGORY))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT))
    mock_db.set_response("platform_connections", MockResponse(data=DEFAULT_CONNECTION_WP))
    mock_db.set_response("platform_schedules", MockResponse(data=[]))


def _put_in_schedule_fsm(
    mock_redis: Any,
    state: str,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """Put user in a ScheduleSetupFSM state."""
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = state
    data: dict[str, Any] = {
        "category_id": 10,
        "connection_id": 100,
        "platform_type": "wordpress",
        "project_id": 1,
        "selected_days": [],
        "last_update_time": time.time(),
    }
    if extra_data:
        data.update(extra_data)
    storage_data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    mock_redis._store[storage_data_key] = json.dumps(data, default=str)


def _get_all_text(mock_bot: Any) -> str:
    texts = []
    for c in mock_bot.send_message.call_args_list:
        texts.append(str(c.kwargs.get("text", "")))
    for c in mock_bot.edit_message_text.call_args_list:
        texts.append(str(c.kwargs.get("text", "")))
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_starts_with_days(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """sched:cat:{id}:plt:{id} -> shows day selection."""
    setup_user()
    _setup_schedule_db(mock_db)

    update = make_update_callback("sched:cat:10:plt:100")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 1/3" in all_text or "дни" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ScheduleSetupFSM:select_days" in state_val


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_toggle_day(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Toggle day selection."""
    setup_user()
    _setup_schedule_db(mock_db)
    _put_in_schedule_fsm(mock_redis, "ScheduleSetupFSM:select_days")

    update = make_update_callback("sched:day:mon")
    await dispatcher.feed_update(mock_bot, update)

    # Check that day was added to state data
    data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    raw = await mock_redis.get(data_key)
    if raw:
        data = json.loads(raw)
        assert "mon" in data.get("selected_days", [])


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_days_done_no_selection(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Confirm days with none selected -> alert."""
    setup_user()
    _setup_schedule_db(mock_db)
    _put_in_schedule_fsm(mock_redis, "ScheduleSetupFSM:select_days", {"selected_days": []})

    update = make_update_callback("sched:days:done")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "день" in text.lower() or "хотя бы" in text.lower()


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_days_selected_moves_to_count(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Days confirmed -> asks for posts_per_day."""
    setup_user()
    _setup_schedule_db(mock_db)
    _put_in_schedule_fsm(mock_redis, "ScheduleSetupFSM:select_days", {"selected_days": ["mon", "wed", "fri"]})

    update = make_update_callback("sched:days:done")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 2/3" in all_text or "публикаций" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ScheduleSetupFSM:select_count" in state_val


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_count_selected_moves_to_times(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Count selected -> asks for time slots."""
    setup_user()
    _setup_schedule_db(mock_db)
    _put_in_schedule_fsm(mock_redis, "ScheduleSetupFSM:select_count", {
        "selected_days": ["mon", "wed"],
    })

    update = make_update_callback("sched:count:1")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 3/3" in all_text or "время" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ScheduleSetupFSM:select_times" in state_val


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_creates_with_qstash(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Times confirmed -> creates QStash cron jobs."""
    setup_user()
    _setup_schedule_db(mock_db)
    _put_in_schedule_fsm(mock_redis, "ScheduleSetupFSM:select_times", {
        "selected_days": ["mon", "wed"],
        "posts_per_day": 1,
        "selected_times": ["09:00"],
    })

    # Mock scheduler_service.create_schedule
    mock_schedule = MagicMock()
    mock_schedule.id = 200
    mock_services["scheduler_service"].create_schedule = AsyncMock(return_value=mock_schedule)

    update = make_update_callback("sched:times:done")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "создано" in all_text.lower() or "Расписание" in all_text

    # Scheduler service should have been called
    mock_services["scheduler_service"].create_schedule.assert_called_once()

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_times_mismatch(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Times count does not match posts_per_day -> alert."""
    setup_user()
    _setup_schedule_db(mock_db)
    _put_in_schedule_fsm(mock_redis, "ScheduleSetupFSM:select_times", {
        "selected_days": ["mon"],
        "posts_per_day": 2,
        "selected_times": ["09:00"],  # Only 1 but need 2
    })

    update = make_update_callback("sched:times:done")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "ровно" in text.lower() or "2" in text


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_toggle_enabled(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Enable/disable schedule toggle."""
    setup_user()
    _setup_schedule_db(mock_db)
    mock_db.set_response("platform_schedules", MockResponse(data=DEFAULT_SCHEDULE))
    mock_services["scheduler_service"].toggle_schedule = AsyncMock()

    update = make_update_callback("schedule:200:toggle")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    mock_services["scheduler_service"].toggle_schedule.assert_called_once()


@patch("routers.publishing.scheduler.get_settings", _mock_settings)
async def test_schedule_delete_removes_qstash(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Delete -> removes QStash schedules first."""
    setup_user()
    _setup_schedule_db(mock_db)
    mock_db.set_response("platform_schedules", MockResponse(data=DEFAULT_SCHEDULE))
    mock_services["scheduler_service"].delete_schedule = AsyncMock()

    update = make_update_callback("schedule:200:delete")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    mock_services["scheduler_service"].delete_schedule.assert_called_once_with(200)
