"""Supabase Storage client for image upload/download/cleanup.

Uses raw httpx calls to Supabase Storage REST API (no SDK).
Bucket: content-images (24h cleanup via api/cleanup.py).
Path format: {user_id}/{project_id}/{timestamp}.webp (see ARCHITECTURE.md §5.9).
"""

import time
from dataclasses import dataclass
from io import BytesIO

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
        user_id: int,
        project_id: int,
        index: int,
        mime: str = "image/png",
    ) -> StoredImage:
        """Upload image as WebP and return path + signed URL (25h TTL).

        Path: {user_id}/{project_id}/{timestamp}_{index}.webp
        Falls back to original format if WebP conversion fails (E33).
        """
        image_bytes, ext, mime = self._convert_to_webp(image_bytes, mime)
        ts = int(time.time())
        path = f"{user_id}/{project_id}/{ts}_{index}.{ext}"

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
        log.info("image_uploaded", path=path, user_id=user_id, project_id=project_id, index=index)

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

    async def cleanup_by_paths(self, paths: list[str]) -> int:
        """Delete specific files from storage. Returns count of deleted files."""
        if not paths:
            return 0
        del_resp = await self._http.post(
            f"{self._base_url}/object/remove/{BUCKET}",
            json=paths,
            headers={**self._headers, "Content-Type": "application/json"},
        )
        deleted = len(paths) if del_resp.status_code == 200 else 0
        log.info("storage_cleanup", deleted=deleted, paths_count=len(paths))
        return deleted

    async def cleanup_prefix(self, prefix: str) -> int:
        """Delete all images under a prefix (e.g. '{user_id}/{project_id}/')."""
        resp = await self._http.post(
            f"{self._base_url}/object/list/{BUCKET}",
            json={"prefix": prefix, "limit": 100},
            headers={**self._headers, "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            log.warning("storage_list_failed", prefix=prefix, status=resp.status_code)
            return 0

        files = resp.json()
        if not files:
            return 0

        paths = [f"{prefix}{f['name']}" for f in files]
        return await self.cleanup_by_paths(paths)

    @staticmethod
    def _convert_to_webp(image_bytes: bytes, mime: str) -> tuple[bytes, str, str]:
        """Convert image to WebP. Falls back to original format on error (E33)."""
        try:
            from PIL import Image  # type: ignore[import-not-found]

            img = Image.open(BytesIO(image_bytes))
            buf = BytesIO()
            img.save(buf, format="WEBP", quality=85)
            return buf.getvalue(), "webp", "image/webp"
        except Exception:
            log.warning("webp_conversion_failed", original_mime=mime)
            ext = "png" if "png" in mime else "jpg"
            return image_bytes, ext, mime

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
