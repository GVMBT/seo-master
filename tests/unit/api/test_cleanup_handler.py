"""Tests for api/cleanup.py — QStash cleanup handler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from api.cleanup import cleanup_handler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(msg_id: str = "msg_1") -> MagicMock:
    """Create mock request."""
    app = MagicMock()
    redis_mock = MagicMock()
    redis_mock.set = AsyncMock(return_value="OK")

    settings_mock = MagicMock()
    settings_mock.admin_ids = [999]

    bot_mock = MagicMock()
    bot_mock.send_message = AsyncMock()

    app.__getitem__ = MagicMock(
        side_effect=lambda key: {
            "db": MagicMock(),
            "redis": redis_mock,
            "http_client": MagicMock(),
            "image_storage": MagicMock(),
            "settings": settings_mock,
            "bot": bot_mock,
        }[key]
    )

    request = MagicMock()
    request.app = app
    request.__getitem__ = MagicMock(
        side_effect=lambda k: {
            "verified_body": {"action": "cleanup"},
            "qstash_msg_id": msg_id,
        }[k]
    )

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("api.cleanup.CleanupService")
async def test_cleanup_happy_path(mock_svc_cls: MagicMock) -> None:
    """Successful cleanup returns 200."""
    from services.cleanup import CleanupResult

    mock_svc = MagicMock()
    mock_svc.execute = AsyncMock(
        return_value=CleanupResult(
            expired_count=2,
            refunded=[],
            logs_deleted=5,
        )
    )
    mock_svc_cls.return_value = mock_svc

    request = _make_request()
    resp = await cleanup_handler.__wrapped__(request)

    assert resp.status == 200


async def test_cleanup_idempotency() -> None:
    """Duplicate message ID returns 200 with duplicate."""
    request = _make_request()
    request.app["redis"].set = AsyncMock(return_value=None)

    resp = await cleanup_handler.__wrapped__(request)
    assert resp.status == 200


@patch("api.cleanup.CleanupService")
async def test_cleanup_notifies_users(mock_svc_cls: MagicMock) -> None:
    """Users with refunded previews receive notification."""
    from services.cleanup import CleanupResult

    mock_svc = MagicMock()
    mock_svc.execute = AsyncMock(
        return_value=CleanupResult(
            expired_count=1,
            refunded=[{"user_id": 1, "keyword": "seo", "tokens_refunded": 200, "notify_balance": True}],
        )
    )
    mock_svc_cls.return_value = mock_svc

    request = _make_request()
    resp = await cleanup_handler.__wrapped__(request)

    assert resp.status == 200
    request.app["bot"].send_message.assert_called_once()


@patch("api.cleanup.CleanupService")
async def test_cleanup_error_returns_200(mock_svc_cls: MagicMock) -> None:
    """Internal error still returns 200 (not to trigger QStash retry)."""
    mock_svc = MagicMock()
    mock_svc.execute = AsyncMock(side_effect=Exception("DB down"))
    mock_svc_cls.return_value = mock_svc

    request = _make_request()
    resp = await cleanup_handler.__wrapped__(request)

    assert resp.status == 200
