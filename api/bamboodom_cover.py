"""GET /api/bamboodom/cover/{filename} — отдаёт tmp-картинку (4K).

Сторона B Bamboodom скачивает картинки по source_url. Когда OpenRouter отдаёт
base64, мы сохраняем в /tmp и отдаём через этот endpoint. URL формируется
из RAILWAY_PUBLIC_URL + filename.

Безопасность: разрешаем только `[A-Za-z0-9_-]{16,}\.(png|jpg|jpeg|webp)$`,
отдаём только .png/.jpg/.webp, без traversal.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import structlog
from aiohttp import web

log = structlog.get_logger()

_TMP_IMAGES_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "bamboodom_cover_images"  # noqa: S108
_FILENAME_RE = re.compile(r"^[A-Za-z0-9_-]{16,}\.(png|jpg|jpeg|webp)$")


async def bamboodom_cover_handler(request: web.Request) -> web.Response:
    filename = request.match_info.get("filename", "")
    if not _FILENAME_RE.match(filename):
        return web.Response(status=404)
    path = _TMP_IMAGES_DIR / filename
    if not path.exists() or not path.is_file():
        return web.Response(status=404)
    try:
        data = path.read_bytes()
    except Exception:
        return web.Response(status=500)

    ext = filename.rsplit(".", 1)[-1].lower()
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "webp": "image/webp",
    }.get(ext, "application/octet-stream")
    return web.Response(body=data, content_type=mime)
