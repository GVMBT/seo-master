"""Integration tests for POST /api/notify endpoint.

Tests QStash signature verification, idempotency, notification types,
and error handling for unknown notification types.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

_LOW_BALANCE_PAYLOAD = {"action": "notify", "type": "low_balance"}


def _make_headers(msg_id: str = "notify_001", signature: str = "valid_sig") -> dict[str, str]:
    """Build headers for QStash-signed requests."""
    return {
        "Upstash-Signature": signature,
        "Upstash-Message-Id": msg_id,
        "Content-Type": "application/json",
    }


async def test_notify_missing_signature_401(api_client):
    """POST /api/notify without Upstash-Signature returns 401."""
    resp = await api_client.post(
        "/api/notify",
        data=json.dumps(_LOW_BALANCE_PAYLOAD),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Missing signature" in text


async def test_notify_idempotency_duplicate(api_client, app_services):
    """Second call with same Upstash-Message-Id returns status 'duplicate'."""
    recipients = [(111, "<b>Low balance</b>")]

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("api.notify.NotifyService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.build_low_balance = AsyncMock(return_value=recipients)

        headers = _make_headers(msg_id="notify_dup_msg")

        # First call
        resp1 = await api_client.post(
            "/api/notify",
            data=json.dumps(_LOW_BALANCE_PAYLOAD),
            headers=headers,
        )
        assert resp1.status == 200
        body1 = await resp1.json()
        assert body1["status"] == "ok"

        # Second call with same msg_id
        resp2 = await api_client.post(
            "/api/notify",
            data=json.dumps(_LOW_BALANCE_PAYLOAD),
            headers=headers,
        )
        assert resp2.status == 200
        body2 = await resp2.json()
        assert body2["status"] == "duplicate"


async def test_notify_low_balance_sends(api_client, app_services):
    """type='low_balance' builds recipient list and sends messages."""
    recipients = [
        (100, "<b>Баланс: 50 токенов</b>\nПополните баланс."),
        (200, "<b>Баланс: 30 токенов</b>\nПополните баланс."),
    ]

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("api.notify.NotifyService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.build_low_balance = AsyncMock(return_value=recipients)

        resp = await api_client.post(
            "/api/notify",
            data=json.dumps(_LOW_BALANCE_PAYLOAD),
            headers=_make_headers(msg_id="notify_low_bal"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert body["type"] == "low_balance"
    assert body["sent"] == 2
    assert body["failed"] == 0

    bot = app_services["bot"]
    assert bot.send_message.call_count == 2
    # Verify first recipient received the message
    first_call = bot.send_message.call_args_list[0]
    assert first_call[0][0] == 100
    assert first_call[1]["parse_mode"] == "HTML"


async def test_notify_unknown_type_error(api_client, app_services):
    """Payload with unrecognized type is rejected by Pydantic validation."""
    bad_payload = {"action": "notify", "type": "nonexistent_type"}

    with patch("qstash.Receiver") as mock_receiver_cls:
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await api_client.post(
            "/api/notify",
            data=json.dumps(bad_payload),
            headers=_make_headers(msg_id="notify_unknown"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "error"
    assert body["reason"] == "invalid_payload"
