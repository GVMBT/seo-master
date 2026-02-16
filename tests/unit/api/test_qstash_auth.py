"""Tests for api/__init__.py — require_qstash_signature decorator.

Covers: valid signature, invalid signature, missing header, malformed body.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp import web

from api import require_qstash_signature

# ---------------------------------------------------------------------------
# Dummy handler for decoration
# ---------------------------------------------------------------------------


@require_qstash_signature
async def _sample_handler(request: web.Request) -> web.Response:
    """Sample handler that echoes verified body."""
    return web.json_response(request["verified_body"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings() -> MagicMock:
    """Create mock Settings with QStash signing keys."""
    s = MagicMock()
    s.qstash_current_signing_key.get_secret_value.return_value = "current_key"
    s.qstash_next_signing_key.get_secret_value.return_value = "next_key"
    return s


def _make_request(
    body: bytes = b'{"action": "test"}',
    signature: str = "valid_sig",
    msg_id: str = "msg_123",
    include_signature: bool = True,
) -> MagicMock:
    """Create a mock aiohttp request."""
    app = MagicMock()
    app.__getitem__ = MagicMock(
        side_effect=lambda key: {
            "settings": _make_settings(),
        }[key]
    )

    request = MagicMock()
    request.app = app
    request.read = AsyncMock(return_value=body)
    request.url = "https://example.com/api/publish"

    headers = {}
    if include_signature:
        headers["Upstash-Signature"] = signature
    headers["Upstash-Message-Id"] = msg_id

    request.headers = MagicMock()
    request.headers.get = MagicMock(side_effect=lambda k, d="": headers.get(k, d))

    # Support dict-style assignment
    storage: dict = {}
    request.__setitem__ = MagicMock(side_effect=lambda k, v: storage.__setitem__(k, v))
    request.__getitem__ = MagicMock(side_effect=lambda k: storage[k])

    return request


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("qstash.Receiver")
async def test_valid_signature(mock_receiver_cls: MagicMock) -> None:
    """Valid QStash signature: handler receives verified_body and qstash_msg_id."""
    mock_receiver = MagicMock()
    mock_receiver.verify = MagicMock()  # No exception = valid
    mock_receiver_cls.return_value = mock_receiver

    request = _make_request()
    resp = await _sample_handler(request)

    assert resp.status == 200
    mock_receiver.verify.assert_called_once()
    request.__setitem__.assert_any_call("verified_body", {"action": "test"})
    request.__setitem__.assert_any_call("qstash_msg_id", "msg_123")


@patch("qstash.Receiver")
async def test_invalid_signature(mock_receiver_cls: MagicMock) -> None:
    """Invalid signature returns 401."""
    mock_receiver = MagicMock()
    mock_receiver.verify = MagicMock(side_effect=Exception("bad sig"))
    mock_receiver_cls.return_value = mock_receiver

    request = _make_request()
    resp = await _sample_handler(request)

    assert resp.status == 401
    assert "Invalid signature" in resp.text


async def test_missing_signature_header() -> None:
    """Missing Upstash-Signature header returns 401."""
    request = _make_request(include_signature=False)
    resp = await _sample_handler(request)

    assert resp.status == 401
    assert "Missing signature" in resp.text


@patch("qstash.Receiver")
async def test_malformed_body(mock_receiver_cls: MagicMock) -> None:
    """Malformed JSON body returns 401."""
    mock_receiver = MagicMock()
    mock_receiver.verify = MagicMock()
    mock_receiver_cls.return_value = mock_receiver

    request = _make_request(body=b"not json{{{")
    resp = await _sample_handler(request)

    assert resp.status == 401
    assert "Malformed body" in resp.text


@patch("qstash.Receiver")
async def test_empty_msg_id_defaults(mock_receiver_cls: MagicMock) -> None:
    """Missing Upstash-Message-Id defaults to empty string."""
    mock_receiver = MagicMock()
    mock_receiver.verify = MagicMock()
    mock_receiver_cls.return_value = mock_receiver

    request = _make_request(msg_id="")
    resp = await _sample_handler(request)

    assert resp.status == 200
    request.__setitem__.assert_any_call("qstash_msg_id", "")
