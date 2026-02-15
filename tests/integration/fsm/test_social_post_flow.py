"""Integration tests for SocialPostPublishFSM — TG/VK/Pinterest social post flow.

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
)
from tests.integration.fsm.conftest import (
    DEFAULT_CATEGORY,
    DEFAULT_PROJECT,
    _test_cm,
    make_mock_settings,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KEYWORDS_CLUSTER = [
    {
        "cluster_name": "TG content",
        "cluster_type": "article",
        "main_phrase": "telegram marketing tips",
        "total_volume": 500,
        "phrases": [{"phrase": "telegram marketing tips", "volume": 500}],
    }
]

_CATEGORY_WITH_KEYWORDS = {**DEFAULT_CATEGORY, "keywords": _KEYWORDS_CLUSTER}

_CONNECTION_TG = {
    "id": 200,
    "project_id": 1,
    "platform_type": "telegram",
    "status": "active",
    "credentials": _test_cm.encrypt({"bot_token": "123:FAKE", "channel_id": "-100123456"}),
    "metadata": {},
    "identifier": "@test_channel",
    "created_at": "2025-01-01T00:00:00Z",
}

_CONNECTION_VK = {
    "id": 201,
    "project_id": 1,
    "platform_type": "vk",
    "status": "active",
    "credentials": _test_cm.encrypt({"access_token": "vk1.a.FAKE", "group_id": "12345"}),
    "metadata": {},
    "identifier": "12345",
    "created_at": "2025-01-01T00:00:00Z",
}


_mock_settings = make_mock_settings


def _setup_social_db(
    mock_db: Any,
    category: dict[str, Any] | None = None,
    connection: dict[str, Any] | None = None,
    balance: int = 1500,
) -> None:
    """Set up DB mocks for social post flow."""
    u = {**DEFAULT_USER, "balance": balance}
    mock_db.set_response("users", MockResponse(data=u))
    mock_db.set_response("categories", MockResponse(data=category or _CATEGORY_WITH_KEYWORDS))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT))
    mock_db.set_response("platform_connections", MockResponse(data=connection or _CONNECTION_TG))
    mock_db.set_response("publication_logs", MockResponse(data={
        "id": 1, "user_id": DEFAULT_USER_ID, "project_id": 1, "category_id": 10,
        "platform_type": "telegram", "connection_id": 200, "keyword": "test",
        "content_type": "social_post", "images_count": 0, "post_url": "",
        "word_count": 100, "tokens_spent": 40, "created_at": "2025-01-01T00:00:00Z",
    }))
    mock_db.set_response("token_expenses", MockResponse(data={
        "id": 1, "user_id": DEFAULT_USER_ID, "amount": -40, "operation_type": "social_post",
        "description": "Social post generation", "created_at": "2025-01-01T00:00:00Z",
    }))
    mock_db.set_rpc_response("charge_balance", [{"new_balance": balance - 40}])
    mock_db.set_rpc_response("refund_balance", [{"new_balance": balance}])


def _put_in_social_fsm(
    mock_redis: Any,
    state: str,
    extra_data: dict[str, Any] | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> None:
    """Put user in a SocialPostPublishFSM state."""
    storage_key = f"fsm:{user_id}:{user_id}:state"
    mock_redis._store[storage_key] = state
    data = {
        "category_id": 10,
        "project_id": 1,
        "connection_id": 200,
        "platform": "telegram",
        "cost": 40,
        "last_update_time": time.time(),
    }
    if extra_data:
        data.update(extra_data)
    storage_data_key = f"fsm:{user_id}:{user_id}:data"
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


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_start_shows_cost_confirmation(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """category:{id}:publish:tg:{conn_id} -> shows cost confirmation."""
    setup_user()
    _setup_social_db(mock_db, connection=_CONNECTION_TG)

    update = make_update_callback("category:10:publish:tg:200")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Telegram" in all_text or "Генерация" in all_text or "токенов" in all_text.lower()

    # Should be in confirm_cost state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "SocialPostPublishFSM:confirm_cost" in state_val


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_tg_post_generated(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Confirm generates Telegram post."""
    setup_user()
    _setup_social_db(mock_db, connection=_CONNECTION_TG)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:confirm_cost")
    mock_services["rate_limiter"].check = AsyncMock()

    update = make_update_callback("pub:social:confirm")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Генерирую" in all_text or "Готово" in all_text or "пост" in all_text.lower()


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_vk_post_generated(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """VK post generation."""
    setup_user()
    _setup_social_db(mock_db, connection=_CONNECTION_VK)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:confirm_cost", {"platform": "vk", "connection_id": 201})
    mock_services["rate_limiter"].check = AsyncMock()

    update = make_update_callback("pub:social:confirm")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Генерирую" in all_text or "Готово" in all_text


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_confirm_publish(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Confirm -> publishes post."""
    setup_user()
    _setup_social_db(mock_db, connection=_CONNECTION_TG)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:review", {
        "generated_content": "Test social post content",
        "keyword": "telegram tips",
        "regeneration_count": 0,
    })

    update = make_update_callback("pub:social:publish")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "опубликован" in all_text.lower() or "Публикую" in all_text

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_cancel_flow(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Cancel -> no publish."""
    setup_user()
    _setup_social_db(mock_db)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:review", {
        "generated_content": "Test content",
        "regeneration_count": 0,
    })

    update = make_update_callback("pub:social:cancel")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "отменена" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_regenerate(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Regenerate post (free attempt)."""
    setup_user()
    _setup_social_db(mock_db, connection=_CONNECTION_TG)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:review", {
        "generated_content": "Original content",
        "keyword": "telegram tips",
        "regeneration_count": 0,
    })

    update = make_update_callback("pub:social:regen")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Перегенер" in all_text or "Готово" in all_text or "Новый пост" in all_text


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_insufficient_balance(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Not enough tokens for social post."""
    low_user = {**DEFAULT_USER, "balance": 5}
    setup_user(user_data=low_user)
    _setup_social_db(mock_db, connection=_CONNECTION_TG, balance=5)

    update = make_update_callback("category:10:publish:tg:200")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "токенов" in all_text.lower() or "баланс" in all_text.lower() or "Недостаточно" in all_text


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_no_connections(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """No platform connected -> alert."""
    setup_user()
    empty_cat = {**DEFAULT_CATEGORY, "keywords": _KEYWORDS_CLUSTER}
    mock_db.set_response("users", MockResponse(data=DEFAULT_USER))
    mock_db.set_response("categories", MockResponse(data=empty_cat))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT))
    # Connection not found
    mock_db.set_response("platform_connections", MockResponse(data=None))

    update = make_update_callback("category:10:publish:tg:999")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "не найдено" in text.lower() or "Подключение" in text


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_stores_in_fsm_data(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Post content stored in state.data (not DB)."""
    setup_user()
    _setup_social_db(mock_db, connection=_CONNECTION_TG)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:confirm_cost")
    mock_services["rate_limiter"].check = AsyncMock()

    update = make_update_callback("pub:social:confirm")
    await dispatcher.feed_update(mock_bot, update)

    # Check state.data has generated content
    data_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:data"
    raw = await mock_redis.get(data_key)
    if raw:
        data = json.loads(raw)
        assert "generated_content" in data


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_publishing_guard_e07(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """E07: Prevent double-click during publishing."""
    setup_user()
    _setup_social_db(mock_db)
    _put_in_social_fsm(mock_redis, "SocialPostPublishFSM:publishing")

    update = make_update_callback("pub:social:publish")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "в процессе" in text.lower()


@patch("routers.publishing.social.get_settings", _mock_settings)
async def test_social_no_keywords(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Category without keywords -> error."""
    setup_user()
    empty_cat = {**DEFAULT_CATEGORY, "keywords": []}
    _setup_social_db(mock_db, category=empty_cat, connection=_CONNECTION_TG)

    update = make_update_callback("category:10:publish:tg:200")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "фраз" in all_text.lower() or "ключев" in all_text.lower()
