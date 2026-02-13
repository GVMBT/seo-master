"""Tests for services/publishers/telegram.py — Telegram Bot API publisher via httpx.

Covers: validate_connection (getChat), publish (text/caption split),
delete_post, error handling, multipart photo upload.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.telegram import _CAPTION_LIMIT, _TEXT_LIMIT, TelegramPublisher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BOT_TOKEN = "00000000:TEST_" + "x" * 30
_CHANNEL_ID = "-1001234567890"
_API_PREFIX = f"https://api.telegram.org/bot{_BOT_TOKEN}"


def _make_connection(**overrides: object) -> PlatformConnection:
    defaults: dict[str, Any] = {
        "id": 1,
        "project_id": 1,
        "platform_type": "telegram",
        "identifier": "test_channel",
        "credentials": {
            "bot_token": _BOT_TOKEN,
            "channel_id": _CHANNEL_ID,
        },
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_publisher(handler: Any) -> TelegramPublisher:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return TelegramPublisher(http_client=client)


def _ok_response(result: dict[str, Any] | bool = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


def _message_response(message_id: int) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})


def _error_response(description: str = "Bad Request") -> httpx.Response:
    return httpx.Response(400, json={"ok": False, "description": description})


# ---------------------------------------------------------------------------
# validate_connection
# ---------------------------------------------------------------------------


class TestValidateConnection:
    async def test_success_returns_true(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "getChat" in str(request.url)
            body = json.loads(request.content)
            assert body["chat_id"] == _CHANNEL_ID
            return _ok_response({"id": int(_CHANNEL_ID), "type": "channel"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is True

    async def test_api_error_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("Chat not found")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_network_error_returns_false(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Telegram API unreachable")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.validate_connection(conn)
        assert result is False

    async def test_uses_post_method(self) -> None:
        captured_method: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured_method.append(request.method)
            return _ok_response({"id": -100, "type": "channel"})

        pub = _make_publisher(handler)
        conn = _make_connection()
        await pub.validate_connection(conn)
        assert captured_method[0] == "POST"


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


class TestPublish:
    async def test_text_only_message(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "sendMessage" in str(request.url)
            body = json.loads(request.content)
            assert body["text"] == "Hello World!"
            assert body["parse_mode"] == "HTML"
            return _message_response(200)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Hello World!",
            content_type="telegram_html",
        )
        result = await pub.publish(req)
        assert result.success is True
        assert result.platform_post_id == "200"

    async def test_short_text_with_image_uses_caption(self) -> None:
        """Text <= 1024: photo with caption (single sendPhoto call)."""
        short_text = "A" * 500
        assert len(short_text) <= _CAPTION_LIMIT
        call_methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "sendPhoto" in url:
                call_methods.append("sendPhoto")
                # Multipart form data — check for caption field
                content_str = request.content.decode("utf-8", errors="replace")
                assert "caption" in content_str or b"caption" in request.content
                return _message_response(300)
            if "sendMessage" in url:
                call_methods.append("sendMessage")
                return _message_response(301)
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content=short_text,
            content_type="telegram_html",
            images=[b"PNG_DATA"],
        )
        result = await pub.publish(req)
        assert result.success is True
        assert result.platform_post_id == "300"
        assert call_methods == ["sendPhoto"]

    async def test_long_text_with_image_sends_photo_then_text(self) -> None:
        """Text > 1024: photo without caption, then separate text message."""
        long_text = "A" * 2000
        assert len(long_text) > _CAPTION_LIMIT
        call_methods: list[str] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "sendPhoto" in url:
                call_methods.append("sendPhoto")
                return _message_response(401)
            if "sendMessage" in url:
                call_methods.append("sendMessage")
                body = json.loads(request.content)
                assert body["parse_mode"] == "HTML"
                return _message_response(400)
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content=long_text,
            content_type="telegram_html",
            images=[b"PNG_DATA"],
        )
        result = await pub.publish(req)
        assert result.success is True
        # The message_id comes from the sendMessage call (last API call)
        assert result.platform_post_id == "400"
        assert call_methods == ["sendPhoto", "sendMessage"]

    async def test_text_truncated_to_limit(self) -> None:
        """Content beyond 4096 chars is truncated."""
        long_text = "B" * 5000

        async def handler(request: httpx.Request) -> httpx.Response:
            if "sendMessage" in str(request.url):
                body = json.loads(request.content)
                assert len(body["text"]) <= _TEXT_LIMIT
                return _message_response(500)
            return httpx.Response(404)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content=long_text,
            content_type="telegram_html",
        )
        result = await pub.publish(req)
        assert result.success is True

    async def test_publish_failure_returns_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("Chat not found")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Hello",
            content_type="telegram_html",
        )
        result = await pub.publish(req)
        assert result.success is False
        assert result.error is not None

    async def test_publish_network_error_returns_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Telegram down")

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Hello",
            content_type="telegram_html",
        )
        result = await pub.publish(req)
        assert result.success is False

    async def test_photo_uses_multipart_upload(self) -> None:
        """sendPhoto should use multipart/form-data with files dict."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "sendPhoto" in str(request.url):
                content_type = request.headers.get("content-type", "")
                assert "multipart/form-data" in content_type
                return _message_response(600)
            return _message_response(601)

        pub = _make_publisher(handler)
        conn = _make_connection()
        req = PublishRequest(
            connection=conn,
            content="Short",
            content_type="telegram_html",
            images=[b"PNG_DATA"],
        )
        result = await pub.publish(req)
        assert result.success is True


# ---------------------------------------------------------------------------
# delete_post
# ---------------------------------------------------------------------------


class TestDeletePost:
    async def test_delete_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert "deleteMessage" in str(request.url)
            body = json.loads(request.content)
            assert body["chat_id"] == _CHANNEL_ID
            assert body["message_id"] == 42
            return _ok_response(True)

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is True

    async def test_delete_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return _error_response("Message not found")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is False

    async def test_delete_network_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Telegram down")

        pub = _make_publisher(handler)
        conn = _make_connection()
        result = await pub.delete_post(conn, "42")
        assert result is False


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_caption_limit_is_1024(self) -> None:
        assert _CAPTION_LIMIT == 1024

    def test_text_limit_is_4096(self) -> None:
        assert _TEXT_LIMIT == 4096
