"""Integration tests for POST /api/cleanup endpoint.

Tests QStash signature verification, idempotency, and notification delivery
for expired preview refunds.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.cleanup import CleanupResult

pytestmark = pytest.mark.integration

_VALID_PAYLOAD = {"action": "cleanup"}


def _make_headers(msg_id: str = "cleanup_001", signature: str = "valid_sig") -> dict[str, str]:
    """Build headers for QStash-signed requests."""
    return {
        "Upstash-Signature": signature,
        "Upstash-Message-Id": msg_id,
        "Content-Type": "application/json",
    }


async def test_cleanup_missing_signature_401(api_client):
    """POST /api/cleanup without Upstash-Signature returns 401."""
    resp = await api_client.post(
        "/api/cleanup",
        data=json.dumps(_VALID_PAYLOAD),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Missing signature" in text


async def test_cleanup_idempotency_duplicate(api_client, app_services):
    """Second call with same Upstash-Message-Id returns status 'duplicate'."""
    result = CleanupResult(expired_count=1, refunded=[], logs_deleted=5, images_deleted=0)

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("api.cleanup.CleanupService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=result)

        headers = _make_headers(msg_id="cleanup_dup_msg")

        # First call
        resp1 = await api_client.post(
            "/api/cleanup",
            data=json.dumps(_VALID_PAYLOAD),
            headers=headers,
        )
        assert resp1.status == 200
        body1 = await resp1.json()
        assert body1["status"] == "ok"

        # Second call with same msg_id
        resp2 = await api_client.post(
            "/api/cleanup",
            data=json.dumps(_VALID_PAYLOAD),
            headers=headers,
        )
        assert resp2.status == 200
        body2 = await resp2.json()
        assert body2["status"] == "duplicate"


async def test_cleanup_valid_processes(api_client, app_services):
    """POST /api/cleanup with valid signature processes and returns result."""
    result = CleanupResult(expired_count=3, refunded=[], logs_deleted=10, images_deleted=2)

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("api.cleanup.CleanupService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=result)

        resp = await api_client.post(
            "/api/cleanup",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="cleanup_ok"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert body["expired"] == 3
    assert body["refunds"] == 0
    assert body["logs_deleted"] == 10


async def test_cleanup_invalid_payload(api_client, app_services):
    """POST /api/cleanup with invalid body returns error (not exception)."""
    bad_payload = {"action": "invalid_action_value"}

    with patch("qstash.Receiver") as mock_receiver_cls:
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await api_client.post(
            "/api/cleanup",
            data=json.dumps(bad_payload),
            headers=_make_headers(msg_id="cleanup_bad"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "error"
    assert body["reason"] == "invalid_payload"


async def test_cleanup_notifies_users_about_refunds(api_client, app_services):
    """When cleanup refunds tokens, bot.send_message is called for users with notify_balance=True."""
    refund_entries = [
        {
            "user_id": 111,
            "keyword": "seo optimization",
            "tokens_refunded": 200,
            "notify_balance": True,
        },
        {
            "user_id": 222,
            "keyword": "content marketing",
            "tokens_refunded": 150,
            "notify_balance": True,
        },
    ]
    result = CleanupResult(expired_count=2, refunded=refund_entries, logs_deleted=0, images_deleted=0)

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("api.cleanup.CleanupService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=result)

        resp = await api_client.post(
            "/api/cleanup",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="cleanup_refund_notify"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["refunds"] == 2

    bot = app_services["bot"]
    assert bot.send_message.call_count == 2

    # Verify first notification content
    first_call = bot.send_message.call_args_list[0]
    assert first_call[0][0] == 111
    assert "seo optimization" in first_call[0][1]
    assert "200" in first_call[0][1]

    # Verify second notification content
    second_call = bot.send_message.call_args_list[1]
    assert second_call[0][0] == 222


async def test_cleanup_skips_notification_when_disabled(api_client, app_services):
    """Users with notify_balance=False should NOT receive cleanup notifications."""
    refund_entries = [
        {
            "user_id": 333,
            "keyword": "web development",
            "tokens_refunded": 100,
            "notify_balance": False,  # notifications disabled
        },
        {
            "user_id": 444,
            "keyword": "seo audit",
            "tokens_refunded": 300,
            "notify_balance": True,  # notifications enabled
        },
    ]
    result = CleanupResult(expired_count=2, refunded=refund_entries, logs_deleted=0, images_deleted=0)

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("api.cleanup.CleanupService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=result)

        resp = await api_client.post(
            "/api/cleanup",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="cleanup_skip_notify"),
        )

    assert resp.status == 200
    bot = app_services["bot"]
    # Only user 444 should be notified (notify_balance=True)
    assert bot.send_message.call_count == 1
    assert bot.send_message.call_args[0][0] == 444
