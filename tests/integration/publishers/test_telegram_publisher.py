"""Integration tests for TelegramPublisher (Bot API via httpx).

Uses `respx` to mock httpx calls to the Telegram Bot API.
The TelegramPublisher uses httpx (NOT aiogram Bot) to post content,
maintaining ZERO aiogram dependencies in the services/ layer.
"""

from __future__ import annotations

import json
from typing import Literal

import httpx
import pytest
import respx

from db.models import PlatformConnection
from services.publishers.base import PublishRequest
from services.publishers.telegram import TelegramPublisher

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

_BOT_TOKEN = "123456:ABC-DEF"
_CHANNEL_ID = "@test_channel"
_API_BASE = f"https://api.telegram.org/bot{_BOT_TOKEN}"

_TG_CREDS = {
    "bot_token": _BOT_TOKEN,
    "channel_id": _CHANNEL_ID,
}


def _make_connection(creds: dict[str, str] | None = None) -> PlatformConnection:
    """Build a PlatformConnection with Telegram credentials."""
    return PlatformConnection(
        id=200,
        project_id=1,
        platform_type="telegram",
        status="active",
        credentials=creds or _TG_CREDS,
        metadata={},
        identifier=_CHANNEL_ID,
    )


def _make_request(
    content: str = "Test post content",
    images: list[bytes] | None = None,
    content_type: Literal["html", "telegram_html", "plain_text", "pin_text"] = "telegram_html",
    connection: PlatformConnection | None = None,
) -> PublishRequest:
    return PublishRequest(
        connection=connection or _make_connection(),
        content=content,
        content_type=content_type,
        images=images or [],
    )


def _ok_message_response(message_id: int = 42) -> dict[str, object]:
    """Standard Telegram API success response for sendMessage/sendPhoto."""
    return {
        "ok": True,
        "result": {
            "message_id": message_id,
            "chat": {"id": -1001234567890, "title": "Test Channel", "type": "channel"},
            "date": 1700000000,
            "text": "Test",
        },
    }


# ---------------------------------------------------------------------------
# 1. Text post
# ---------------------------------------------------------------------------


@respx.mock
async def test_tg_publish_text_post() -> None:
    """Send a text-only message to a Telegram channel."""
    send_route = respx.post(f"{_API_BASE}/sendMessage").mock(
        return_value=httpx.Response(200, json=_ok_message_response(42)),
    )

    async with httpx.AsyncClient() as client:
        publisher = TelegramPublisher(client)
        result = await publisher.publish(_make_request(content="Hello <b>World</b>"))

    assert result.success is True
    assert result.platform_post_id == "42"

    # Verify sendMessage was called with correct payload
    assert send_route.call_count == 1
    body = json.loads(send_route.calls[0].request.content)
    assert body["chat_id"] == _CHANNEL_ID
    assert body["text"] == "Hello <b>World</b>"
    assert body["parse_mode"] == "HTML"


# ---------------------------------------------------------------------------
# 2. Photo with caption
# ---------------------------------------------------------------------------


@respx.mock
async def test_tg_publish_with_photo() -> None:
    """Send a photo with short caption (<=1024 chars) via sendPhoto."""
    photo_route = respx.post(f"{_API_BASE}/sendPhoto").mock(
        return_value=httpx.Response(200, json=_ok_message_response(43)),
    )

    short_caption = "Short caption under 1024 chars"
    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

    async with httpx.AsyncClient() as client:
        publisher = TelegramPublisher(client)
        result = await publisher.publish(_make_request(content=short_caption, images=[image_data]))

    assert result.success is True
    assert result.platform_post_id == "43"

    # sendPhoto was called (multipart upload)
    assert photo_route.call_count == 1


# ---------------------------------------------------------------------------
# 3. Long text with photo -> photo without caption + separate text message
# ---------------------------------------------------------------------------


@respx.mock
async def test_tg_publish_long_text_with_photo() -> None:
    """Content >1024 chars + image -> sendPhoto (no caption) + sendMessage (text).

    TelegramPublisher splits into two messages when content exceeds caption limit.
    """
    long_content = "A" * 2000  # Well above 1024 caption limit

    # Both endpoints will be called
    photo_route = respx.post(f"{_API_BASE}/sendPhoto").mock(
        return_value=httpx.Response(200, json=_ok_message_response(44)),
    )
    text_route = respx.post(f"{_API_BASE}/sendMessage").mock(
        return_value=httpx.Response(200, json=_ok_message_response(45)),
    )

    image_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    async with httpx.AsyncClient() as client:
        publisher = TelegramPublisher(client)
        result = await publisher.publish(_make_request(content=long_content, images=[image_data]))

    assert result.success is True
    # The message_id comes from the sendMessage call (the second one)
    assert result.platform_post_id == "45"

    # Both photo and text were sent
    assert photo_route.call_count == 1
    assert text_route.call_count == 1


# ---------------------------------------------------------------------------
# 4. HTML formatting preserved
# ---------------------------------------------------------------------------


@respx.mock
async def test_tg_publish_html_formatting() -> None:
    """HTML tags are preserved in the message text (parse_mode=HTML)."""
    html_content = "<b>Bold title</b>\n<i>Italic subtitle</i>\n<a href='https://example.com'>Link</a>"

    send_route = respx.post(f"{_API_BASE}/sendMessage").mock(
        return_value=httpx.Response(200, json=_ok_message_response(46)),
    )

    async with httpx.AsyncClient() as client:
        publisher = TelegramPublisher(client)
        result = await publisher.publish(_make_request(content=html_content))

    assert result.success is True
    body = json.loads(send_route.calls[0].request.content)
    assert body["parse_mode"] == "HTML"
    assert "<b>" in body["text"]
    assert "<i>" in body["text"]


# ---------------------------------------------------------------------------
# 5. Connection inactive (bot not admin of channel)
# ---------------------------------------------------------------------------


@respx.mock
async def test_tg_publish_connection_inactive() -> None:
    """Bot not admin of channel -> API error -> PublishResult with success=False."""
    respx.post(f"{_API_BASE}/sendMessage").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": False,
                "error_code": 403,
                "description": "Forbidden: bot is not a member of the channel chat",
            },
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = TelegramPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "bot is not a member" in result.error.lower() or "forbidden" in result.error.lower()


# ---------------------------------------------------------------------------
# 6. Rate limited (TelegramRetryAfter)
# ---------------------------------------------------------------------------


@respx.mock
async def test_tg_publish_rate_limited() -> None:
    """Telegram returns 429 Too Many Requests -> PublishResult with success=False.

    The publisher does not retry on 429 -- it returns an error result.
    The caller (PublishService/auto-publish handler) handles retry logic.
    """
    respx.post(f"{_API_BASE}/sendMessage").mock(
        return_value=httpx.Response(
            429,
            json={
                "ok": False,
                "error_code": 429,
                "description": "Too Many Requests: retry after 30",
                "parameters": {"retry_after": 30},
            },
        ),
    )

    async with httpx.AsyncClient() as client:
        publisher = TelegramPublisher(client)
        result = await publisher.publish(_make_request())

    assert result.success is False
    assert result.error is not None
    assert "429" in result.error or "retry" in result.error.lower()
