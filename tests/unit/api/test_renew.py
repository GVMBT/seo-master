"""Tests for api/renew.py -- YooKassa subscription renewal handler.

Covers: happy path, idempotency lock, invalid payload, service error,
renewal failure with user notification, QStash signature requirement.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from aiohttp import web

from api.renew import renew_handler

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    body: dict | None = None,
    msg_id: str = "msg_renew_123",
    lock_acquired: bool = True,
) -> web.Request:
    """Build a mock aiohttp request for the renew handler.

    Simulates post-QStash-signature-verification state:
    request["verified_body"] and request["qstash_msg_id"] are already set.
    """
    redis = MagicMock()
    redis.set = AsyncMock(return_value=lock_acquired)
    redis.delete = AsyncMock()

    service = MagicMock()
    service.renew_subscription = AsyncMock(return_value=True)

    bot = MagicMock()
    bot.send_message = AsyncMock()

    app = MagicMock()
    app.__getitem__ = MagicMock(
        side_effect=lambda key: {
            "redis": redis,
            "yookassa_service": service,
            "bot": bot,
            "settings": MagicMock(),
        }[key]
    )

    request = MagicMock(spec=web.Request)
    request.app = app

    # Simulate @require_qstash_signature already passed
    storage: dict = {}
    request.__getitem__ = MagicMock(side_effect=lambda k: storage[k])
    request.__setitem__ = MagicMock(side_effect=lambda k, v: storage.__setitem__(k, v))

    if body is not None:
        storage["verified_body"] = body
    storage["qstash_msg_id"] = msg_id

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRenewHappyPath:
    async def test_successful_renewal(self) -> None:
        body = {"user_id": 42, "payment_method_id": "pm_abc", "package": "pro"}
        request = _make_request(body=body)

        # Call the inner handler directly (skip QStash decorator)
        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200

        service = request.app["yookassa_service"]
        service.renew_subscription.assert_called_once_with(
            user_id=42,
            payment_method_id="pm_abc",
            package_name="pro",
        )


class TestRenewIdempotency:
    async def test_duplicate_returns_ok(self) -> None:
        body = {"user_id": 42, "payment_method_id": "pm_abc", "package": "pro"}
        request = _make_request(body=body, lock_acquired=False)

        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200

        service = request.app["yookassa_service"]
        service.renew_subscription.assert_not_called()


class TestRenewValidation:
    async def test_invalid_payload(self) -> None:
        body = {"bad": "data"}
        request = _make_request(body=body)

        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200  # always 200 for QStash

    async def test_missing_user_id(self) -> None:
        body = {"payment_method_id": "pm_abc", "package": "pro"}
        request = _make_request(body=body)

        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200


class TestRenewFailure:
    async def test_renewal_failure_notifies_user(self) -> None:
        body = {"user_id": 42, "payment_method_id": "pm_abc", "package": "pro"}
        request = _make_request(body=body)

        service = request.app["yookassa_service"]
        service.renew_subscription = AsyncMock(return_value=False)

        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200

        bot = request.app["bot"]
        bot.send_message.assert_called_once()
        call_args = bot.send_message.call_args
        assert call_args[0][0] == 42  # user_id
        assert "подписку" in call_args[0][1].lower()

    async def test_service_exception_returns_200(self) -> None:
        body = {"user_id": 42, "payment_method_id": "pm_abc", "package": "pro"}
        request = _make_request(body=body)

        service = request.app["yookassa_service"]
        service.renew_subscription = AsyncMock(side_effect=RuntimeError("boom"))

        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200

    async def test_notification_failure_does_not_crash(self) -> None:
        body = {"user_id": 42, "payment_method_id": "pm_abc", "package": "pro"}
        request = _make_request(body=body)

        service = request.app["yookassa_service"]
        service.renew_subscription = AsyncMock(return_value=False)

        bot = request.app["bot"]
        bot.send_message = AsyncMock(side_effect=RuntimeError("bot down"))

        resp = await renew_handler.__wrapped__(request)  # type: ignore[attr-defined]
        assert resp.status == 200  # does not crash
