"""Tests for api/notify.py — QStash notification handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from api.notify import _send_notifications, notify_handler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(notify_type: str = "low_balance", msg_id: str = "msg_1") -> MagicMock:
    app = MagicMock()
    redis_mock = MagicMock()
    redis_mock.set = AsyncMock(return_value="OK")

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    app.__getitem__ = MagicMock(side_effect=lambda key: {
        "db": MagicMock(),
        "redis": redis_mock,
        "bot": bot_mock,
        "settings": MagicMock(),
    }[key])

    request = MagicMock()
    request.app = app
    request.__getitem__ = MagicMock(side_effect=lambda k: {
        "verified_body": {"action": "notify", "type": notify_type},
        "qstash_msg_id": msg_id,
    }[k])

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("api.notify.NotifyService")
async def test_notify_low_balance(mock_svc_cls: MagicMock) -> None:
    """Low balance notification sends to matching users."""
    mock_svc = MagicMock()
    mock_svc.build_low_balance = AsyncMock(return_value=[(1, "Low balance!")])
    mock_svc_cls.return_value = mock_svc

    request = _make_request(notify_type="low_balance")
    resp = await notify_handler.__wrapped__(request)

    assert resp.status == 200


@patch("api.notify.NotifyService")
async def test_notify_weekly_digest(mock_svc_cls: MagicMock) -> None:
    """Weekly digest notification."""
    mock_svc = MagicMock()
    mock_svc.build_weekly_digest = AsyncMock(return_value=[(1, "Digest!")])
    mock_svc_cls.return_value = mock_svc

    request = _make_request(notify_type="weekly_digest")
    resp = await notify_handler.__wrapped__(request)

    assert resp.status == 200


@patch("api.notify.NotifyService")
async def test_notify_reactivation(mock_svc_cls: MagicMock) -> None:
    """Reactivation notification."""
    mock_svc = MagicMock()
    mock_svc.build_reactivation = AsyncMock(return_value=[(1, "Come back!")])
    mock_svc_cls.return_value = mock_svc

    request = _make_request(notify_type="reactivation")
    resp = await notify_handler.__wrapped__(request)

    assert resp.status == 200


async def test_notify_idempotency() -> None:
    """Duplicate message ID returns duplicate."""
    request = _make_request()
    request.app["redis"].set = AsyncMock(return_value=None)

    resp = await notify_handler.__wrapped__(request)
    assert resp.status == 200


# ---------------------------------------------------------------------------
# _send_notifications
# ---------------------------------------------------------------------------


async def test_send_notifications_happy() -> None:
    """All messages sent successfully."""
    bot = MagicMock()
    bot.send_message = AsyncMock()

    sent, failed = await _send_notifications(bot, [(1, "Hello"), (2, "World")])

    assert sent == 2
    assert failed == 0


async def test_send_notifications_forbidden() -> None:
    """TelegramForbiddenError counts as failed."""
    from aiogram.exceptions import TelegramForbiddenError

    bot = MagicMock()
    bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(method=MagicMock(), message="Forbidden"))

    sent, failed = await _send_notifications(bot, [(1, "Hello")])

    assert sent == 0
    assert failed == 1


async def test_send_notifications_retry_after() -> None:
    """TelegramRetryAfter triggers retry after sleep."""
    from aiogram.exceptions import TelegramRetryAfter

    bot = MagicMock()
    err = TelegramRetryAfter(method=MagicMock(), message="Too many", retry_after=0)
    bot.send_message = AsyncMock(side_effect=[err, None])

    sent, failed = await _send_notifications(bot, [(1, "Hello")])

    assert sent == 1
    assert failed == 0
