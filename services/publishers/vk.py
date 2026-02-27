"""VK publisher — VK API v5.199, direct token, single group per connection.

Source of truth: docs/API_CONTRACTS.md section 3.5.
Edge cases: E08 (VK token revoked).
Retry: C10/C11 — retry on 429/5xx with backoff, no retry on 401/403.
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from db.models import PlatformConnection
from services.http_retry import retry_with_backoff

from .base import BasePublisher, PublishRequest, PublishResult

log = structlog.get_logger()

# Retry settings for VK publish (C11)
_PUBLISH_MAX_RETRIES = 2
_PUBLISH_BASE_DELAY = 1.0

_VK_API = "https://api.vk.ru/method"
_VK_VERSION = "5.199"
_VK_TEXT_LIMIT = 16384


class VKPublisher(BasePublisher):
    """VK API v5.199. Direct token, one group per connection."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_vk_response(data: dict[str, Any], operation: str) -> None:
        """Raise if VK response contains an error block."""
        if "error" in data:
            code = data["error"].get("error_code", "?")
            msg = data["error"].get("error_msg", "unknown")
            err_msg = f"VK {operation} error {code}: {msg}"
            raise httpx.HTTPStatusError(
                err_msg,
                request=httpx.Request("POST", _VK_API),
                response=httpx.Response(status_code=400),
            )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """groups.getById — verify token and group access."""
        creds = connection.credentials
        try:
            resp = await self._client.post(
                f"{_VK_API}/groups.getById",
                data={
                    "access_token": creds["access_token"],
                    "group_id": creds["group_id"],
                    "v": _VK_VERSION,
                },
                timeout=10,
            )
            return "response" in resp.json()
        except httpx.HTTPError:
            return False

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials
        token = creds["access_token"]
        group_id = creds["group_id"]
        owner_id = f"-{group_id}"

        try:
            result = await retry_with_backoff(
                lambda: self._do_publish(request, token, group_id, owner_id),
                max_retries=_PUBLISH_MAX_RETRIES,
                base_delay=_PUBLISH_BASE_DELAY,
                operation="vk_publish",
            )
        except httpx.HTTPStatusError as exc:
            log.error("vk_publish_failed", error=str(exc))
            return PublishResult(success=False, error=str(exc))
        except httpx.HTTPError as exc:
            log.error("vk_publish_error", error=str(exc))
            return PublishResult(success=False, error=str(exc))
        else:
            return result

    async def _do_publish(
        self,
        request: PublishRequest,
        token: str,
        group_id: str,
        owner_id: str,
    ) -> PublishResult:
        """Execute the actual VK publish flow (called inside retry_with_backoff)."""
        attachments: list[str] = []

        # 1. Upload photo (3-step: get server -> upload -> save)
        if request.images:
            # Step 1: get upload URL
            resp = await self._client.post(
                f"{_VK_API}/photos.getWallUploadServer",
                data={
                    "access_token": token,
                    "group_id": group_id,
                    "v": _VK_VERSION,
                },
                timeout=15,
            )
            server_data = resp.json()
            self._check_vk_response(server_data, "getWallUploadServer")
            upload_url = server_data["response"]["upload_url"]

            # Step 2: upload file
            upload_resp = await self._client.post(
                upload_url,
                files={"photo": ("image.png", request.images[0], "image/png")},
                timeout=30,
            )
            upload_data = upload_resp.json()

            # Step 3: save photo
            save_resp = await self._client.post(
                f"{_VK_API}/photos.saveWallPhoto",
                data={
                    "access_token": token,
                    "group_id": group_id,
                    "photo": upload_data["photo"],
                    "server": upload_data["server"],
                    "hash": upload_data["hash"],
                    "v": _VK_VERSION,
                },
                timeout=15,
            )
            save_data = save_resp.json()
            self._check_vk_response(save_data, "saveWallPhoto")
            photo = save_data["response"][0]
            attachments.append(f"photo{photo['owner_id']}_{photo['id']}")

        # 2. Publish wall post
        resp = await self._client.post(
            f"{_VK_API}/wall.post",
            data={
                "access_token": token,
                "owner_id": owner_id,
                "message": request.content[:_VK_TEXT_LIMIT],
                "attachments": ",".join(attachments),
                "v": _VK_VERSION,
            },
            timeout=15,
        )
        post_data = resp.json()
        self._check_vk_response(post_data, "wall.post")
        post_id = post_data["response"]["post_id"]

        return PublishResult(
            success=True,
            post_url=f"https://vk.com/wall{owner_id}_{post_id}",
            platform_post_id=str(post_id),
        )

    async def delete_post(self, connection: PlatformConnection, post_id: str) -> bool:
        creds = connection.credentials
        try:
            resp = await self._client.post(
                f"{_VK_API}/wall.delete",
                data={
                    "access_token": creds["access_token"],
                    "owner_id": f"-{creds['group_id']}",
                    "post_id": post_id,
                    "v": _VK_VERSION,
                },
                timeout=10,
            )
            data = resp.json()
            return bool(data.get("response") == 1)
        except httpx.HTTPError as exc:
            log.error("vk_delete_failed", post_id=post_id, error=str(exc))
            return False
