"""WordPress publisher — WP REST API v2, Basic Auth.

Source of truth: docs/API_CONTRACTS.md section 3.3.
Edge cases: E02 (WP unavailable).
"""

from __future__ import annotations

import httpx
import structlog

from db.models import PlatformConnection

from .base import BasePublisher, PublishRequest, PublishResult

log = structlog.get_logger()


class WordPressPublisher(BasePublisher):
    """WP REST API v2. Authorization: Application Password (Basic Auth)."""

    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._client = http_client

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _base_url(creds: dict[str, str]) -> str:
        return creds["url"].rstrip("/") + "/wp-json/wp/v2"

    @staticmethod
    def _auth(creds: dict[str, str]) -> httpx.BasicAuth:
        return httpx.BasicAuth(creds["login"], creds["app_password"])

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """GET /wp-json/wp/v2/users/me — verify authorization."""
        creds = connection.credentials
        base = self._base_url(creds)
        try:
            resp = await self._client.get(
                f"{base}/users/me",
                auth=self._auth(creds),
                timeout=10,
            )
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials
        base = self._base_url(creds)
        auth = self._auth(creds)

        try:
            # 1. Upload images -> attachment IDs (with SEO metadata from images_meta)
            attachment_ids: list[int] = []
            for i, img_bytes in enumerate(request.images):
                meta = request.images_meta[i] if i < len(request.images_meta) else {}
                filename = f"{meta.get('filename', f'image-{i}')}.webp"
                alt_text = meta.get("alt", "")
                mime = "image/webp" if img_bytes[:4] == b"RIFF" else "image/png"

                resp = await self._client.post(
                    f"{base}/media",
                    content=img_bytes,
                    auth=auth,
                    headers={
                        "Content-Type": mime,
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    },
                    timeout=30,
                )
                resp.raise_for_status()
                media_id = resp.json()["id"]

                # Update alt_text and caption via WP REST (Image SEO)
                if alt_text or meta.get("figcaption"):
                    await self._client.post(
                        f"{base}/media/{media_id}",
                        json={
                            "alt_text": alt_text,
                            "caption": meta.get("figcaption", ""),
                        },
                        auth=auth,
                        timeout=15,
                    )
                attachment_ids.append(media_id)

            # 2. Create post
            post_data: dict[str, object] = {
                "title": request.title or "",
                "content": request.content,
                "status": "publish",
                "featured_media": attachment_ids[0] if attachment_ids else 0,
                "meta": {
                    "_yoast_wpseo_title": request.metadata.get(
                        "seo_title", request.title or ""
                    ),
                    "_yoast_wpseo_metadesc": request.metadata.get(
                        "seo_description", ""
                    ),
                    "_yoast_wpseo_focuskw": request.metadata.get(
                        "focus_keyword", ""
                    ),
                },
            }
            if wp_cat := request.metadata.get("wp_category_id"):
                post_data["categories"] = [wp_cat]

            resp = await self._client.post(
                f"{base}/posts", json=post_data, auth=auth, timeout=30
            )
            resp.raise_for_status()
            post = resp.json()

            return PublishResult(
                success=True,
                post_url=post["link"],
                platform_post_id=str(post["id"]),
            )
        except httpx.HTTPStatusError as exc:
            log.error(
                "wordpress_publish_failed",
                status=exc.response.status_code,
                body=exc.response.text[:500],
            )
            return PublishResult(success=False, error=str(exc))
        except httpx.HTTPError as exc:
            log.error("wordpress_publish_error", error=str(exc))
            return PublishResult(success=False, error=str(exc))

    async def delete_post(
        self, connection: PlatformConnection, post_id: str
    ) -> bool:
        creds = connection.credentials
        base = self._base_url(creds)
        try:
            resp = await self._client.delete(
                f"{base}/posts/{post_id}",
                auth=self._auth(creds),
                params={"force": "true"},
                timeout=15,
            )
            return resp.is_success
        except httpx.HTTPError as exc:
            log.error("wordpress_delete_failed", post_id=post_id, error=str(exc))
            return False
