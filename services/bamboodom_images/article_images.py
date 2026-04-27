"""AI-генерация картинок для всех img-блоков статьи (v14.1, 2026-04-27).

Поток для каждого {"type":"img","slot":"hero","src":"","alt":"..."}:
1. Берём alt как Gemini-промпт.
2. Генерим через OpenRouterImageClient (1024×576 — Gemini рендерит ~16:9
   независимо от aspect_ratio параметра, поэтому ресайзим/кропим на нашей
   стороне через Pillow).
3. Конвертим в WebP 1024px по ширине, аспект слота сохраняется через crop
   к нужному ratio.
4. Multipart-upload в blog_upload_image.
5. Возвращённый src подставляем в блок.

Параллелизм: до 3 одновременных запросов (asyncio.Semaphore).
Graceful degrade: ошибка одной картинки → src="" остаётся, статья
публикуется с placeholder для этого слота.
"""

from __future__ import annotations

import asyncio
import io
from typing import Any

import httpx
import structlog

from integrations.bamboodom import BamboodomAPIError, BamboodomClient, BamboodomRateLimitError
from integrations.openrouter_image import (
    OpenRouterImageClient,
    OpenRouterImageError,
)

log = structlog.get_logger()

# Side B rate-limits blog_upload_image to ~1/sec. Sleep slightly more than 1s
# between requests to avoid 429 storms when we have 5-7 slots per article.
_INTER_REQUEST_DELAY = 1.2

# Целевая ширина WebP по слотам (письмо B 4S — 1024 покрывает все слоты).
_WEBP_TARGET_WIDTH = 1024

# Аспекты слотов для crop'а Gemini-вывода (он рисует 16:9 fixed).
# 4W layout v3 (2026-04-27): landscape-* и wide-* теперь оба full-width 16:9
# на стороне B (раньше landscape был ограничен центром 900px). hero оставляем
# в 21:9 — он узкий cinematic cover. square/portrait без изменений.
_SLOT_ASPECTS: dict[str, tuple[int, int]] = {
    "hero": (21, 9),
    "wide-1": (16, 9),
    "wide-2": (16, 9),
    "landscape-1": (16, 9),
    "landscape-2": (16, 9),
    "square-1": (1, 1),
    "square-2": (1, 1),
    "square-3": (1, 1),
    "portrait-1": (3, 4),
    "portrait-2": (2, 3),
}

# Базовый стилевой промпт для Gemini — добавляется к alt-тексту от модели.
_STYLE_SUFFIX = (
    " Photorealistic editorial interior photography, neutral palette with "
    "warm wood and stone accents, soft natural daylight. No people, no text, "
    "no watermarks. Sharp focus, high detail."
)


