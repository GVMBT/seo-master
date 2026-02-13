"""Tests for api/yookassa.py — YooKassa webhook aiohttp handler.

Covers: IP whitelist verification, JSON parsing, event routing,
always-200 response, error handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from api.yookassa import yookassa_webhook

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    body: dict | None = None,
    client_ip: str = "185.71.76.1",
    x_forwarded_for: str = "",
) -> web.Request:
    """Create a mock aiohttp request for YooKassa webhook."""
    mock_service = MagicMock()
    mock_service.process_webhook = AsyncMock()

    app = MagicMock()
    app.__getitem__ = MagicMock(side_effect=lambda key: {
        "db": MagicMock(),
        "http_client": MagicMock(),
        "yookassa_service": mock_service,
    }[key])

    headers = {}
    if x_forwarded_for:
        headers["X-Forwarded-For"] = x_forwarded_for

    request = make_mocked_request(
        "POST",
        "/api/yookassa/webhook",
        app=app,
        headers=headers,
    )
    # Override remote to simulate client IP
    request = MagicMock(wraps=request)
    request.remote = client_ip
    request.app = app
    request.headers = MagicMock()
    request.headers.get = MagicMock(side_effect=lambda k, d="": x_forwarded_for if k == "X-Forwarded-For" else d)

    if body is not None:
        request.json = AsyncMock(return_value=body)
    else:
        request.json = AsyncMock(side_effect=json.JSONDecodeError("err", "doc", 0))

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestIpVerification:
    async def test_rejects_non_whitelisted_ip(self) -> None:
        request = _make_request(
            body={"event": "payment.succeeded", "object": {}},
            client_ip="1.2.3.4",
        )
        resp = await yookassa_webhook(request)
        assert resp.status == 403

    async def test_accepts_whitelisted_ip(self) -> None:
        request = _make_request(
            body={"event": "payment.succeeded", "object": {"id": "yk_1", "metadata": {}}},
            x_forwarded_for="185.71.76.1",
        )
        resp = await yookassa_webhook(request)
        assert resp.status == 200

    async def test_uses_x_forwarded_for_first(self) -> None:
        """X-Forwarded-For should be preferred over request.remote."""
        request = _make_request(
            body={"event": "payment.succeeded", "object": {}},
            client_ip="185.71.76.1",  # Valid IP
            x_forwarded_for="1.2.3.4",  # Invalid IP takes precedence
        )
        resp = await yookassa_webhook(request)
        assert resp.status == 403


class TestJsonParsing:
    async def test_invalid_json_returns_400(self) -> None:
        request = _make_request(body=None, x_forwarded_for="185.71.76.1")
        resp = await yookassa_webhook(request)
        assert resp.status == 400


class TestEventRouting:
    async def test_delegates_to_service(self) -> None:
        body = {"event": "payment.succeeded", "object": {"id": "yk_test"}}
        request = _make_request(body=body, x_forwarded_for="185.71.76.1")
        resp = await yookassa_webhook(request)
        assert resp.status == 200
        service = request.app["yookassa_service"]
        service.process_webhook.assert_called_once_with("payment.succeeded", {"id": "yk_test"})

    async def test_missing_event_returns_200(self) -> None:
        """Missing event should still return 200 (don't trigger retries)."""
        request = _make_request(body={"data": "something"}, x_forwarded_for="185.71.76.1")
        resp = await yookassa_webhook(request)
        assert resp.status == 200

    async def test_service_error_still_returns_200(self) -> None:
        """Service exceptions should not cause non-200 response."""
        request = _make_request(
            body={"event": "payment.succeeded", "object": {"id": "yk_err"}},
            x_forwarded_for="185.71.76.1",
        )
        service = request.app["yookassa_service"]
        service.process_webhook = AsyncMock(side_effect=RuntimeError("boom"))
        resp = await yookassa_webhook(request)
        assert resp.status == 200
