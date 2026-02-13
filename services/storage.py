"""Supabase Storage client for image upload/download/cleanup.

Uses raw httpx calls to Supabase Storage REST API (no SDK).
Bucket: article-previews (48h lifecycle as safety net).
"""

from dataclasses import dataclass

import httpx
import structlog

from bot.exceptions import AppError

log = structlog.get_logger()

BUCKET = "content-images"
SIGNED_URL_TTL = 90000  # 25 hours in seconds


@dataclass
class StoredImage:
    """Image stored in Supabase Storage."""

    path: str
    signed_url: str


class ImageStorage:
    """Upload/download/cleanup images in Supabase Storage."""

    def __init__(
        self,
        supabase_url: str,
        supabase_key: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._base_url = f"{supabase_url}/storage/v1"
        self._headers = {
            "apikey": supabase_key,
            "Authorization": f"Bearer {supabase_key}",
        }
        self._http = http_client

    async def upload(
        self,
        image_bytes: bytes,
        preview_id: int,
        index: int,
        mime: str = "image/png",
    ) -> StoredImage:
        """Upload image and return path + signed URL (25h TTL)."""
        ext = "png" if "png" in mime else "jpg"
        path = f"previews/{preview_id}/{index}.{ext}"

        # Upload
        resp = await self._http.post(
            f"{self._base_url}/object/{BUCKET}/{path}",
            content=image_bytes,
            headers={
                **self._headers,
                "Content-Type": mime,
                "x-upsert": "true",
            },
        )
        if resp.status_code not in (200, 201):
            log.error("storage_upload_failed", status=resp.status_code, body=resp.text[:200])
            raise AppError(
                message=f"Storage upload failed: {resp.status_code}",
                user_message="Ошибка загрузки изображения",
            )

        # Get signed URL
        signed_url = await self._get_signed_url(path)
        log.info("image_uploaded", path=path, preview_id=preview_id, index=index)

        return StoredImage(path=path, signed_url=signed_url)

    async def download(self, path: str) -> bytes:
        """Download image bytes from storage."""
        resp = await self._http.get(
            f"{self._base_url}/object/{BUCKET}/{path}",
            headers=self._headers,
        )
        if resp.status_code != 200:
            raise AppError(
                message=f"Storage download failed: {resp.status_code}",
                user_message="Ошибка загрузки изображения",
            )
        return resp.content

    async def cleanup(self, preview_id: int) -> int:
        """Delete all images for a preview. Returns count of deleted files."""
        # List files in the preview directory
        resp = await self._http.post(
            f"{self._base_url}/object/list/{BUCKET}",
            json={"prefix": f"previews/{preview_id}/", "limit": 100},
            headers={**self._headers, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            log.warning("storage_list_failed", preview_id=preview_id, status=resp.status_code)
            return 0

        files = resp.json()
        if not files:
            return 0

        # Delete files via POST (Supabase Storage batch delete expects plain array)
        paths = [f"previews/{preview_id}/{f['name']}" for f in files]
        del_resp = await self._http.post(
            f"{self._base_url}/object/remove/{BUCKET}",
            json=paths,
            headers={**self._headers, "Content-Type": "application/json"},
        )
        deleted = len(paths) if del_resp.status_code == 200 else 0
        log.info("storage_cleanup", preview_id=preview_id, deleted=deleted)
        return deleted

    async def _get_signed_url(self, path: str) -> str:
        """Create a signed URL with 25h TTL."""
        resp = await self._http.post(
            f"{self._base_url}/object/sign/{BUCKET}/{path}",
            json={"expiresIn": SIGNED_URL_TTL},
            headers={**self._headers, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise AppError(
                message=f"Signed URL creation failed: {resp.status_code}",
                user_message="Ошибка создания ссылки на изображение",
            )
        data = resp.json()
        signed = data.get("signedURL")
        if not signed:
            raise AppError(
                message=f"Unexpected signed URL response: {data}",
                user_message="Ошибка создания ссылки на изображение",
            )
        return f"{self._base_url}{signed}"