def _crop_and_webp(raw_bytes: bytes, slot: str, target_width: int = _WEBP_TARGET_WIDTH) -> bytes:
    """Crop to slot aspect + resize to target_width + encode as WebP.

    Имеется в виду: Gemini рисует ~16:9. Мы должны получить нужный нам
    аспект (например 21:9 для hero, 1:1 для square). Cropим по центру.
    """
    from PIL import Image  # lazy import to avoid pillow at module import time

    aspect_w, aspect_h = _SLOT_ASPECTS.get(slot, (16, 9))
    img = Image.open(io.BytesIO(raw_bytes))
    img = img.convert("RGB")  # WebP поддерживает RGBA, но для фото RGB достаточно

    src_w, src_h = img.size
    # Целевой аспект: target_h = target_w * aspect_h / aspect_w
    target_aspect = aspect_w / aspect_h
    src_aspect = src_w / src_h

    if src_aspect > target_aspect:
        # Картинка шире чем нужно — обрезаем по бокам
        new_w = int(src_h * target_aspect)
        offset = (src_w - new_w) // 2
        img = img.crop((offset, 0, offset + new_w, src_h))
    elif src_aspect < target_aspect:
        # Картинка выше чем нужно — обрезаем сверху-снизу
        new_h = int(src_w / target_aspect)
        offset = (src_h - new_h) // 2
        img = img.crop((0, offset, src_w, offset + new_h))

    # Resize to target width keeping aspect
    final_h = int(target_width * aspect_h / aspect_w)
    img = img.resize((target_width, final_h), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    img.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue()


async def _generate_one(
    *,
    block: dict[str, Any],
    slug: str,
    bamboodom_client: BamboodomClient,
    image_client: OpenRouterImageClient,
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, Any], str]:
    """Генерирует одну картинку для блока. Возвращает (block_ref, status).

    status: "ok" / "skip" / "error:..."
    """
    slot = str(block.get("slot") or "")
    alt = str(block.get("alt") or "").strip()

    if not slot or slot not in _SLOT_ASPECTS:
        return block, f"skip:bad_slot:{slot}"
    if not alt:
        return block, "skip:no_alt"

    prompt = alt + _STYLE_SUFFIX

    async with semaphore:
        # 1. Gemini generation
        try:
            result = await image_client.generate(prompt)
        except OpenRouterImageError as exc:
            log.warning("img_pipeline_gen_failed", slot=slot, error=str(exc)[:200])
            return block, f"error:gen:{exc}"

        # 2. Decode bytes (URL or b64)
        try:
            if result.data_b64:
                raw = OpenRouterImageClient.decode_b64(result.data_b64)
            elif result.url:
                # Fetch URL bytes through our http client
                async with httpx.AsyncClient(timeout=30.0) as c:
                    r = await c.get(result.url)
                    r.raise_for_status()
                    raw = r.content
            else:
                return block, "error:no_data"
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("img_pipeline_decode_failed", slot=slot, error=str(exc)[:200])
            return block, f"error:decode:{exc}"

        # 3. Crop + WebP
        try:
            webp_bytes = _crop_and_webp(raw, slot)
        except Exception as exc:
            log.warning("img_pipeline_pillow_failed", slot=slot, exc_info=True)
            return block, f"error:pillow:{exc}"

        # 4. Upload to Side B via multipart, with 429-aware retry.
        # Side B rate-limits to 1/sec — even with sequential parallel=1 we
        # can hit it on bursts. Up to 2 retries with sleeps from Retry-After.
        resp = None
        upload_attempts = 0
        last_exc: Exception | None = None
        while upload_attempts < 3:
            upload_attempts += 1
            try:
                resp = await bamboodom_client.upload_image_multipart(
                    slug=slug,
                    slot=slot,
                    image_bytes=webp_bytes,
                    content_type="image/webp",
                    alt=alt,
                )
                break  # success
            except BamboodomRateLimitError as exc:
                last_exc = exc
                wait_s = max(1.0, float(getattr(exc, "retry_after", 1) or 1))
                log.info(
                    "img_pipeline_upload_429",
                    slot=slot,
                    slug=slug,
                    attempt=upload_attempts,
                    wait_s=wait_s,
                )
                await asyncio.sleep(wait_s + 0.3)
                continue
            except BamboodomAPIError as exc:
                # Non-429 client/server error — log full body and bail out.
                log.warning(
                    "img_pipeline_upload_failed",
                    slot=slot,
                    slug=slug,
                    error=str(exc)[:1500],
                )
                return block, f"error:upload:{exc}"

        if resp is None:
            log.warning(
                "img_pipeline_upload_429_exhausted",
                slot=slot,
                slug=slug,
                error=str(last_exc)[:200] if last_exc else "unknown",
            )
            return block, "error:upload:429_exhausted"

        src = ""
        if isinstance(resp, dict):
            src = str(resp.get("src") or resp.get("url") or "").strip()
        if not src:
            return block, "error:upload_no_src"

        # 5. Mutate block in-place
        block["src"] = src
        log.info(
            "img_pipeline_ok",
            slot=slot,
            slug=slug,
            src=src[:80],
            webp_kb=len(webp_bytes) // 1024,
        )
        # Respect Side B's 1/sec rate limit on blog_upload_image.
        await asyncio.sleep(_INTER_REQUEST_DELAY)
        return block, "ok"


