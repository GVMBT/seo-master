"""Integration tests for ConnectWordPressFSM — 3-step WP connection flow.

Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tests.integration.conftest import (
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
    make_update_message,
)
from tests.integration.fsm.conftest import DEFAULT_PROJECT, _test_cm, make_mock_settings

pytestmark = pytest.mark.integration

_mock_settings = make_mock_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_wp_db(mock_db: Any) -> None:
    """Set up DB mocks for WP connection flow."""
    mock_db.set_response("users", MockResponse(data=DEFAULT_USER))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT))
    mock_db.set_response("platform_connections", MockResponse(data=None))


def _put_in_wp_fsm(
    mock_redis: Any,
    state: str,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """Put user in a ConnectWordPressFSM state."""
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = state
    data: dict[str, Any] = {"project_id": 1, "last_update_time": time.time()}
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


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_connect_starts_fsm(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Callback project:{id}:add:wordpress -> asks for URL."""
    setup_user()
    _setup_wp_db(mock_db)

    update = make_update_callback("project:1:add:wordpress")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 1/3" in all_text or "URL" in all_text

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ConnectWordPressFSM:url" in state_val


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_step1_valid_url(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """URL accepted -> asks for username."""
    setup_user()
    _setup_wp_db(mock_db)
    _put_in_wp_fsm(mock_redis, "ConnectWordPressFSM:url")

    update = make_update_message("https://myblog.example.com")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 2/3" in all_text or "логин" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ConnectWordPressFSM:login" in state_val


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_step1_invalid_url(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Bad URL -> retry."""
    setup_user()
    _setup_wp_db(mock_db)
    _put_in_wp_fsm(mock_redis, "ConnectWordPressFSM:url")

    update = make_update_message("not a url at all !!!")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "URL" in all_text or "https" in all_text.lower()

    # Should stay in url state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ConnectWordPressFSM:url" in state_val


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_step1_auto_prepend_https(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """URL without scheme -> auto-prepend https://."""
    setup_user()
    _setup_wp_db(mock_db)
    _put_in_wp_fsm(mock_redis, "ConnectWordPressFSM:url")

    update = make_update_message("myblog.example.com")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    # Should accept and advance (auto-prepend https://)
    assert "Шаг 2/3" in all_text or "логин" in all_text.lower()


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_step2_username(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Username -> asks for app password."""
    setup_user()
    _setup_wp_db(mock_db)
    _put_in_wp_fsm(mock_redis, "ConnectWordPressFSM:login", {"wp_url": "https://myblog.example.com"})

    update = make_update_message("admin")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 3/3" in all_text or "Application Password" in all_text or "пароль" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ConnectWordPressFSM:password" in state_val


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_step3_valid_credentials(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Valid app password format -> creates connection."""
    setup_user()
    _setup_wp_db(mock_db)
    # Connection creation response (with encrypted credentials for decryption)
    conn_creds = _test_cm.encrypt({"url": "https://myblog.example.com", "login": "admin", "app_password": "test"})
    conn_data = {
        "id": 100,
        "project_id": 1,
        "platform_type": "wordpress",
        "status": "active",
        "identifier": "myblog.example.com",
        "credentials": conn_creds,
        "metadata": {},
        "created_at": "2025-01-01T00:00:00Z",
    }
    # First query: get_by_identifier_for_user returns None (no dup), second: insert
    mock_db.set_responses(
        "platform_connections",
        [
            MockResponse(data=None),  # get_by_identifier_for_user: no duplicate
            MockResponse(data=conn_data),  # create: returns new connection
        ],
    )
    _put_in_wp_fsm(
        mock_redis,
        "ConnectWordPressFSM:password",
        {
            "wp_url": "https://myblog.example.com",
            "wp_login": "admin",
        },
    )

    # Valid WP Application Password format: xxxx xxxx xxxx xxxx xxxx xxxx
    update = make_update_message("Abcd Efgh Ijkl Mnop Qrst Uvwx")

    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "подключен" in all_text.lower() or "WordPress" in all_text

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_step3_invalid_password_format(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Bad password format -> error, retry."""
    setup_user()
    _setup_wp_db(mock_db)
    _put_in_wp_fsm(
        mock_redis,
        "ConnectWordPressFSM:password",
        {
            "wp_url": "https://myblog.example.com",
            "wp_login": "admin",
        },
    )

    update = make_update_message("wrong-password-format")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Application Password" in all_text or "формат" in all_text.lower()

    # Should stay in password state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "password" in state_val


async def test_wp_cancel_during_connection(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """/cancel during WP connection -> clean exit."""
    setup_user()
    _setup_wp_db(mock_db)
    _put_in_wp_fsm(mock_redis, "ConnectWordPressFSM:login", {"wp_url": "https://example.com"})

    update = make_update_message("/cancel")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "отменено" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.platforms.connections.get_settings", _mock_settings)
async def test_wp_full_flow_end_to_end(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Full 3-step WP connection flow."""
    setup_user()
    _setup_wp_db(mock_db)
    conn_creds = _test_cm.encrypt({"url": "https://blog.example.com", "login": "admin", "app_password": "test"})
    conn_data = {
        "id": 100,
        "project_id": 1,
        "platform_type": "wordpress",
        "status": "active",
        "identifier": "blog.example.com",
        "credentials": conn_creds,
        "metadata": {},
        "created_at": "2025-01-01T00:00:00Z",
    }
    # Set up responses: None for dup check, conn_data for create
    mock_db.set_responses(
        "platform_connections",
        [
            MockResponse(data=None),  # get_by_identifier during step 3
            MockResponse(data=conn_data),  # create result
        ],
    )

    # Step 1: start
    update = make_update_callback("project:1:add:wordpress")
    await dispatcher.feed_update(mock_bot, update)
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 2: URL
    update = make_update_message("https://blog.example.com")
    await dispatcher.feed_update(mock_bot, update)
    all_text = _get_all_text(mock_bot)
    assert "Шаг 2/3" in all_text or "логин" in all_text.lower()
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 3: login
    update = make_update_message("admin")
    await dispatcher.feed_update(mock_bot, update)
    all_text = _get_all_text(mock_bot)
    assert "Шаг 3/3" in all_text or "пароль" in all_text.lower()
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 4: password
    mock_bot.delete_message = AsyncMock(return_value=True)
    update = make_update_message("Abcd Efgh Ijkl Mnop Qrst Uvwx")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "подключен" in all_text.lower() or "WordPress" in all_text

    # FSM cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None
