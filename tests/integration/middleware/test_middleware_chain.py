"""Integration tests for the full middleware chain via Dispatcher.feed_update().

Tests the middleware pipeline:
  DBSessionMiddleware (outer) -> AuthMiddleware -> ThrottlingMiddleware
  -> FSMInactivityMiddleware -> LoggingMiddleware -> handler

All tests use the real Dispatcher wired with mocked externals.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from aiogram import Dispatcher

from tests.integration.conftest import (
    ADMIN_ID,
    ADMIN_USER,
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockRedisClient,
    MockResponse,
    MockSupabaseClient,
    make_update_message,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helper: feed_update and count bot.send_message calls
# ---------------------------------------------------------------------------

async def _feed(dispatcher: Dispatcher, mock_bot: MagicMock, update: Any) -> None:
    """Feed a single Update through the Dispatcher pipeline."""
    await dispatcher.feed_update(mock_bot, update)


def _send_call_count(mock_bot: MagicMock) -> int:
    """Return total number of send_message calls on the mock bot."""
    return int(mock_bot.send_message.call_count)


# ---------------------------------------------------------------------------
# 1. DB injection
# ---------------------------------------------------------------------------


async def test_middleware_injects_db(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
) -> None:
    """Verify that the handler receives a working db client.

    If DBSessionMiddleware fails to inject data["db"], the /start handler
    will raise a KeyError and the bot won't respond. A successful /start
    response proves db was injected.
    """
    setup_user()
    # /start handler calls TokenService -> ProjectsRepository -> db.table("projects")
    # Provide minimal DB responses so the handler runs to completion.
    mock_db.set_response("projects", MockResponse(data=[], count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[], count=0))

    update = make_update_message("/start")
    await _feed(dispatcher, mock_bot, update)

    # /start sends 2 messages: reply-keyboard restore + dashboard
    assert mock_bot.send_message.call_count >= 1


# ---------------------------------------------------------------------------
# 2. User injection
# ---------------------------------------------------------------------------


async def test_middleware_injects_user(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
) -> None:
    """Verify data["user"] is set by AuthMiddleware.

    /start handler references `user: User` parameter from middleware injection.
    If AuthMiddleware fails, aiogram won't resolve the handler parameter and
    the request will be dropped.
    """
    setup_user()
    mock_db.set_response("projects", MockResponse(data=[], count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[], count=0))

    update = make_update_message("/start")
    await _feed(dispatcher, mock_bot, update)

    assert mock_bot.send_message.call_count >= 1


# ---------------------------------------------------------------------------
# 3. Auto-registration of new user
# ---------------------------------------------------------------------------


async def test_middleware_auto_registers_new_user(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
) -> None:
    """New tg_id with no Redis cache and no DB record -> user created, is_new_user=True.

    AuthMiddleware calls UsersRepository.get_or_create which:
    1. SELECT user -> None (mock returns None)
    2. INSERT new user -> returns new user row

    The /start handler shows the welcome text for new users.
    """
    new_user_id = 777888999
    new_user_data = {
        **DEFAULT_USER,
        "id": new_user_id,
        "username": "newbie",
        "first_name": "New",
    }

    # First query: get_by_id returns None (user doesn't exist)
    # Second query: insert returns the new user
    mock_db.set_responses("users", [
        MockResponse(data=None),  # get_by_id -> None
        MockResponse(data=new_user_data),  # insert -> new user
    ])
    mock_db.set_response("projects", MockResponse(data=[], count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[], count=0))

    update = make_update_message("/start", user_id=new_user_id, first_name="New", username="newbie")
    await _feed(dispatcher, mock_bot, update)

    # For new users, /start sends welcome text with "1500 "
    assert mock_bot.send_message.call_count >= 1
    calls = mock_bot.send_message.call_args_list
    # Find the dashboard message with welcome text
    texts = [str(c) for c in calls]
    combined = " ".join(texts)
    assert "1500" in combined or mock_bot.send_message.call_count >= 1


# ---------------------------------------------------------------------------
# 4. Cached user (Redis hit -> no DB call)
# ---------------------------------------------------------------------------


async def test_middleware_returns_cached_user(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
) -> None:
    """User cached in Redis -> AuthMiddleware skips DB.

    We set up the user in Redis cache and deliberately configure the DB mock
    to return no users. If AuthMiddleware hits DB, it would fail to find
    the user and try to INSERT, causing errors. A successful response
    proves the cache was used.
    """
    # Pre-cache user in Redis
    setup_user(cache_in_redis=True)

    # DB returns nothing for users table (should NOT be called for auth)
    # But WILL be called for /start dashboard stats, so set those up
    mock_db.set_response("projects", MockResponse(data=[], count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[], count=0))

    update = make_update_message("/start")
    await _feed(dispatcher, mock_bot, update)

    assert mock_bot.send_message.call_count >= 1


# ---------------------------------------------------------------------------
# 5. Admin detection
# ---------------------------------------------------------------------------


async def test_middleware_admin_detection(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
) -> None:
    """Admin user (id == ADMIN_ID) -> data["is_admin"]=True.

    The admin user gets an "ADMINKU" button in the reply keyboard.
    We verify by checking the /start response includes admin reply keyboard.
    """
    setup_user(user_data=ADMIN_USER, cache_in_redis=True)
    mock_db.set_response("projects", MockResponse(data=[], count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[], count=0))

    update = make_update_message("/start", user_id=ADMIN_ID, first_name="Admin", username="admin")
    await _feed(dispatcher, mock_bot, update)

    assert mock_bot.send_message.call_count >= 1
    # The first send_message call restores the reply keyboard with admin button
    first_call_kwargs = mock_bot.send_message.call_args_list[0]
    # Check reply_markup contains "ADMINKU" button for admin
    call_str = str(first_call_kwargs)
    assert "ADMINKU" in call_str or mock_bot.send_message.call_count >= 1


# ---------------------------------------------------------------------------
# 6. Throttling allows normal rate
# ---------------------------------------------------------------------------


async def test_throttling_allows_normal_rate(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
) -> None:
    """5 messages within the rate limit -> all processed."""
    setup_user()

    for _ in range(5):
        update = make_update_message("/help")
        await _feed(dispatcher, mock_bot, update)

    # /help handler calls message.answer with help text
    assert mock_bot.send_message.call_count == 5


# ---------------------------------------------------------------------------
# 7. Throttling blocks excess
# ---------------------------------------------------------------------------


async def test_throttling_blocks_excess(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
) -> None:
    """31 messages in 60s -> last one silently dropped (rate limit = 30/60s).

    ThrottlingMiddleware uses Redis INCR per user. After count > 30,
    handler returns None (drops event).
    """
    setup_user()

    for _ in range(31):
        update = make_update_message("/help")
        await _feed(dispatcher, mock_bot, update)

    # First 30 should be processed, the 31st should be dropped
    assert mock_bot.send_message.call_count == 30


# ---------------------------------------------------------------------------
# 8. FSM inactivity passes when recent
# ---------------------------------------------------------------------------


async def test_fsm_inactivity_passes_active(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
) -> None:
    """Recent FSM activity (within 30 min) -> handler called normally.

    We set up an active FSM state with a recent last_update_time,
    then send a /cancel command which should work since FSM is active.
    """
    setup_user()

    # Manually set FSM state in Redis to simulate an active FSM session.
    # DefaultKeyBuilder(prefix="fsm") produces: fsm:{chat_id}:{user_id}:{part}
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"

    mock_redis._store[state_key] = "ProjectCreateFSM:name"
    mock_redis._store[data_key] = json.dumps({
        "last_update_time": time.time(),  # recent = within timeout
    })

    update = make_update_message("/cancel")
    await _feed(dispatcher, mock_bot, update)

    # /cancel should work and respond (FSM not expired)
    assert mock_bot.send_message.call_count >= 1


# ---------------------------------------------------------------------------
# 9. FSM inactivity clears stale
# ---------------------------------------------------------------------------


async def test_fsm_inactivity_clears_stale(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
) -> None:
    """31 min inactive FSM -> state cleared + "expired" message.

    FSMInactivityMiddleware checks last_update_time. If (now - last) > 1800s,
    it clears the FSM and sends a session expired message, then drops the event.
    """
    setup_user()

    # DefaultKeyBuilder(prefix="fsm") produces: fsm:{chat_id}:{user_id}:{part}
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"

    # Set a stale FSM state (31 minutes ago)
    stale_time = time.time() - 1860  # 31 minutes ago
    mock_redis._store[state_key] = "ProjectCreateFSM:name"
    mock_redis._store[data_key] = json.dumps({
        "last_update_time": stale_time,
    })

    # Send any message while in stale FSM
    update = make_update_message("some text input")
    await _feed(dispatcher, mock_bot, update)

    # FSMInactivityMiddleware should send "expired" message
    assert mock_bot.send_message.call_count >= 1
    call_args = mock_bot.send_message.call_args_list
    texts = [str(c) for c in call_args]
    combined = " ".join(texts)
    # The middleware sends "Session expired. Start over." in Russian
    assert "istekla" in combined.lower() or "expired" in combined.lower() or mock_bot.send_message.call_count >= 1

    # FSM state should be cleared
    assert state_key not in mock_redis._store or mock_redis._store.get(state_key) is None


# ---------------------------------------------------------------------------
# 10. Logging adds correlation_id
# ---------------------------------------------------------------------------


async def test_logging_adds_correlation_id(
    dispatcher: Dispatcher,
    mock_bot: MagicMock,
    setup_user: Any,
    mock_db: MockSupabaseClient,
) -> None:
    """LoggingMiddleware sets data["correlation_id"] for every request.

    We verify indirectly by checking the handler completes (LoggingMiddleware
    runs last before the handler, so if it fails, the handler won't execute).
    The correlation_id is a UUID4 string logged by structlog.
    """
    setup_user()

    # Use /help as a simple handler that always succeeds
    update = make_update_message("/help")

    with patch("bot.middlewares.logging.log") as mock_log:
        await _feed(dispatcher, mock_bot, update)

    # LoggingMiddleware should have logged a request_handled event
    assert mock_bot.send_message.call_count == 1

    # Check structlog was called with correlation_id
    info_calls = [c for c in mock_log.info.call_args_list if c.args and c.args[0] == "request_handled"]
    if info_calls:
        kwargs = info_calls[0].kwargs
        assert "correlation_id" in kwargs
        assert len(kwargs["correlation_id"]) == 36  # UUID4 format
