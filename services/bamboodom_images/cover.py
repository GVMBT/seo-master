"""Cover-картинка для AI-статьи (4K).

Поток:
1. AI-промпт → cover_image_prompt (см. v13).
2. Вызываем OpenRouter Gemini Image → получаем URL или base64.
3. Если base64 — сохраняем во временный файл в /sessions/.../tmp_images/
   и формируем публичный URL через RAILWAY_PUBLIC_URL.
4. Если URL — отдаём как есть.
5. Дёргаем `blog_upload_image` стороны B с source_url + alt.
6. B WebP-конвертит, возвращает публичный URL картинки на bamboodom.ru.
7. Возвращаем этот URL — он попадёт в payload как cover.

Безопасность: tmp_images cleared при следующем uploads (TTL 1 час).
"""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

import structlog

from bot.config import get_settings
from integrations.bamboodom import BamboodomAPIError, BamboodomClient
from integrations.openrouter_image import OpenRouterImageClient, OpenRouterImageError

log = structlog.get_logger()

# Tmp images директория для Railway
_TMP_IMAGES_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "bamboodom_cover_images"  # noqa: S108
_TMP_IMAGES_TTL = 3600  # 1 час


def _ensure_tmp_dir() -> None:
    _TMP_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


def _cleanup_old() -> None:
    """Удалить tmp файлы старше 1 часа."""
    if not _TMP_IMAGES_DIR.exists():
        return
    now = time.time()
    for f in _TMP_IMAGES_DIR.iterdir():
        try:
            if now - f.stat().st_mtime > _TMP_IMAGES_TTL:
                f.unlink(missing_ok=True)
        except OSError:
            pass


def _public_url_for_tmp(filename: str) -> str | None:
    """Формирует публичный URL для tmp-файла через RAILWAY_PUBLIC_URL."""
    s = get_settings()
    base = (s.railway_public_url or "").rstrip("/")
    if not base:
        return None
    return f"{base}/api/bamboodom/cover/{filename}"


async def generate_and_upload_cover(
    cover_prompt: str,
    alt: str = "",
) -> str | None:
    """Полный цикл: prompt → OpenRouter → bamboodom upload → URL.

    Возвращает публичный URL картинки на bamboodom.ru для вставки в payload,
    или None при любой ошибке (graceful degrade — статья публикуется без cover).
    """
    if not cover_prompt:
        return None

    _ensure_tmp_dir()
    _cleanup_old()

    # 1. OpenRouter image generation
    try:
        img_client = OpenRouterImageClient()
        result = await img_client.generate(cover_prompt)
    except OpenRouterImageError as exc:
        log.warning("cover_openrouter_failed", error=str(exc)[:200])
        return None

    # 2. Если URL — сразу шлём в bamboodom
    source_url: str | None = None
    if result.url:
        source_url = result.url
    elif result.data_b64:
        # Сохраним в /tmp + сформируем publicURL через наш handler
        ext = "png" if "png" in result.mime_type else "jpg"
        filename = f"{secrets.token_urlsafe(16)}.{ext}"
        path = _TMP_IMAGES_DIR / filename
        try:
            path.write_bytes(OpenRouterImageClient.decode_b64(result.data_b64))
        except Exception:
            log.warning("cover_save_b64_failed", exc_info=True)
            return None
        source_url = _public_url_for_tmp(filename)
        if not source_url:
            log.warning("cover_no_public_url")
            return None
    else:
        return None

    # 3. Bamboodom upload_image
    try:
        b_client = BamboodomClient()
        resp = await b_client.upload_image(source_url=source_url, alt=alt)
    except BamboodomAPIError as exc:
        log.warning("cover_bamboodom_upload_failed", error=str(exc)[:200])
        return None
    except Exception:
        log.warning("cover_bamboodom_upload_unexpected", exc_info=True)
        return None

    final_url = resp.get("url") if isinstance(resp, dict) else None
    if not final_url:
        log.warning("cover_no_url_in_response", resp=str(resp)[:200])
        return None

    log.info("cover_uploaded", final_url=final_url, source_url=source_url[:80])
    return str(final_url)
