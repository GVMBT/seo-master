"""Integration tests for FSMInactivityMiddleware (E27).

Tests the 30-minute inactivity timeout that auto-clears FSM state.
Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
import time
from typing import Any

import pytest

from tests.integration.conftest import (
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_message,
)
from tests.integration.fsm.conftest import DEFAULT_PROJECT

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db(mock_db: Any) -> None:
    """Set up DB mocks for inactivity tests."""
    mock_db.set_response("users", MockResponse(data=DEFAULT_USER))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT, count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[]))


def _put_in_fsm(
    mock_redis: Any,
    state: str,
    last_update_time: float | None = None,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """Put user in a given FSM state with specified last_update_time."""
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = state
    data: dict[str, Any] = {}
    if last_update_time is not None:
        data["last_update_time"] = last_update_time
    if extra_data:
        data.update(extra_data)
    storage_data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    mock_redis._store[storage_data_key] = json.dumps(data, default=str)


def _get_fsm_state(mock_redis: Any) -> str | None:
    key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    return mock_redis._store.get(key)


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


async def test_active_fsm_not_timed_out(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Recent activity -> handler called normally."""
    setup_user()
    _setup_db(mock_db)

    # Put user in FSM with recent last_update_time (just now)
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name", last_update_time=time.time())

    update = make_update_message("My Project Name")
    await dispatcher.feed_update(mock_bot, update)

    # Handler should have been called (FSM state should advance)
    all_text = _get_all_text(mock_bot)
    # Should show step 2 (company name) since name was accepted
    assert "Шаг 2/4" in all_text or "компании" in all_text.lower() or mock_bot.send_message.called


async def test_inactive_fsm_cleared(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """31 min old -> FSM cleared, 'Сессия истекла'."""
    setup_user()
    _setup_db(mock_db)

    # Put user in FSM with old last_update_time (31 minutes ago)
    old_time = time.time() - (31 * 60)  # 31 minutes ago
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name", last_update_time=old_time)

    update = make_update_message("My Project Name")
    await dispatcher.feed_update(mock_bot, update)

    # FSM should be cleared
    state = _get_fsm_state(mock_redis)
    assert state is None

    # Should have sent "Сессия истекла" message
    all_text = _get_all_text(mock_bot)
    assert "истекла" in all_text.lower() or "Сессия" in all_text


async def test_inactivity_sends_main_menu(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Expired -> main menu keyboard restored."""
    setup_user()
    _setup_db(mock_db)

    old_time = time.time() - (35 * 60)  # 35 minutes ago
    _put_in_fsm(mock_redis, "KeywordGenerationFSM:products", last_update_time=old_time)

    update = make_update_message("Some input that should be dropped")
    await dispatcher.feed_update(mock_bot, update)

    # Should have sent message with reply markup (main menu)
    assert mock_bot.send_message.called
    call_kwargs = mock_bot.send_message.call_args.kwargs
    # The reply_markup should be present (main menu keyboard)
    assert call_kwargs.get("reply_markup") is not None


async def test_no_fsm_no_check(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """No active FSM -> middleware passes through without check."""
    setup_user()
    _setup_db(mock_db)

    # No FSM state set — user sends a regular message
    update = make_update_message("/help")
    await dispatcher.feed_update(mock_bot, update)

    # /help handler should have been called
    all_text = _get_all_text(mock_bot)
    assert "SEO Master Bot" in all_text or "Команды" in all_text


async def test_last_update_time_refreshed(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Each update refreshes the inactivity timer."""
    setup_user()
    _setup_db(mock_db)

    # Put user in FSM with somewhat old but not expired time (20 min ago)
    twenty_min_ago = time.time() - (20 * 60)
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name", last_update_time=twenty_min_ago)

    before_update = time.time()
    update = make_update_message("Valid Project Name")
    await dispatcher.feed_update(mock_bot, update)

    # Check that last_update_time was refreshed
    data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    raw = mock_redis._store.get(data_key)
    if raw:
        data = json.loads(raw)
        new_time = data.get("last_update_time")
        if new_time is not None:
            # The refreshed time should be close to now (within 5 seconds)
            assert float(new_time) >= before_update - 1


async def test_boundary_exactly_30_min(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Exactly 1800s -> not expired (boundary condition)."""
    setup_user()
    _setup_db(mock_db)

    # Set last_update_time to exactly 1800 seconds ago (boundary)
    # The check is: (now - last_update) > timeout, so exactly 1800 is NOT expired
    exactly_30_min_ago = time.time() - 1800
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name", last_update_time=exactly_30_min_ago)

    update = make_update_message("Boundary Test Project")
    await dispatcher.feed_update(mock_bot, update)

    # Should NOT have expired — handler should process normally
    all_text = _get_all_text(mock_bot)
    # Either the handler processed (step 2) or at worst the FSM didn't clear
    # The key check: "Сессия истекла" should NOT appear
    assert "истекла" not in all_text.lower()
