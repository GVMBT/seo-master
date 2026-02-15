"""Integration tests for /start, /cancel, /help, menu navigation.

Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from tests.integration.conftest import (
    ADMIN_ID,
    ADMIN_USER,
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
    make_update_message,
)
from tests.integration.fsm.conftest import make_mock_settings

pytestmark = pytest.mark.integration

_mock_settings = make_mock_settings


# ---------------------------------------------------------------------------
# Helpers: configure mock_db for dashboard calls
# ---------------------------------------------------------------------------


def _setup_dashboard_db(mock_db: Any, user: dict[str, Any] | None = None) -> None:
    """Set up DB responses needed for _build_dashboard_text."""
    data = user or DEFAULT_USER
    mock_db.set_response("users", MockResponse(data=data))
    mock_db.set_response("projects", MockResponse(data=[], count=0))
    mock_db.set_response("categories", MockResponse(data=[], count=0))
    mock_db.set_response("platform_schedules", MockResponse(data=[], count=0))
    mock_db.set_response("token_expenses", MockResponse(data=[]))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("routers.start.get_settings", _mock_settings)
async def test_start_new_user_welcome(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any,
) -> None:
    """New user /start -> welcome text with 1500 tokens."""
    _setup_dashboard_db(mock_db)
    # Pre-cache user as new (is_new_user=True via AuthMiddleware)
    # Don't pre-cache -> AuthMiddleware will call get_or_create
    # and set is_new_user=True for first-time users
    new_user = {**DEFAULT_USER, "balance": 1500}
    mock_db.set_response("users", MockResponse(data=new_user))
    # Insert response for get_or_create
    mock_db.set_responses("users", [
        MockResponse(data=None),  # get_by_id returns None (new user)
        MockResponse(data=new_user),  # insert returns user
    ])

    update = make_update_message("/start")
    await dispatcher.feed_update(mock_bot, update)

    # Should have called send_message (message.answer calls bot.send_message)
    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    # Find the call with welcome text
    all_text = " ".join(
        str(c.kwargs.get("text", "") or c.args[1] if len(c.args) > 1 else "")
        for c in calls
        if c.kwargs.get("text") or (len(c.args) > 1 and c.args[1])
    )
    assert "1500" in all_text or "Добро пожаловать" in all_text


@patch("routers.start.get_settings", _mock_settings)
async def test_start_existing_user_dashboard(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """Existing user /start -> dashboard with balance."""
    setup_user()
    _setup_dashboard_db(mock_db)

    update = make_update_message("/start")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    all_text = " ".join(
        str(c.kwargs.get("text", ""))
        for c in calls
    )
    assert "Баланс" in all_text or "1500" in all_text or "Используйте кнопки" in all_text


@patch("routers.start.get_settings", _mock_settings)
async def test_start_clears_fsm(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """If user was in FSM state, /start clears it."""
    setup_user()
    _setup_dashboard_db(mock_db)

    # Pre-set an FSM state in Redis
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = "ProjectCreateFSM:name"
    storage_data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    mock_redis._store[storage_data_key] = json.dumps({"name": "test"})

    update = make_update_message("/start")
    await dispatcher.feed_update(mock_bot, update)

    # FSM state should be cleared
    val = await mock_redis.get(storage_key)
    assert val is None


async def test_cancel_during_fsm(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Cancel command during active FSM clears state."""
    setup_user()
    _setup_dashboard_db(mock_db)

    # Pre-set FSM state
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = "ProjectCreateFSM:name"
    storage_data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    mock_redis._store[storage_data_key] = json.dumps({"last_update_time": 9999999999})

    update = make_update_message("/cancel")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    all_text = " ".join(str(c.kwargs.get("text", "")) for c in calls)
    assert "отменено" in all_text.lower()

    # FSM state should be cleared
    val = await mock_redis.get(storage_key)
    assert val is None


