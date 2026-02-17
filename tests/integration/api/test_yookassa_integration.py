"""Integration tests for POST /api/yookassa/webhook endpoint.

Tests IP whitelist verification, payload validation, event processing,
and notification delivery.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

pytestmark = pytest.mark.integration

_VALID_PAYMENT_BODY = {
    "event": "payment.succeeded",
    "object": {
        "id": "yoo_pay_123",
        "metadata": {
            "user_id": "12345",
            "package_name": "start",
            "tokens_amount": "500",
        },
        "amount": {"value": "990.00", "currency": "RUB"},
    },
}

# An IP from YooKassa whitelist: 185.71.76.0/27 contains 185.71.76.1
_WHITELISTED_IP = "185.71.76.1"
_NON_WHITELISTED_IP = "1.2.3.4"


async def test_yookassa_rejects_invalid_ip(api_client):
    """POST from non-whitelisted IP returns 403 Forbidden."""
    resp = await api_client.post(
        "/api/yookassa/webhook",
        data=json.dumps(_VALID_PAYMENT_BODY),
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _NON_WHITELISTED_IP,
        },
    )
    assert resp.status == 403
    text = await resp.text()
    assert "Forbidden" in text


async def test_yookassa_accepts_valid_ip(api_client, app_services):
    """POST from whitelisted IP is accepted and processed."""
    yookassa_svc = app_services["yookassa_service"]
    yookassa_svc.process_webhook = AsyncMock(return_value=None)

    resp = await api_client.post(
        "/api/yookassa/webhook",
        data=json.dumps(_VALID_PAYMENT_BODY),
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _WHITELISTED_IP,
        },
    )
    assert resp.status == 200
    yookassa_svc.process_webhook.assert_called_once_with(
        "payment.succeeded",
        _VALID_PAYMENT_BODY["object"],
    )


async def test_yookassa_invalid_json_400(api_client):
    """POST with invalid JSON body returns 400."""
    resp = await api_client.post(
        "/api/yookassa/webhook",
        data="not valid json {{{",
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _WHITELISTED_IP,
        },
    )
    assert resp.status == 400
    text = await resp.text()
    assert "Invalid JSON" in text


async def test_yookassa_missing_event_200(api_client, app_services):
    """POST with body missing 'event' field returns 200 (no retry, per spec)."""
    body_no_event = {"some_field": "value"}

    resp = await api_client.post(
        "/api/yookassa/webhook",
        data=json.dumps(body_no_event),
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _WHITELISTED_IP,
        },
    )
    assert resp.status == 200
    # Service should NOT be called — missing event/object
    yookassa_svc = app_services["yookassa_service"]
    yookassa_svc.process_webhook.assert_not_called()


async def test_yookassa_payment_succeeded(api_client, app_services):
    """event='payment.succeeded' delegates to service.process_webhook."""
    yookassa_svc = app_services["yookassa_service"]
    yookassa_svc.process_webhook = AsyncMock(return_value=None)

    resp = await api_client.post(
        "/api/yookassa/webhook",
        data=json.dumps(_VALID_PAYMENT_BODY),
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _WHITELISTED_IP,
        },
    )
    assert resp.status == 200
    text = await resp.text()
    assert text == "OK"

    yookassa_svc.process_webhook.assert_called_once_with(
        "payment.succeeded",
        _VALID_PAYMENT_BODY["object"],
    )


async def test_yookassa_notifies_user(api_client, app_services):
    """When service returns notification dict, bot.send_message is called."""
    notification = {
        "user_id": 12345,
        "text": "Payment canceled. Try another method.",
    }
    yookassa_svc = app_services["yookassa_service"]
    yookassa_svc.process_webhook = AsyncMock(return_value=notification)

    canceled_body = {
        "event": "payment.canceled",
        "object": {
            "id": "yoo_pay_456",
            "metadata": {"user_id": "12345", "package_name": "start"},
        },
    }

    resp = await api_client.post(
        "/api/yookassa/webhook",
        data=json.dumps(canceled_body),
        headers={
            "Content-Type": "application/json",
            "X-Forwarded-For": _WHITELISTED_IP,
        },
    )
    assert resp.status == 200

    bot = app_services["bot"]
    bot.send_message.assert_called_once_with(12345, "Payment canceled. Try another method.")
