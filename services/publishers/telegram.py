"""Telegram publisher — Bot API via direct httpx HTTP calls.

Source of truth: docs/API_CONTRACTS.md section 3.4.
ZERO aiogram dependencies (services/ layer rule).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from db.models import PlatformConnection

from .base import BasePublisher, PublishRequest, PublishResult

log = structlog.get_logger()

# Telegram limits
_CAPTION_LIMIT = 1024
_TEXT_LIMIT = 4096

_API_BASE = "https://api.telegram.org/bot{token}"


class TelegramPublisher(BasePublisher):
    """Publish via a user-owned publisher bot added as admin to a channel."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    def _url(self, token: str, method: str) -> str:
        """Build Telegram Bot API URL."""
        return f"{_API_BASE.format(token=token)}/{method}"

    async def _api_call(
        self,
        token: str,
        method: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Send a JSON-body POST to the Bot API and return the result dict.

        Raises httpx.HTTPStatusError on non-2xx or API error.
        """
        resp = await self._client.post(
            self._url(token, method),
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        if not data.get("ok"):
            description = data.get("description", "Unknown Telegram API error")
            raise httpx.HTTPStatusError(
                description,
                request=resp.request,
                response=resp,
            )
        return data

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """getChat — verify the bot can access the channel."""
        creds = connection.credentials
        try:
            await self._api_call(
                creds["bot_token"],
                "getChat",
                {"chat_id": creds["channel_id"]},
            )
            return True
        except Exception:
            log.warning(
                "telegram_validate_failed",
                channel_id=creds.get("channel_id"),
            )
            return False

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials
        token = creds["bot_token"]
        channel_id = creds["channel_id"]

        try:
            if request.images:
                text = request.content[:_TEXT_LIMIT]
                if len(request.content) > _CAPTION_LIMIT:
                    # Long post: photo without caption, then separate text message
                    await self._send_photo(token, channel_id, request.images[0])
                    data = await self._api_call(
                        token,
                        "sendMessage",
                        {
                            "chat_id": channel_id,
                            "text": text,
                            "parse_mode": "HTML",
                        },
                    )
                else:
                    # Short post: photo with caption
                    data = await self._send_photo(
                        token,
                        channel_id,
                        request.images[0],
                        caption=request.content[:_CAPTION_LIMIT],
                    )
            else:
                data = await self._api_call(
                    token,
                    "sendMessage",
                    {
                        "chat_id": channel_id,
                        "text": request.content[:_TEXT_LIMIT],
                        "parse_mode": "HTML",
                    },
                )

            message_id = str(data["result"]["message_id"])
            return PublishResult(
                success=True,
                platform_post_id=message_id,
            )
        except Exception as exc:
            log.error(
                "telegram_publish_failed",
                channel_id=channel_id,
                error=str(exc),
            )
            return PublishResult(success=False, error=str(exc))

    async def delete_post(
        self, connection: PlatformConnection, post_id: str
    ) -> bool:
        creds = connection.credentials
        try:
            await self._api_call(
                creds["bot_token"],
                "deleteMessage",
                {
                    "chat_id": creds["channel_id"],
                    "message_id": int(post_id),
                },
            )
            return True
        except Exception as exc:
            log.error("telegram_delete_failed", post_id=post_id, error=str(exc))
            return False

    async def _send_photo(
        self,
        token: str,
        chat_id: str,
        image_bytes: bytes,
        *,
        caption: str | None = None,
    ) -> dict[str, Any]:
        """Upload a photo via multipart/form-data."""
        data_fields: dict[str, Any] = {"chat_id": chat_id}
        if caption:
            data_fields["caption"] = caption
            data_fields["parse_mode"] = "HTML"

        resp = await self._client.post(
            self._url(token, "sendPhoto"),
            data=data_fields,
            files={"photo": ("image.jpg", image_bytes, "image/jpeg")},
            timeout=30,
        )
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        if not result.get("ok"):
            description = result.get("description", "Unknown Telegram API error")
            raise httpx.HTTPStatusError(
                description,
                request=resp.request,
                response=resp,
            )
        return result