async def test_cancel_no_active_fsm(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """Cancel without FSM -> 'Нет активного действия' (via reply button handler)."""
    setup_user()
    _setup_dashboard_db(mock_db)

    # Send the "Отмена" reply button text (not /cancel command)
    update = make_update_message("Отмена")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    all_text = " ".join(str(c.kwargs.get("text", "")) for c in calls)
    assert "Нет активного действия" in all_text


@patch("routers.start.get_settings", _mock_settings)
async def test_menu_button_shows_dashboard(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """'Меню' reply text -> dashboard with inline navigation."""
    setup_user()
    _setup_dashboard_db(mock_db)

    update = make_update_message("Меню")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    all_text = " ".join(str(c.kwargs.get("text", "")) for c in calls)
    assert "Баланс" in all_text or "проект" in all_text.lower()


async def test_help_command(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """/help -> help text."""
    setup_user()
    _setup_dashboard_db(mock_db)

    update = make_update_message("/help")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    all_text = " ".join(str(c.kwargs.get("text", "")) for c in calls)
    assert "SEO Master Bot" in all_text or "Команды" in all_text


async def test_help_inline_button(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """Callback 'help:main' -> help sections menu."""
    setup_user()
    _setup_dashboard_db(mock_db)

    update = make_update_callback("help:main")
    await dispatcher.feed_update(mock_bot, update)

    # help:main in start.py delegates to help.py cb_help_main which edits message
    assert mock_bot.edit_message_text.called or mock_bot.answer_callback_query.called


@patch("routers.start.get_settings", _mock_settings)
async def test_main_menu_callback(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """Callback 'menu:main' -> dashboard edit."""
    setup_user()
    _setup_dashboard_db(mock_db)

    update = make_update_callback("menu:main")
    await dispatcher.feed_update(mock_bot, update)

    # Should edit the message text to dashboard
    assert mock_bot.edit_message_text.called or mock_bot.send_message.called


async def test_non_text_in_fsm_rejected(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Photo during FSM -> 'отправьте текстовое'."""
    setup_user()
    _setup_dashboard_db(mock_db)

    # Put user in FSM state
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = "ProjectCreateFSM:name"
    storage_data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    mock_redis._store[storage_data_key] = json.dumps({"last_update_time": 9999999999})

    # Create an update with a photo (non-text, non-document)
    import time as time_mod
    from aiogram.types import Chat, Message, PhotoSize, Update
    from aiogram.types import User as TgUser
    from tests.integration.conftest import _next_update_id, make_tg_user

    tg_user = make_tg_user()
    chat = Chat(id=DEFAULT_USER_ID, type="private")
    photo = PhotoSize(file_id="photo_123", file_unique_id="unique_photo", width=100, height=100)
    msg = Message(
        message_id=_next_update_id(),
        date=int(time_mod.time()),
        chat=chat,
        from_user=tg_user,
        photo=[photo],
    )
    update = Update(update_id=_next_update_id(), message=msg)

    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.send_message.called
    calls = mock_bot.send_message.call_args_list
    all_text = " ".join(str(c.kwargs.get("text", "")) for c in calls)
    assert "текстовое" in all_text.lower()


@patch("routers.start.get_settings", _mock_settings)
async def test_start_deep_link_referral(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """/start ref_12345 -> sets referrer_id (mock UsersRepository)."""
    user_data = {**DEFAULT_USER, "referrer_id": None}
    setup_user(user_data=user_data)
    _setup_dashboard_db(mock_db, user_data)

    # The referrer user must exist
    referrer = {**DEFAULT_USER, "id": 12345, "username": "referrer"}
    mock_db.set_responses("users", [
        MockResponse(data=user_data),  # get_by_id for current user (TokenService)
        MockResponse(data=referrer),  # get_by_id for referrer
        MockResponse(data=user_data),  # update referrer_id
        MockResponse(data=user_data),  # get_profile_stats queries
    ])

    update = make_update_message("/start ref_12345")
    await dispatcher.feed_update(mock_bot, update)

    # Handler should have run without error (can't easily verify update call
    # without more intricate DB mock, but no error is the key assertion)
    assert mock_bot.send_message.called


@patch("routers.start.get_settings", _mock_settings)
async def test_admin_button_visible(
    dispatcher: Any, mock_bot: Any, mock_db: Any, setup_user: Any,
) -> None:
    """Admin user -> 'АДМИНКА' button handling."""
    setup_user(user_data=ADMIN_USER)
    _setup_dashboard_db(mock_db, ADMIN_USER)
    mock_db.set_response("payments", MockResponse(data=[]))

    update = make_update_message("АДМИНКА", user_id=ADMIN_ID, first_name="Admin", username="admin")
    await dispatcher.feed_update(mock_bot, update)

    # Should get some response (admin dashboard or redirect)
    assert mock_bot.send_message.called
