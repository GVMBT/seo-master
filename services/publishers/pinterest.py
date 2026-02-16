"""Pinterest publisher — API v5, base64 image upload, token refresh.

Source of truth: docs/API_CONTRACTS.md section 3.6.
Credentials include refresh_token + expires_at (30-day token refresh).
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from db.models import PlatformConnection

from .base import BasePublisher, PublishRequest, PublishResult

log = structlog.get_logger()

_BASE_URL = "https://api.pinterest.com/v5"
_TITLE_LIMIT = 100
_DESCRIPTION_LIMIT = 500
_REFRESH_THRESHOLD = timedelta(days=1)

# Callback type for callers that need to persist refreshed credentials
TokenRefreshCallback = Callable[
    [dict[str, Any], dict[str, Any]],
    Coroutine[Any, Any, None],
]


class PinterestPublisher(BasePublisher):
    """Pinterest API v5. OAuth access_token + refresh_token (30-day expiry)."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        client_id: str = "",
        client_secret: str = "",
        on_token_refresh: TokenRefreshCallback | None = None,
    ) -> None:
        self._client = http_client
        self._client_id = client_id
        self._client_secret = client_secret
        self._on_token_refresh = on_token_refresh

    # ------------------------------------------------------------------
    # token refresh
    # ------------------------------------------------------------------

    async def _maybe_refresh_token(self, creds: dict[str, Any]) -> str:
        """Return a valid access_token, refreshing if expires_at < now + 1 day."""
        expires_at_raw = creds.get("expires_at")
        if expires_at_raw is not None:
            expires_at = datetime.fromisoformat(expires_at_raw) if isinstance(expires_at_raw, str) else expires_at_raw

            # Ensure timezone-aware comparison
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)

            if expires_at > datetime.now(UTC) + _REFRESH_THRESHOLD:
                return str(creds["access_token"])

        # Token expires soon or already expired — refresh
        return await self._refresh_token(creds)

    async def _refresh_token(self, creds: dict[str, Any]) -> str:
        resp = await self._client.post(
            f"{_BASE_URL}/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            timeout=15,
        )
        resp.raise_for_status()
        new_tokens = resp.json()

        new_access = str(new_tokens["access_token"])
        new_refresh = new_tokens.get("refresh_token", creds["refresh_token"])
        expires_in: int = new_tokens.get("expires_in", 2592000)
        new_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        # Notify caller to persist updated credentials
        if self._on_token_refresh:
            await self._on_token_refresh(
                creds,
                {
                    "access_token": new_access,
                    "refresh_token": new_refresh,
                    "expires_at": new_expires_at.isoformat(),
                },
            )

        log.info("pinterest_token_refreshed")
        return new_access

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """GET /v5/user_account — verify token validity."""
        creds = connection.credentials
        try:
            token = await self._maybe_refresh_token(creds)
            resp = await self._client.get(
                f"{_BASE_URL}/user_account",
                headers=self._headers(token),
                timeout=10,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials

        try:
            token = await self._maybe_refresh_token(creds)

            if not request.images:
                return PublishResult(
                    success=False,
                    error="Pinterest requires at least one image",
                )

            pin_data: dict[str, Any] = {
                "board_id": request.metadata["board_id"],
                "title": request.metadata.get("pin_title", "")[:_TITLE_LIMIT],
                "description": request.content[:_DESCRIPTION_LIMIT],
                "media_source": {
                    "source_type": "image_base64",
                    "content_type": "image/png",
                    "data": base64.b64encode(request.images[0]).decode(),
                },
            }
            if link := request.metadata.get("link"):
                pin_data["link"] = link

            resp = await self._client.post(
                f"{_BASE_URL}/pins",
                json=pin_data,
                headers=self._headers(token),
                timeout=30,
            )
            resp.raise_for_status()
            pin = resp.json()

            return PublishResult(
                success=True,
                post_url=f"https://pinterest.com/pin/{pin['id']}",
                platform_post_id=str(pin["id"]),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "pinterest_publish_failed",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            return PublishResult(success=False, error=str(exc))
        except httpx.HTTPError as exc:
            log.error("pinterest_publish_error", error=str(exc))
            return PublishResult(success=False, error=str(exc))

    async def delete_post(self, connection: PlatformConnection, post_id: str) -> bool:
        creds = connection.credentials
        try:
            token = await self._maybe_refresh_token(creds)
            resp = await self._client.delete(
                f"{_BASE_URL}/pins/{post_id}",
                headers=self._headers(token),
                timeout=10,
            )
            return resp.is_success
        except httpx.HTTPError as exc:
            log.error("pinterest_delete_failed", post_id=post_id, error=str(exc))
            return False
