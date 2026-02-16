"""Tests for api/publish.py — QStash auto-publish handler."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from api.publish import _build_notification_text, publish_handler
from services.publish import PublishOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    body: dict | None = None,
    msg_id: str = "msg_1",
) -> MagicMock:
    """Create mock request with verified_body and qstash_msg_id pre-set."""
    if body is None:
        body = {
            "schedule_id": 1,
            "category_id": 10,
            "connection_id": 5,
            "platform_type": "wordpress",
            "user_id": 1,
            "project_id": 1,
            "idempotency_key": "pub_1_09:00",
        }

    app = MagicMock()
    redis_mock = MagicMock()
    redis_mock.set = AsyncMock(return_value="OK")
    redis_mock.delete = AsyncMock(return_value=1)

    settings_mock = MagicMock()
    settings_mock.admin_ids = [999]

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    scheduler_mock = MagicMock()
    scheduler_mock.delete_qstash_schedules = AsyncMock()

    app_store = {
        "db": MagicMock(),
        "redis": redis_mock,
        "http_client": MagicMock(),
        "ai_orchestrator": MagicMock(),
        "image_storage": MagicMock(),
        "settings": settings_mock,
        "bot": bot_mock,
        "scheduler_service": scheduler_mock,
    }
    app.__getitem__ = MagicMock(side_effect=lambda key: app_store[key])
    app.get = MagicMock(side_effect=lambda key, default=None: app_store.get(key, default))

    request = MagicMock()
    request.app = app
    request.__getitem__ = MagicMock(
        side_effect=lambda k: {
            "verified_body": body,
            "qstash_msg_id": msg_id,
        }[k]
    )

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("bot.main.SHUTDOWN_EVENT", new_callable=lambda: type("", (), {"is_set": lambda self: False})())
@patch("bot.main.PUBLISH_SEMAPHORE", new_callable=lambda: asyncio.Semaphore(10))
@patch("api.publish.PublishService")
async def test_publish_happy_path(
    mock_svc_cls: MagicMock,
    *args,
) -> None:
    """Successful publish returns 200 with ok status."""
    from services.publish import PublishOutcome

    mock_svc = MagicMock()
    mock_svc.execute = AsyncMock(
        return_value=PublishOutcome(
            status="ok",
            keyword="test",
            user_id=1,
            notify=False,
        )
    )
    mock_svc_cls.return_value = mock_svc

    request = _make_request()
    # Need to unwrap the decorated function
    resp = await publish_handler.__wrapped__(request)

    assert resp.status == 200


@patch("bot.main.SHUTDOWN_EVENT")
async def test_publish_shutdown_503(mock_event: MagicMock) -> None:
    """Shutdown event returns 503."""
    mock_event.is_set.return_value = True

    request = _make_request()
    resp = await publish_handler.__wrapped__(request)

    assert resp.status == 503


async def test_publish_idempotency_duplicate() -> None:
    """Duplicate message ID returns 200 with duplicate status."""
    request = _make_request()
    # Simulate lock not acquired (duplicate)
    request.app["redis"].set = AsyncMock(return_value=None)

    with patch("bot.main.SHUTDOWN_EVENT") as mock_event:
        mock_event.is_set.return_value = False
        resp = await publish_handler.__wrapped__(request)

    assert resp.status == 200


async def test_publish_invalid_payload() -> None:
    """Invalid payload returns 200 with error."""
    request = _make_request(body={"invalid": "data"})

    with (
        patch("bot.main.SHUTDOWN_EVENT") as mock_event,
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
    ):
        mock_event.is_set.return_value = False
        resp = await publish_handler.__wrapped__(request)

    assert resp.status == 200


# ---------------------------------------------------------------------------
# Notification text templates (EDGE_CASES.md)
# ---------------------------------------------------------------------------


def test_notification_text_ok() -> None:
    """Success notification includes keyword and post_url."""
    result = PublishOutcome(status="ok", keyword="seo tips", post_url="https://test.com/seo")
    text = _build_notification_text(result)
    assert "seo tips" in text
    assert "https://test.com/seo" in text
    assert "выполнена" in text.lower()


def test_notification_text_insufficient_balance() -> None:
    """Insufficient balance uses Russian template."""
    result = PublishOutcome(status="error", reason="insufficient_balance")
    text = _build_notification_text(result)
    assert "токенов" in text.lower()
    assert "приостановлено" in text.lower()


def test_notification_text_no_keywords() -> None:
    """No keywords uses Russian template per E17."""
    result = PublishOutcome(status="error", reason="no_keywords")
    text = _build_notification_text(result)
    assert "ключевых фраз" in text.lower()


def test_notification_text_connection_inactive() -> None:
    """Connection inactive uses Russian template."""
    result = PublishOutcome(status="error", reason="connection_inactive")
    text = _build_notification_text(result)
    assert "платформа" in text.lower()


def test_notification_text_unknown_reason() -> None:
    """Unknown reason falls back to generic message."""
    result = PublishOutcome(status="error", reason="something_weird")
    text = _build_notification_text(result)
    assert "something_weird" in text
