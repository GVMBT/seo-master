"""Integration tests for require_qstash_signature decorator.

Tests the decorator directly using a simple aiohttp handler, verifying
signature verification, body parsing, and message ID extraction.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from api import require_qstash_signature

pytestmark = pytest.mark.integration


# A simple handler wrapped with the decorator, for testing in isolation.
@require_qstash_signature
async def _echo_handler(request: web.Request) -> web.Response:
    """Echo back the verified body and message ID."""
    return web.json_response({
        "body": request["verified_body"],
        "msg_id": request["qstash_msg_id"],
    })


@pytest.fixture
async def sig_client(mock_settings: MagicMock) -> Any:
    """Minimal aiohttp TestClient with _echo_handler for signature tests."""
    app = web.Application()
    app.router.add_post("/test", _echo_handler)
    app["settings"] = mock_settings
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    yield client
    await client.close()


async def test_decorator_missing_signature_header(sig_client):
    """Request without Upstash-Signature header returns 401."""
    resp = await sig_client.post(
        "/test",
        data=json.dumps({"key": "value"}),
        headers={"Content-Type": "application/json"},
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Missing signature" in text


async def test_decorator_empty_signature(sig_client):
    """Request with empty Upstash-Signature header returns 401."""
    resp = await sig_client.post(
        "/test",
        data=json.dumps({"key": "value"}),
        headers={
            "Content-Type": "application/json",
            "Upstash-Signature": "",
        },
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Missing signature" in text


async def test_decorator_invalid_signature(sig_client):
    """Request with invalid Upstash-Signature returns 401 'Invalid signature'."""
    # The real Receiver will fail because signing keys are fake
    resp = await sig_client.post(
        "/test",
        data=json.dumps({"key": "value"}),
        headers={
            "Content-Type": "application/json",
            "Upstash-Signature": "invalid_jwt_token_here",
        },
    )
    assert resp.status == 401
    text = await resp.text()
    assert "Invalid signature" in text


async def test_decorator_malformed_body(sig_client):
    """Valid signature but body is not valid JSON returns 401 'Malformed body'."""
    with patch("qstash.Receiver") as mock_receiver_cls:
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await sig_client.post(
            "/test",
            data=b"this is not json {{{",
            headers={
                "Content-Type": "application/json",
                "Upstash-Signature": "valid_sig",
            },
        )

    assert resp.status == 401
    text = await resp.text()
    assert "Malformed body" in text


async def test_decorator_valid_stores_body_and_msg_id(sig_client):
    """Valid signature stores parsed body as request['verified_body']."""
    payload = {"schedule_id": 42, "user_id": 100}

    with patch("qstash.Receiver") as mock_receiver_cls:
        mock_receiver_cls.return_value.verify = MagicMock()

        resp = await sig_client.post(
            "/test",
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Upstash-Signature": "valid_sig",
                "Upstash-Message-Id": "msg_abc_123",
            },
        )

    assert resp.status == 200
    body = await resp.json()
    assert body["body"] == payload
    assert body["msg_id"] == "msg_abc_123"


async def test_decorator_reads_message_id_header(sig_client):
    """Decorator reads Upstash-Message-Id header and stores it in request."""
    with patch("qstash.Receiver") as mock_receiver_cls:
        mock_receiver_cls.return_value.verify = MagicMock()

        # With explicit message ID
        resp = await sig_client.post(
            "/test",
            data=json.dumps({"data": 1}),
            headers={
                "Content-Type": "application/json",
                "Upstash-Signature": "valid_sig",
                "Upstash-Message-Id": "custom_msg_id_456",
            },
        )
    assert resp.status == 200
    body = await resp.json()
    assert body["msg_id"] == "custom_msg_id_456"

    # Without message ID header: should default to empty string
    with patch("qstash.Receiver") as mock_receiver_cls:
        mock_receiver_cls.return_value.verify = MagicMock()

        resp2 = await sig_client.post(
            "/test",
            data=json.dumps({"data": 2}),
            headers={
                "Content-Type": "application/json",
                "Upstash-Signature": "valid_sig",
            },
        )
    assert resp2.status == 200
    body2 = await resp2.json()
    assert body2["msg_id"] == ""
