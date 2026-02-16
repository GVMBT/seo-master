"""Integration tests for POST /api/publish endpoint.

Tests QStash signature verification, idempotency, backpressure,
shutdown handling, and notification delivery.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.publish import _REASON_TEMPLATES
from services.publish import PublishOutcome

pytestmark = pytest.mark.integration

# Valid publish payload matching PublishPayload model
_VALID_PAYLOAD = {
    "schedule_id": 1,
    "category_id": 10,
    "connection_id": 20,
    "platform_type": "wordpress",
    "user_id": 12345,
    "project_id": 5,
}


def _make_headers(msg_id: str = "msg_001", signature: str = "valid_sig") -> dict[str, str]:
    """Build headers for QStash-signed requests."""
    return {
        "Upstash-Signature": signature,
        "Upstash-Message-Id": msg_id,
        "Content-Type": "application/json",
    }


async def test_publish_missing_signature_401(api_client):
    """POST /api/publish without Upstash-Signature returns 401."""
    resp = await api_client.post(
        "/api/publish",
        data=json.dumps(_VALID_PAYLOAD),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Missing signature" in text


async def test_publish_invalid_signature_401(api_client):
    """POST /api/publish with an invalid signature returns 401."""
    # The real Receiver.verify will raise because keys are fake
    resp = await api_client.post(
        "/api/publish",
        data=json.dumps(_VALID_PAYLOAD),
        headers=_make_headers(signature="bad_signature_value"),
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Invalid signature" in text


async def test_publish_valid_signature_processes(api_client, app_services):
    """POST /api/publish with valid (mocked) signature processes the payload."""
    outcome = PublishOutcome(status="ok", reason="", keyword="test seo", user_id=12345, notify=False)

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", asyncio.Event()),
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
        patch("api.publish.PublishService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=outcome)

        resp = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"


async def test_publish_idempotency_duplicate(api_client, app_services):
    """Second call with same Upstash-Message-Id returns status 'duplicate'."""
    outcome = PublishOutcome(status="ok", reason="", keyword="kw", user_id=12345, notify=False)

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", asyncio.Event()),
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
        patch("api.publish.PublishService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=outcome)

        headers = _make_headers(msg_id="dup_msg_123")

        # First call: should process
        resp1 = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=headers,
        )
        assert resp1.status == 200
        body1 = await resp1.json()
        assert body1["status"] == "ok"

        # Second call with same msg_id: duplicate
        resp2 = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=headers,
        )
        assert resp2.status == 200
        body2 = await resp2.json()
        assert body2["status"] == "duplicate"


async def test_publish_invalid_payload(api_client, app_services):
    """POST /api/publish with invalid body returns error status (not 4xx/5xx)."""
    bad_payload = {"not_a_valid_field": "value"}

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", asyncio.Event()),
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
    ):
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await api_client.post(
            "/api/publish",
            data=json.dumps(bad_payload),
            headers=_make_headers(msg_id="bad_payload_msg"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "error"
    assert body["reason"] == "invalid_payload"


async def test_publish_ok_notifies_user(api_client, app_services):
    """On successful publish with notify=True, bot.send_message is called."""
    outcome = PublishOutcome(
        status="ok",
        reason="",
        keyword="seo keyword",
        user_id=12345,
        notify=True,
        post_url="https://example.com/post/1",
    )

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", asyncio.Event()),
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
        patch("api.publish.PublishService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(return_value=outcome)

        resp = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="notify_msg"),
        )

    assert resp.status == 200
    bot = app_services["bot"]
    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args[0][0] == 12345  # user_id
    assert "seo keyword" in call_args[0][1]
    assert "https://example.com/post/1" in call_args[0][1]


async def test_publish_error_no_retry(api_client, app_services):
    """Internal error returns 200 (not 5xx) to prevent QStash retries."""
    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", asyncio.Event()),
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
        patch("api.publish.PublishService") as mock_svc_cls,
    ):
        mock_receiver_cls.return_value.verify = MagicMock()
        mock_svc_cls.return_value.execute = AsyncMock(side_effect=RuntimeError("boom"))

        resp = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="error_msg"),
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "error"
    assert body["reason"] == "internal_error"


async def test_publish_shutdown_503(api_client, app_services):
    """When SHUTDOWN_EVENT is set, handler returns 503 with Retry-After."""
    shutdown_event = asyncio.Event()
    shutdown_event.set()

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", shutdown_event),
        patch("bot.main.PUBLISH_SEMAPHORE", asyncio.Semaphore(10)),
    ):
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="shutdown_msg"),
        )

    assert resp.status == 503
    assert resp.headers.get("Retry-After") == "60"


async def test_publish_semaphore_timeout_503(api_client, app_services):
    """When semaphore acquire times out, handler returns 503."""
    # Patch the publish_handler to simulate TimeoutError inside the semaphore block.
    # We cannot globally patch asyncio.timeout because aiohttp client uses it too.
    # Instead, mock PUBLISH_SEMAPHORE as an async context manager that raises TimeoutError.
    mock_semaphore = MagicMock()
    mock_semaphore.__aenter__ = AsyncMock(side_effect=TimeoutError)
    mock_semaphore.__aexit__ = AsyncMock()

    with (
        patch("qstash.Receiver") as mock_receiver_cls,
        patch("bot.main.SHUTDOWN_EVENT", asyncio.Event()),
        patch("bot.main.PUBLISH_SEMAPHORE", mock_semaphore),
    ):
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await api_client.post(
            "/api/publish",
            data=json.dumps(_VALID_PAYLOAD),
            headers=_make_headers(msg_id="semaphore_msg"),
        )

    assert resp.status == 503
    assert resp.headers.get("Retry-After") == "120"


async def test_publish_reason_templates():
    """Verify _REASON_TEMPLATES has all expected reason keys."""
    expected_keys = {
        "insufficient_balance",
        "no_keywords",
        "connection_inactive",
        "content_validation_failed",
        "ai_service_unavailable",
    }
    assert set(_REASON_TEMPLATES.keys()) == expected_keys
    # All values should be non-empty strings
    for key, value in _REASON_TEMPLATES.items():
        assert isinstance(value, str), f"Template for {key} should be a string"
        assert len(value) > 10, f"Template for {key} should be meaningful text"
