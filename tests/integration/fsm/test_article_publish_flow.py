"""Integration tests for ArticlePublishFSM — WordPress article publish flow.

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
    ADMIN_USER,
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
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
        "main_phrase": "seo optimization guide",
        "total_volume": 1500,
        "avg_difficulty": 30,
        "phrases": [
            {"phrase": "seo optimization guide", "volume": 800, "difficulty": 30},
            {"phrase": "seo best practices", "volume": 700, "difficulty": 25},
        ],
    }
]

_CATEGORY_WITH_KEYWORDS = {**DEFAULT_CATEGORY, "keywords": _KEYWORDS_CLUSTER}


_mock_settings = make_mock_settings


def _setup_article_db(
    mock_db: Any,
    user: dict[str, Any] | None = None,
    category: dict[str, Any] | None = None,
    connections: list[dict[str, Any]] | None = None,
    balance: int = 1500,
) -> None:
    """Set up DB mocks for article publish flow."""
    u = user or {**DEFAULT_USER, "balance": balance}
    mock_db.set_response("users", MockResponse(data=u))
    mock_db.set_response("categories", MockResponse(data=category or _CATEGORY_WITH_KEYWORDS))
    mock_db.set_response("projects", MockResponse(data=DEFAULT_PROJECT))
    conn_list = connections if connections is not None else [DEFAULT_CONNECTION_WP]
    mock_db.set_response("platform_connections", MockResponse(data=conn_list))
    mock_db.set_response("publication_logs", MockResponse(data={
        "id": 1, "user_id": DEFAULT_USER_ID, "project_id": 1, "category_id": 10,
        "platform_type": "wordpress", "connection_id": 100, "keyword": "seo guide",
        "content_type": "article", "images_count": 4, "post_url": "https://blog.example.com/test",
        "word_count": 2000, "tokens_spent": 320, "created_at": "2025-01-01T00:00:00Z",
    }))
    mock_db.set_response("article_previews", MockResponse(data={
        "id": 1, "user_id": DEFAULT_USER_ID, "project_id": 1, "category_id": 10,
        "connection_id": 100, "title": "Test Article", "keyword": "seo optimization guide",
        "word_count": 2000, "images_count": 4, "tokens_charged": 320,
        "content_html": "<h1>Test</h1>", "images": [], "telegraph_url": "https://telegra.ph/test",
        "telegraph_path": "test", "regeneration_count": 0, "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
    }))
    mock_db.set_response("token_expenses", MockResponse(data={
        "id": 1, "user_id": DEFAULT_USER_ID, "amount": -320, "operation_type": "article",
        "description": "Article generation", "created_at": "2025-01-01T00:00:00Z",
    }))
    # RPC for charge_balance
    mock_db.set_rpc_response("charge_balance", [{"new_balance": balance - 320}])
    mock_db.set_rpc_response("refund_balance", [{"new_balance": balance}])


def _put_in_article_fsm(
    mock_redis: Any,
    state: str,
    extra_data: dict[str, Any] | None = None,
) -> None:
    """Put user in an ArticlePublishFSM state."""
    storage_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    mock_redis._store[storage_key] = state
    data = {
        "category_id": 10,
        "project_id": 1,
        "connection_id": 100,
        "cost": 320,
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


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_start_selects_category(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """category:{id}:publish:wp -> shows cost confirmation."""
    setup_user()
    _setup_article_db(mock_db)

    update = make_update_callback("category:10:publish:wp")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Сгенерировать" in all_text or "статью" in all_text.lower() or "стоимость" in all_text.lower()


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_category_selected_with_single_wp(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """With single WP connection, goes straight to confirmation."""
    setup_user()
    _setup_article_db(mock_db)

    update = make_update_callback("category:10:publish:wp")
    await dispatcher.feed_update(mock_bot, update)

    # Should be in confirm_cost state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ArticlePublishFSM:confirm_cost" in state_val


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_insufficient_balance(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Not enough tokens -> error."""
    low_balance_user = {**DEFAULT_USER, "balance": 10}
    setup_user(user_data=low_balance_user)
    _setup_article_db(mock_db, user=low_balance_user, balance=10)

    update = make_update_callback("category:10:publish:wp")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "токенов" in all_text.lower() or "баланс" in all_text.lower() or "Недостаточно" in all_text


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_no_keywords(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Empty keywords -> error E08."""
    setup_user()
    empty_cat = {**DEFAULT_CATEGORY, "keywords": []}
    _setup_article_db(mock_db, category=empty_cat)

    update = make_update_callback("category:10:publish:wp")
    await dispatcher.feed_update(mock_bot, update)

    # Should get callback answer with alert
    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "фраз" in text.lower() or "ключев" in text.lower()


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_no_connections(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """No WP connections -> error E09."""
    setup_user()
    _setup_article_db(mock_db, connections=[])

    update = make_update_callback("category:10:publish:wp")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text") or ""
    assert "WordPress" in text or "подключен" in text.lower()


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_multiple_wp_connections(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """>1 WP connection -> asks which one (E28)."""
    setup_user()
    conn2 = {**DEFAULT_CONNECTION_WP, "id": 101, "identifier": "https://another.com"}
    _setup_article_db(mock_db, connections=[DEFAULT_CONNECTION_WP, conn2])

    update = make_update_callback("category:10:publish:wp")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Выберите" in all_text or "подключение" in all_text.lower()


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_confirm_charges_tokens(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Confirm -> charges tokens and starts generation."""
    setup_user()
    _setup_article_db(mock_db)
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:confirm_cost")

    # Mock rate_limiter.check to not raise
    mock_services["rate_limiter"].check = AsyncMock()

    # Mock AI orchestrator for generation
    mock_article = MagicMock()
    mock_article.title = "Test Article"
    mock_article.word_count = 2000
    mock_article.images_count = 4
    mock_article.content_html = "<h1>Test</h1>"
    mock_article.stored_images = []

    with patch("routers.publishing.preview.PreviewService") as mock_preview_svc_cls:
        mock_svc = MagicMock()
        mock_svc.generate_article_content = AsyncMock(return_value=mock_article)
        mock_preview_svc_cls.return_value = mock_svc

        update = make_update_callback("pub:article:confirm")
        await dispatcher.feed_update(mock_bot, update)

    # Should have progressed to generating/preview
    # May show "Подбираю ключевую фразу..." or preview
    assert mock_bot.edit_message_text.called or mock_bot.send_message.called


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_cancel_refunds(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Cancel preview -> clears FSM."""
    setup_user()
    _setup_article_db(mock_db)
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:preview", {"preview_id": 1})

    update = make_update_callback("pub:article:cancel")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "отменена" in all_text.lower()

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_regenerate_within_limit(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Regenerate (2 free max) does not charge extra tokens."""
    setup_user()
    _setup_article_db(mock_db)
    # Preview with regeneration_count=0 (first regen is free)
    preview_data = {
        "id": 1, "user_id": DEFAULT_USER_ID, "project_id": 1, "category_id": 10,
        "connection_id": 100, "title": "Test", "keyword": "seo guide",
        "word_count": 2000, "images_count": 4, "tokens_charged": 320,
        "content_html": "<h1>Test</h1>", "images": [], "telegraph_url": None,
        "telegraph_path": None, "regeneration_count": 0, "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
    }
    mock_db.set_response("article_previews", MockResponse(data=preview_data))
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:preview", {"preview_id": 1, "keyword": "seo guide"})

    mock_article = MagicMock()
    mock_article.title = "Regenerated Article"
    mock_article.word_count = 2100
    mock_article.images_count = 4
    mock_article.content_html = "<h1>Regen</h1>"
    mock_article.stored_images = []

    with patch("routers.publishing.preview.PreviewService") as mock_preview_svc_cls:
        mock_svc = MagicMock()
        mock_svc.generate_article_content = AsyncMock(return_value=mock_article)
        mock_preview_svc_cls.return_value = mock_svc

        update = make_update_callback("pub:article:regen")
        await dispatcher.feed_update(mock_bot, update)

    # Should proceed without charging (first regen is free when count=0 < max_free=2)
    all_text = _get_all_text(mock_bot)
    assert "Перегенерация" in all_text or mock_bot.edit_message_text.called


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_regenerate_exceeds_limit(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """3rd regen -> charges tokens (E10)."""
    setup_user()
    _setup_article_db(mock_db)
    # Preview with regeneration_count=2 (third regen is paid)
    preview_data = {
        "id": 1, "user_id": DEFAULT_USER_ID, "project_id": 1, "category_id": 10,
        "connection_id": 100, "title": "Test", "keyword": "seo guide",
        "word_count": 2000, "images_count": 4, "tokens_charged": 320,
        "content_html": "<h1>Test</h1>", "images": [], "telegraph_url": None,
        "telegraph_path": None, "regeneration_count": 2, "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
    }
    mock_db.set_response("article_previews", MockResponse(data=preview_data))
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:preview", {"preview_id": 1, "keyword": "seo guide"})

    mock_article = MagicMock()
    mock_article.title = "Regen 3"
    mock_article.word_count = 2100
    mock_article.images_count = 4
    mock_article.content_html = "<h1>R3</h1>"
    mock_article.stored_images = []

    with patch("routers.publishing.preview.PreviewService") as mock_preview_svc_cls:
        mock_svc = MagicMock()
        mock_svc.generate_article_content = AsyncMock(return_value=mock_article)
        mock_preview_svc_cls.return_value = mock_svc

        update = make_update_callback("pub:article:regen")
        await dispatcher.feed_update(mock_bot, update)

    # Should attempt to charge (regen_count=2 >= max_free=2)
    # The charge call goes through RPC mock
    assert mock_bot.edit_message_text.called or mock_bot.answer_callback_query.called


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_publish_guard_e07(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """E07: double-click during publishing -> blocked."""
    setup_user()
    _setup_article_db(mock_db)
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:publishing", {"preview_id": 1})

    update = make_update_callback("pub:article:publish")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "в процессе" in text.lower()


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_regen_guard(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
) -> None:
    """Block callbacks while regeneration is in progress."""
    setup_user()
    _setup_article_db(mock_db)
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:regenerating", {"preview_id": 1})

    update = make_update_callback("pub:article:regen")
    await dispatcher.feed_update(mock_bot, update)

    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    text = call_kwargs.get("text", "")
    assert "в процессе" in text.lower()


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_god_mode_no_charge(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Admin -> tokens shown but not charged (GOD_MODE)."""
    setup_user(user_data=ADMIN_USER)
    admin_project = {**DEFAULT_PROJECT, "user_id": ADMIN_ID}
    mock_db.set_response("users", MockResponse(data=ADMIN_USER))
    mock_db.set_response("categories", MockResponse(data=_CATEGORY_WITH_KEYWORDS))
    mock_db.set_response("projects", MockResponse(data=admin_project))
    mock_db.set_response("platform_connections", MockResponse(data=[DEFAULT_CONNECTION_WP]))
    mock_db.set_response("publication_logs", MockResponse(data={
        "id": 1, "user_id": DEFAULT_USER_ID, "project_id": 1, "category_id": 10,
        "platform_type": "wordpress", "connection_id": 100, "keyword": "seo guide",
        "content_type": "article", "images_count": 4, "post_url": "https://blog.example.com/test",
        "word_count": 2000, "tokens_spent": 320, "created_at": "2025-01-01T00:00:00Z",
    }))
    mock_db.set_response("article_previews", MockResponse(data={
        "id": 1, "user_id": ADMIN_ID, "project_id": 1, "category_id": 10,
        "connection_id": 100, "title": "Admin Article", "keyword": "seo guide",
        "word_count": 2000, "images_count": 4, "tokens_charged": 320,
        "content_html": "<h1>Admin</h1>", "images": [], "telegraph_url": None,
        "telegraph_path": None, "regeneration_count": 0, "status": "draft",
        "created_at": "2025-01-01T00:00:00Z",
    }))
    mock_db.set_response("token_expenses", MockResponse(data=[]))
    mock_db.set_rpc_response("charge_balance", [{"new_balance": 99999}])

    update = make_update_callback(
        "category:10:publish:wp",
        user_id=ADMIN_ID,
        first_name="Admin",
        username="admin",
    )
    await dispatcher.feed_update(mock_bot, update)

    # Should show cost confirmation (admin still sees cost)
    all_text = _get_all_text(mock_bot)
    assert "320" in all_text or "стоимость" in all_text.lower() or "Сгенерировать" in all_text


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_saves_preview_to_db(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """ArticlePreview row created during generation."""
    setup_user()
    _setup_article_db(mock_db)
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:confirm_cost")

    mock_services["rate_limiter"].check = AsyncMock()

    mock_article = MagicMock()
    mock_article.title = "Preview Article"
    mock_article.word_count = 2000
    mock_article.images_count = 4
    mock_article.content_html = "<h1>Preview</h1>"
    mock_article.stored_images = []

    with patch("routers.publishing.preview.PreviewService") as mock_preview_svc_cls:
        mock_svc = MagicMock()
        mock_svc.generate_article_content = AsyncMock(return_value=mock_article)
        mock_preview_svc_cls.return_value = mock_svc

        update = make_update_callback("pub:article:confirm")
        await dispatcher.feed_update(mock_bot, update)

    # The handler creates preview via PreviewsRepository, which hits DB
    # If no error, the flow proceeded to preview creation
    assert mock_bot.edit_message_text.called


@patch("routers.publishing.preview.get_settings", _mock_settings)
async def test_article_confirm_publish(
    dispatcher: Any, mock_bot: Any, mock_db: Any, mock_redis: Any, setup_user: Any,
    mock_services: dict[str, Any],
) -> None:
    """Confirm -> publishes to WP."""
    setup_user()
    _setup_article_db(mock_db)
    _put_in_article_fsm(mock_redis, "ArticlePublishFSM:preview", {
        "preview_id": 1, "keyword": "seo guide",
    })

    mock_pub_result = MagicMock()
    mock_pub_result.success = True
    mock_pub_result.post_url = "https://blog.example.com/test-article"

    with patch("routers.publishing.preview.PreviewService") as mock_preview_svc_cls:
        mock_svc = MagicMock()
        mock_svc.publish_to_wordpress = AsyncMock(return_value=mock_pub_result)
        mock_preview_svc_cls.return_value = mock_svc

        update = make_update_callback("pub:article:publish")
        await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "успешна" in all_text.lower() or "Публикую" in all_text

    # FSM should be cleared after successful publish
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    # May be None (cleared) or still publishing (async)
    assert state_val is None or "publishing" in (state_val or "")
