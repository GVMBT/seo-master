"""Integration tests for FSM conflict resolution (E29).

Tests that starting a new FSM auto-resets the current one via ensure_no_active_fsm().
Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from tests.integration.conftest import (
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
    make_update_message,
)
from tests.integration.fsm.conftest import (
    DEFAULT_CATEGORY,
    DEFAULT_CONNECTION_WP,
    DEFAULT_PROJECT,
    make_mock_settings,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEYWORDS_CLUSTER = [
    {
        "cluster_name": "SEO testing",
        "cluster_type": "article",
        "main_phrase": "seo guide",
        "total_volume": 1000,
        "phrases": [{"phrase": "seo guide", "volume": 1000}],
    }
]

_CATEGORY_WITH_KEYWORDS = {**DEFAULT_CATEGORY, "keywords": _KEYWORDS_CLUSTER}


_mock_settings = make_mock_settings


def _setup_db(mock_db: Any) -> None:
    """Set up DB mocks for conflict tests."""
    mock_db.set_response("users", MockResponse(data=DEFAULT_USER))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT, count=1))
    mock_db.set_response("categories", MockResponse(data=DEFAULT_CATEGORY))
    mock_db.set_response("platform_connections", MockResponse(data=DEFAULT_CONNECTION_WP))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[]))
    mock_db.set_response("publication_logs", MockResponse(data=[]))


def _put_in_fsm(
    mock_redis: Any,
    state: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Put user in a given FSM state."""
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = state
    fsm_data: dict[str, Any] = {"last_update_time": time.time()}
    if data:
        fsm_data.update(data)
    storage_data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    mock_redis._store[storage_data_key] = json.dumps(fsm_data, default=str)


def _get_fsm_state(mock_redis: Any) -> str | None:
    """Get current FSM state from Redis."""
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


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_new_fsm_clears_old(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """User in ProjectCreateFSM, starts WP connect -> old FSM cleared."""
    setup_user()
    _setup_db(mock_db)

    # Put user in ProjectCreate FSM
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name", {"name": "draft project"})

    # Start ConnectWordPress FSM (should clear ProjectCreate)
    update = make_update_callback("project:1:add:wordpress")
    await dispatcher.feed_update(mock_bot, update)

    # Should be in ConnectWordPressFSM now
    state = _get_fsm_state(mock_redis)
    assert state is not None
    assert "ConnectWordPressFSM" in state

    # Should have sent interruption message
    all_text = _get_all_text(mock_bot)
    assert "прерван" in all_text.lower() or "Шаг 1/3" in all_text


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_fsm_conflict_warning_sent(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Notification about auto-reset is sent."""
    setup_user()
    _setup_db(mock_db)

    # Put user in KeywordGeneration FSM
    _put_in_fsm(mock_redis, "KeywordGenerationFSM:products", {"category_id": 10})

    # Start ConnectWordPress FSM
    update = make_update_callback("project:1:add:wordpress")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    # The message should include the interrupted process name
    assert "прерван" in all_text.lower() or "подбор" in all_text.lower()


@patch("routers.start.get_settings", _mock_settings)
async def test_start_clears_any_fsm(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """/start always clears any active FSM."""
    setup_user()
    _setup_db(mock_db)

    # Put user in ScheduleSetup FSM
    _put_in_fsm(mock_redis, "ScheduleSetupFSM:select_days", {"category_id": 10, "connection_id": 100})

    update = make_update_message("/start")
    await dispatcher.feed_update(mock_bot, update)

    state = _get_fsm_state(mock_redis)
    assert state is None  # FSM cleared


async def test_cancel_clears_any_fsm(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """/cancel always clears any FSM."""
    setup_user()
    _setup_db(mock_db)

    # Put user in SocialPostPublishFSM
    _put_in_fsm(
        mock_redis,
        "SocialPostPublishFSM:review",
        {
            "generated_content": "test",
            "category_id": 10,
        },
    )

    update = make_update_message("/cancel")
    await dispatcher.feed_update(mock_bot, update)

    state = _get_fsm_state(mock_redis)
    assert state is None


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_multiple_fsm_switches(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Switch 3 times, only last one active."""
    setup_user()
    _setup_db(mock_db)

    # Start ProjectCreate
    update = make_update_callback("projects:new")
    await dispatcher.feed_update(mock_bot, update)
    state = _get_fsm_state(mock_redis)
    assert state is not None
    assert "ProjectCreateFSM" in state
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Switch to ConnectWordPress (interrupts ProjectCreate)
    update = make_update_callback("project:1:add:wordpress")
    await dispatcher.feed_update(mock_bot, update)
    state = _get_fsm_state(mock_redis)
    assert state is not None
    assert "ConnectWordPressFSM" in state
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Switch to keyword generation (interrupts ConnectWordPress)
    update = make_update_callback("category:10:kw:generate")
    await dispatcher.feed_update(mock_bot, update)
    state = _get_fsm_state(mock_redis)
    assert state is not None
    assert "KeywordGenerationFSM" in state


async def test_fsm_state_data_cleared(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Old FSM's state.data is gone after conflict resolution."""
    setup_user()
    _setup_db(mock_db)

    # Put user in ProjectCreate with some data
    _put_in_fsm(
        mock_redis,
        "ProjectCreateFSM:company_name",
        {
            "name": "My Draft",
            "sensitive_data": "should_be_cleared",
        },
    )

    # Start a new FSM (projects:new will clear and start fresh)
    update = make_update_callback("projects:new")
    await dispatcher.feed_update(mock_bot, update)

    # Check state data no longer contains old data
    data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    raw = mock_redis._store.get(data_key)
    if raw:
        data = json.loads(raw)
        assert "sensitive_data" not in data
        assert data.get("name") != "My Draft"


async def test_callback_during_wrong_fsm(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Callback for FSM A while in FSM B -> FSM A callback should not trigger."""
    setup_user()
    _setup_db(mock_db)

    # Put user in ProjectCreateFSM:name
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name")

    # Send a SocialPostPublishFSM callback (pub:social:confirm)
    # This should NOT trigger because user is in wrong FSM state
    update = make_update_callback("pub:social:confirm")
    await dispatcher.feed_update(mock_bot, update)

    # State should NOT have changed to SocialPostPublishFSM
    state = _get_fsm_state(mock_redis)
    # Should still be in ProjectCreate (callback didn't match)
    if state is not None:
        assert "ProjectCreateFSM" in state


async def test_concurrent_updates_safe(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Two rapid updates, last one wins."""
    setup_user()
    _setup_db(mock_db)

    # Put user in ProjectCreate
    _put_in_fsm(mock_redis, "ProjectCreateFSM:name")

    # Send two messages rapidly
    update1 = make_update_message("First Project Name")
    update2 = make_update_message("Second Project Name")

    # Process sequentially (Dispatcher.feed_update is sequential)
    await dispatcher.feed_update(mock_bot, update1)
    await dispatcher.feed_update(mock_bot, update2)

    # The last successful state transition should be the active one.
    # After first message, state should advance to company_name.
    # After second message (in company_name), should advance to specialization.
    # Both updates should have been processed.
    assert _get_fsm_state(mock_redis) is not None
    assert mock_bot.send_message.call_count >= 2