async def generate_article_images(
    *,
    slug: str,
    blocks: list[dict[str, Any]],
    http_client: httpx.AsyncClient,
    settings: Any,
    parallel: int = 1,
    inter_request_delay: float = 1.2,
) -> dict[str, int]:
    """Полный pipeline: для каждого img-блока в blocks → генерим и заливаем.

    Mutates blocks in-place — заполняет src у тех блоков, где это получилось.
    Возвращает счётчик статусов: {ok, skip, error}.
    """
    if not getattr(settings, "bamboodom_images_enabled", False):
        log.info("img_pipeline_disabled_by_flag")
        return {"disabled": 1}

    img_blocks = [b for b in blocks if isinstance(b, dict) and b.get("type") == "img"]
    if not img_blocks:
        return {"no_img_blocks": 1}

    bamboodom_client = BamboodomClient(http_client=http_client)
    image_client = OpenRouterImageClient()
    semaphore = asyncio.Semaphore(parallel)

    tasks = [
        _generate_one(
            block=b,
            slug=slug,
            bamboodom_client=bamboodom_client,
            image_client=image_client,
            semaphore=semaphore,
        )
        for b in img_blocks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    counter: dict[str, int] = {"ok": 0, "skip": 0, "error": 0}
    for r in results:
        if isinstance(r, Exception):
            counter["error"] += 1
            continue
        _block, status = r
        if status == "ok":
            counter["ok"] += 1
        elif status.startswith("skip:"):
            counter["skip"] += 1
        else:
            counter["error"] += 1

    log.info(
        "img_pipeline_done",
        slug=slug,
        total=len(img_blocks),
        results=counter,
    )
    return counter


async def run_background_image_pipeline(
    *,
    slug: str,
    blocks: list[dict[str, Any]],
    payload: dict[str, Any] | None = None,
    http_client: httpx.AsyncClient,
    settings: Any,
    sandbox: bool = True,
    parallel: int = 1,
) -> None:
    """Background task: generate images, upload, then re-publish article.

    Flow:
    1. generate_article_images mutates blocks in-place — fills src for each
       img-block that uploaded successfully.
    2. Re-publish via blog_publish (it's upsert-by-slug, allowed for our
       user-level X-Blog-Key). blog_update_article requires admin-only key
       per Side B's BLOG_API_V14 (HTTP 403 'admin only' otherwise).

    payload — оригинальный JSON, который мы отправляли в blog_publish при
    первой публикации (с пустыми src в img-блоках). После генерации мы
    заменяем blocks на обновлённые и шлём весь payload заново.

    Safe to fire-and-forget — exceptions logged but never re-raised.
    """
    try:
        counter = await generate_article_images(
            slug=slug,
            blocks=blocks,
            http_client=http_client,
            settings=settings,
            parallel=parallel,
        )
        log.info("bg_img_pipeline_generated", slug=slug, results=counter)

        # If nothing got generated, no point republishing.
        if not isinstance(counter, dict) or counter.get("ok", 0) == 0:
            log.info("bg_img_pipeline_no_update_needed", slug=slug)
            return

        if not isinstance(payload, dict):
            log.warning("bg_img_pipeline_no_payload_to_republish", slug=slug)
            return

        # Re-publish via blog_publish (upsert by slug). blocks were mutated
        # in-place by generate_article_images, so payload["blocks"] now has
        # real src values where uploads succeeded.
        bamboodom_client = BamboodomClient(http_client=http_client)
        # Make sure payload's blocks reference the mutated list (it already
        # does, because we passed the same list — just being explicit).
        new_payload = dict(payload)
        new_payload["blocks"] = blocks
        try:
            resp = await bamboodom_client.publish(new_payload, sandbox=sandbox)
            log.info(
                "bg_img_pipeline_republished",
                slug=slug,
                action_type=getattr(resp, "action_type", "?"),
                blocks_parsed=getattr(resp, "blocks_parsed", -1),
            )
        except BamboodomAPIError as exc:
            log.warning(
                "bg_img_pipeline_republish_failed",
                slug=slug,
                error=str(exc)[:1500],
            )
    except Exception:
        log.warning("bg_img_pipeline_unexpected_failure", slug=slug, exc_info=True)
