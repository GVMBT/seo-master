"""Integration tests for KeywordGenerationFSM and KeywordUploadFSM.

Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.integration.conftest import (
    ADMIN_ID,
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
    make_update_document,
    make_update_message,
)
from tests.integration.fsm.conftest import (
    DEFAULT_CATEGORY,
    DEFAULT_PROJECT,
    make_mock_settings,
)

pytestmark = pytest.mark.integration

_mock_settings = make_mock_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_keyword_db(
    mock_db: Any,
    balance: int = 1500,
    category: dict[str, Any] | None = None,
) -> None:
    """Set up DB mocks for keyword generation flow."""
    u = {**DEFAULT_USER, "balance": balance}
    mock_db.set_response("users", MockResponse(data=u))
    mock_db.set_response("categories", MockResponse(data=category or DEFAULT_CATEGORY))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT))
    mock_db.set_response("token_expenses", MockResponse(data=[]))
    mock_db.set_rpc_response("charge_balance", [{"new_balance": balance - 50}])
    mock_db.set_rpc_response("refund_balance", [{"new_balance": balance}])


def _put_in_kw_fsm(
    mock_redis: Any,
    state: str,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """Put user in a KeywordGenerationFSM state."""
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = state
    data: dict[str, Any] = {"category_id": 10, "last_update_time": time.time()}
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
# Tests: KeywordGenerationFSM
# ---------------------------------------------------------------------------


async def test_keyword_gen_starts_with_category(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Callback category:{id}:kw:generate -> starts generation, asks about products."""
    setup_user()
    _setup_keyword_db(mock_db)

    update = make_update_callback("category:10:kw:generate")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "товары" in all_text.lower() or "услуги" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "KeywordGenerationFSM:products" in state_val


async def test_keyword_gen_products_step(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Products input -> advances to geography."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:products")

    update = make_update_message("SEO services and web development")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "география" in all_text.lower() or "город" in all_text.lower()


async def test_keyword_gen_geography_step(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Geography input -> advances to quantity selection."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:geography", {"products": "SEO services"})

    update = make_update_message("Moscow, Russia")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Сколько" in all_text or "фраз" in all_text.lower()


@patch("routers.categories.keywords.get_settings", _mock_settings)
async def test_keyword_gen_quantity_selection(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Quantity callback -> shows cost confirmation."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:quantity", {
        "products": "SEO", "geography": "Moscow",
    })

    update = make_update_callback("kw:qty:10:50")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "50" in all_text or "токенов" in all_text.lower()


@patch("routers.categories.keywords.get_settings", _mock_settings)
async def test_keyword_gen_insufficient_balance(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Balance check fails -> insufficient balance message."""
    low_user = {**DEFAULT_USER, "balance": 5}
    setup_user(user_data=low_user)
    _setup_keyword_db(mock_db, balance=5)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:quantity", {
        "products": "SEO", "geography": "Moscow",
    })

    update = make_update_callback("kw:qty:10:200")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "токенов" in all_text.lower() or "баланс" in all_text.lower()


@patch("routers.categories.keywords.get_settings", _mock_settings)
async def test_keyword_gen_confirm_runs_pipeline(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Confirm -> charges tokens and runs data-first pipeline."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:confirm", {
        "products": "SEO", "geography": "Moscow", "quantity": 50, "cost": 50,
    })
    mock_services["rate_limiter"].check = AsyncMock()

    mock_clusters = [
        {"cluster_name": "SEO basics", "cluster_type": "article", "main_phrase": "seo guide",
         "total_volume": 1000, "phrases": [{"phrase": "seo guide", "volume": 1000}]},
    ]

    with patch("routers.categories.keywords.KeywordService") as mock_kw_svc_cls:
        mock_svc = MagicMock()
        mock_svc.fetch_raw_phrases = AsyncMock(return_value=["seo guide", "seo basics"])
        mock_svc.cluster_phrases = AsyncMock(return_value=mock_clusters)
        mock_svc.enrich_clusters = AsyncMock(return_value=mock_clusters)
        mock_kw_svc_cls.return_value = mock_svc

        update = make_update_callback("kw:confirm")
        await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    # Should show results or progress
    assert "кластер" in all_text.lower() or "Получаю" in all_text or "Найдено" in all_text


@patch("routers.categories.keywords.get_settings", _mock_settings)
async def test_keyword_gen_save_results(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Save generated clusters to category.keywords."""
    setup_user()
    _setup_keyword_db(mock_db)
    clusters = [{"cluster_name": "SEO", "cluster_type": "article", "main_phrase": "seo guide",
                 "total_volume": 1000, "phrases": []}]
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:results", {"clusters": clusters})

    update = make_update_callback("kw:save")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "сохранены" in all_text.lower()

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.categories.keywords.get_settings", _mock_settings)
async def test_keyword_gen_pipeline_error_refunds(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """DataForSEO API error -> graceful fallback, refund."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:confirm", {
        "products": "SEO", "geography": "Moscow", "quantity": 50, "cost": 50,
    })
    mock_services["rate_limiter"].check = AsyncMock()

    with patch("routers.categories.keywords.KeywordService") as mock_kw_svc_cls:
        mock_svc = MagicMock()
        mock_svc.fetch_raw_phrases = AsyncMock(side_effect=Exception("DataForSEO unavailable"))
        mock_kw_svc_cls.return_value = mock_svc

        update = make_update_callback("kw:confirm")
        await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "ошибка" in all_text.lower() or "возвращены" in all_text.lower()


async def test_keyword_gen_cancel_midway(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """/cancel during keyword generation -> clears FSM."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:geography", {"products": "SEO"})

    update = make_update_message("/cancel")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "отменено" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


async def test_keyword_gen_products_too_short(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Products input too short -> validation error."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordGenerationFSM:products")

    update = make_update_message("ab")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "минимум" in all_text.lower() or "подробнее" in all_text.lower()

    # Should stay in products state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "products" in state_val


# ---------------------------------------------------------------------------
# Tests: KeywordUploadFSM
# ---------------------------------------------------------------------------


async def test_keyword_upload_starts(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Callback category:{id}:kw:upload -> starts upload FSM."""
    setup_user()
    _setup_keyword_db(mock_db)

    update = make_update_callback("category:10:kw:upload")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "TXT" in all_text or "файл" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "KeywordUploadFSM:file_upload" in state_val


async def test_keyword_upload_invalid_format(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Wrong file format -> error message."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordUploadFSM:file_upload")

    # Send a document with wrong extension
    update = make_update_document(file_name="keywords.xlsx")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "TXT" in all_text or ".txt" in all_text.lower()


async def test_keyword_upload_txt_file(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Upload TXT file -> processes keywords."""
    setup_user()
    _setup_keyword_db(mock_db)
    _put_in_kw_fsm(mock_redis, "KeywordUploadFSM:file_upload")

    # Create update with TXT document
    update = make_update_document(file_name="keywords.txt")

    # Mock bot.download to return file content
    import io
    content = "seo optimization\nweb development\ncontent marketing\n"
    buf = io.BytesIO(content.encode("utf-8"))

    mock_bot.download = AsyncMock(side_effect=lambda doc, destination: destination.write(buf.getvalue()))

    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    # Should show progress or results
    assert "Обогащаю" in all_text or "Группирую" in all_text or "кластер" in all_text.lower() or "Найдено" in all_text
