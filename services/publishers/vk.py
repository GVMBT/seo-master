"""VK publisher — VK API v5.199, dual-mode: group + personal page.

Source of truth: docs/API_CONTRACTS.md section 3.5.
Edge cases: E08 (VK token revoked).
Write idempotency (CR-78a): no retry on POST/create operations
(wall.post / photo upload could duplicate posts).

Token refresh: access_token TTL=3600s (60 min), refreshed via
POST https://id.vk.ru/oauth2/auth (refresh_token grant).
Pattern: same as PinterestPublisher._maybe_refresh_token().

Dual-mode:
- Group: owner_id=-{group_id}, photo upload with group_id
- Personal: owner_id={user_vk_id} or omitted, photo upload without group_id
  Detected via creds.get("target") == "personal"
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from db.models import PlatformConnection

from .base import BasePublisher, PublishRequest, PublishResult, TokenRefreshCallback

log = structlog.get_logger()

VK_API_URL = "https://api.vk.ru/method"
VK_API_VERSION = "5.199"
_VK_TEXT_LIMIT = 16384
_VK_TOKEN_URL = "https://id.vk.ru/oauth2/auth"  # noqa: S105
_REFRESH_THRESHOLD = timedelta(minutes=5)


class VKPublisher(BasePublisher):
    """VK API v5.199. Dual-mode: group or personal page per connection."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        vk_app_id: int = 0,
        on_token_refresh: TokenRefreshCallback | None = None,
    ) -> None:
        self._client = http_client
        self._app_id = vk_app_id
        self._on_token_refresh = on_token_refresh

    # ------------------------------------------------------------------
    # token refresh (pattern: PinterestPublisher)
    # ------------------------------------------------------------------

    async def _maybe_refresh_token(self, creds: dict[str, Any]) -> str:
        """Return a valid access_token, refreshing if expires_at < now + 5 min."""
        try:
            expires_at_raw = creds.get("expires_at")
            if expires_at_raw is not None:
                expires_at = (
                    datetime.fromisoformat(expires_at_raw)
                    if isinstance(expires_at_raw, str)
                    else expires_at_raw
                )
                # Ensure timezone-aware comparison
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at > datetime.now(UTC) + _REFRESH_THRESHOLD:
                    return str(creds["access_token"])
        except (ValueError, TypeError, AttributeError):
            log.warning("vk_expires_at_parse_error", expires_at=creds.get("expires_at"))
            # Can't determine expiry — attempt refresh if possible

        # No expires_at or token expiring soon — try refresh
        refresh_token = creds.get("refresh_token")
        if not refresh_token:
            # Legacy connection without refresh_token — use current token as-is
            return str(creds["access_token"])

        try:
            return await self._refresh_token(creds)
        except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
            log.warning("vk_token_refresh_failed", error=str(exc))
            # Fallback to current token — may be expired but worth trying
            return str(creds["access_token"])

    async def _refresh_token(self, creds: dict[str, Any]) -> str:
        """POST https://id.vk.ru/oauth2/auth (refresh_token grant)."""
        resp = await self._client.post(
            _VK_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": str(self._app_id),
                "device_id": creds.get("device_id", ""),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        resp.raise_for_status()
        new_tokens = resp.json()

        new_access = str(new_tokens["access_token"])
        new_refresh = new_tokens.get("refresh_token", creds["refresh_token"])
        expires_in: int = new_tokens.get("expires_in", 3600)
        new_expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        # Notify caller to persist updated credentials
        if self._on_token_refresh:
            updated: dict[str, Any] = {
                "access_token": new_access,
                "refresh_token": new_refresh,
                "expires_at": new_expires_at.isoformat(),
                "device_id": creds.get("device_id", ""),
                "group_id": creds.get("group_id", ""),
            }
            # Preserve personal page fields
            if creds.get("target") == "personal":
                updated["target"] = "personal"
                updated["user_vk_id"] = creds.get("user_vk_id", "")
            await self._on_token_refresh(creds, updated)

        log.info("vk_token_refreshed")
        return new_access

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
                request=httpx.Request("POST", VK_API_URL),
                response=httpx.Response(status_code=400),
            )

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """Verify token: users.get for personal, groups.getById for group."""
        creds = connection.credentials
        try:
            token = await self._maybe_refresh_token(creds)
            if creds.get("target") == "personal":
                resp = await self._client.post(
                    f"{VK_API_URL}/users.get",
                    data={"access_token": token, "v": VK_API_VERSION},
                    timeout=10,
                )
                return "response" in resp.json()
            resp = await self._client.post(
                f"{VK_API_URL}/groups.getById",
                data={
                    "access_token": token,
                    "group_id": creds["group_id"],
                    "v": VK_API_VERSION,
                },
                timeout=10,
            )
            return "response" in resp.json()
        except httpx.HTTPError:
            return False

    async def publish(self, request: PublishRequest) -> PublishResult:
        """Publish to VK. No retry on write operations (CR-78a)."""
        creds = request.connection.credentials
        is_personal = creds.get("target") == "personal"
        if is_personal:
            owner_id = str(creds.get("user_vk_id", ""))
            group_id = ""
        else:
            group_id = creds["group_id"]
            owner_id = f"-{group_id}"

        try:
            token = await self._maybe_refresh_token(creds)
            return await self._do_publish(request, token, group_id, owner_id)
        except httpx.HTTPStatusError as exc:
            log.error("vk_publish_failed", error=str(exc))
            return PublishResult(success=False, error=str(exc))
        except httpx.HTTPError as exc:
            log.error("vk_publish_error", error=str(exc))
            return PublishResult(success=False, error=str(exc))

    async def _upload_photo_wall(
        self,
        token: str,
        group_id: str,
        image_data: bytes,
    ) -> str | None:
        """Upload photo via photos.getWallUploadServer (user tokens).

        Returns attachment string like 'photo-123_456' or None on failure.
        When group_id is empty (personal page), omit group_id from API calls.
        """
        params: dict[str, str] = {"access_token": token, "v": VK_API_VERSION}
        if group_id:
            params["group_id"] = group_id
        resp = await self._client.post(
            f"{VK_API_URL}/photos.getWallUploadServer",
            data=params,
            timeout=15,
        )
        server_data = resp.json()
        if "error" in server_data:
            return None
        upload_url = server_data["response"]["upload_url"]
        return await self._upload_and_save_wall(token, group_id, upload_url, image_data)

    async def _upload_photo_album(
        self,
        token: str,
        group_id: str,
        image_data: bytes,
    ) -> str | None:
        """Upload photo via album (community token fallback).

        Creates/reuses a hidden album, uploads photo there.
        Returns attachment string like 'photo-123_456' or None on failure.
        Skipped for personal pages (empty group_id).
        """
        if not group_id:
            return None
        # Get or create album for bot uploads
        album_id = await self._get_or_create_album(token, group_id)
        if not album_id:
            return None

        resp = await self._client.post(
            f"{VK_API_URL}/photos.getUploadServer",
            data={
                "access_token": token,
                "album_id": album_id,
                "group_id": group_id,
                "v": VK_API_VERSION,
            },
            timeout=15,
        )
        server_data = resp.json()
        if "error" in server_data:
            log.warning(
                "vk_album_upload_server_failed",
                error_code=server_data["error"].get("error_code"),
                error_msg=server_data["error"].get("error_msg", ""),
            )
            return None

        upload_url = server_data["response"]["upload_url"]

        # Upload file
        upload_resp = await self._client.post(
            upload_url,
            files={"file1": ("image.png", image_data, "image/png")},
            timeout=30,
        )
        upload_data = upload_resp.json()

        # Save photo
        save_resp = await self._client.post(
            f"{VK_API_URL}/photos.save",
            data={
                "access_token": token,
                "album_id": album_id,
                "group_id": group_id,
                "photos_list": upload_data.get("photos_list", ""),
                "server": upload_data.get("server", ""),
                "hash": upload_data.get("hash", ""),
                "v": VK_API_VERSION,
            },
            timeout=15,
        )
        save_data = save_resp.json()
        if "error" in save_data:
            log.warning(
                "vk_album_photo_save_failed",
                error_code=save_data["error"].get("error_code"),
                error_msg=save_data["error"].get("error_msg", ""),
            )
            return None

        photo = save_data["response"][0]
        return f"photo{photo['owner_id']}_{photo['id']}"

    async def _get_or_create_album(self, token: str, group_id: str) -> int | None:
        """Get or create a hidden album for bot photo uploads."""
        # Try to find existing album named "SEO Bot"
        resp = await self._client.post(
            f"{VK_API_URL}/photos.getAlbums",
            data={"access_token": token, "owner_id": f"-{group_id}", "v": VK_API_VERSION},
            timeout=10,
        )
        albums_data = resp.json()
        if "response" in albums_data:
            for album in albums_data["response"].get("items", []):
                if album.get("title") == "SEO Bot":
                    return int(album["id"])

        # Create new album
        create_resp = await self._client.post(
            f"{VK_API_URL}/photos.createAlbum",
            data={
                "access_token": token,
                "group_id": group_id,
                "title": "SEO Bot",
                "upload_by_admins_only": 1,
                "comments_disabled": 1,
                "v": VK_API_VERSION,
            },
            timeout=10,
        )
        create_data = create_resp.json()
        if "error" in create_data:
            log.warning(
                "vk_create_album_failed",
                error_code=create_data["error"].get("error_code"),
                error_msg=create_data["error"].get("error_msg", ""),
            )
            return None
        return int(create_data["response"]["id"])

    async def _upload_and_save_wall(
        self,
        token: str,
        group_id: str,
        upload_url: str,
        image_data: bytes,
    ) -> str | None:
        """Upload file to VK server and save as wall photo."""
        upload_resp = await self._client.post(
            upload_url,
            files={"photo": ("image.png", image_data, "image/png")},
            timeout=30,
        )
        upload_data = upload_resp.json()

        save_params: dict[str, Any] = {
            "access_token": token,
            "photo": upload_data["photo"],
            "server": upload_data["server"],
            "hash": upload_data["hash"],
            "v": VK_API_VERSION,
        }
        if group_id:
            save_params["group_id"] = group_id

        save_resp = await self._client.post(
            f"{VK_API_URL}/photos.saveWallPhoto",
            data=save_params,
            timeout=15,
        )
        save_data = save_resp.json()
        if "error" in save_data:
            return None
        photo = save_data["response"][0]
        return f"photo{photo['owner_id']}_{photo['id']}"

    async def _do_publish(
        self,
        request: PublishRequest,
        token: str,
        group_id: str,
        owner_id: str,
    ) -> PublishResult:
        """Execute the actual VK publish flow."""
        attachments: list[str] = []

        # 1. Upload photo: try wall upload first, fallback to album upload
        if request.images:
            image_data = request.images[0]

            # Try wall upload (works with user tokens)
            attachment = await self._upload_photo_wall(token, group_id, image_data)

            if not attachment and group_id:
                # Fallback: album upload (works with community tokens, not for personal pages)
                log.info("vk_trying_album_upload", group_id=group_id)
                attachment = await self._upload_photo_album(token, group_id, image_data)

            if attachment:
                attachments.append(attachment)
            else:
                log.warning("vk_all_photo_uploads_failed", group_id=group_id or "personal")

        # 2. Publish wall post
        post_params: dict[str, str] = {
            "access_token": token,
            "message": request.content[:_VK_TEXT_LIMIT],
            "attachments": ",".join(attachments),
            "v": VK_API_VERSION,
        }
        if owner_id:
            post_params["owner_id"] = owner_id

        resp = await self._client.post(
            f"{VK_API_URL}/wall.post",
            data=post_params,
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
            token = await self._maybe_refresh_token(creds)
            if creds.get("target") == "personal":
                owner_id = str(creds.get("user_vk_id", ""))
            else:
                owner_id = f"-{creds['group_id']}"
            resp = await self._client.post(
                f"{VK_API_URL}/wall.delete",
                data={
                    "access_token": token,
                    "owner_id": owner_id,
                    "post_id": post_id,
                    "v": VK_API_VERSION,
                },
                timeout=10,
            )
            data = resp.json()
            return bool(data.get("response") == 1)
        except httpx.HTTPError as exc:
            log.error("vk_delete_failed", post_id=post_id, error=str(exc))
            return False
