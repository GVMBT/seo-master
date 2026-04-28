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

# 5T (2026-04-28): material-aware Gemini style suffix.
# Раньше был один общий _STYLE_SUFFIX про "interior + neutral palette" —
# из-за этого WPC рисовался как реечные планки или мраморные блоки. Теперь
# каждому материалу дан жёсткий гайдрейл по геометрии и текстуре.

_STYLE_BY_MATERIAL: dict[str, str] = {
    "wpc": (
        " CRITICAL GEOMETRY (do not deviate): WPC panels are LARGE FLAT WALL "
        "SHEETS, exactly 1220 mm WIDE and 2440-3000 mm TALL. Always shown as "
        "continuous flat wide vertical or horizontal SHEETS covering the "
        "wall edge-to-edge. ABSOLUTELY NOT narrow slats, NOT vertical "
        "battens, NOT wood planks, NOT rakes, NOT 30-50mm wide stripes — "
        "those are a different product (рейки). NO 3D ribs, NO grooves, NO "
        "vertical lines between sheets — surface is smooth and flat. "
        "Wood-print or stone-print decorative laminate on a single flat "
        "plane. Joint between two sheets (when visible) is a thin 1-2mm "
        "vertical seam, never a wide groove. "
        "Photorealistic editorial interior photography, soft natural "
        "daylight, no people, no text, no watermarks, sharp focus, high detail."
    ),
    "flex": (
        " CRITICAL: flexible ceramic facade tile (гибкая керамика) — thin "
        "flexible composite sheet (2-17mm) with stone/brick/travertine print, "
        "applied directly on flat or CURVED surfaces (column, archway, "
        "rounded façade corner) with subtle joint lines. NOT solid stone, "
        "NOT 3D brick, NOT raised pattern. Photorealistic editorial "
        "architectural photography, natural daylight, no people, no text, "
        "no watermarks, sharp focus, high detail."
    ),
    "reiki": (
        " CRITICAL: vertical wooden slat wall panels (реечные панели) — "
        "30-50 mm wide vertical wooden battens with NARROW 5-10mm SHADOW "
        "GAPS between them. Acoustic wall feature. NOT a flat panel, NOT "
        "a wide sheet — clearly separate vertical strips. Photorealistic "
        "editorial interior photography, soft warm daylight, no people, "
        "no text, no watermarks, sharp focus, high detail."
    ),
    "profiles": (
        " CRITICAL: aluminum decorative finishing profile — narrow elongated "
        "metal trim, sharp clean edges, brushed or polished metallic finish. "
        "Used at joints between wall panels, corner trims, edge caps. "
        "Macro/detail composition. Photorealistic, sharp focus, high detail, "
        "no people, no text."
    ),
}

_STYLE_SUFFIX_DEFAULT = (
    " Photorealistic editorial interior photography, neutral palette, "
    "soft natural daylight, no people, no text, no watermarks, sharp focus."
)


def _style_suffix_for(material: str | None) -> str:
    """Pick material-specific Gemini suffix; fall back to neutral default."""
    if not material:
        return _STYLE_SUFFIX_DEFAULT
    return _STYLE_BY_MATERIAL.get(material.strip().lower(), _STYLE_SUFFIX_DEFAULT)


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
    material: str | None = None,
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

    prompt = alt + _style_suffix_for(material)

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
    material: str | None = None,
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
            material=material,
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
    sandbox: bool = False,
    parallel: int = 1,
    # 4Z (2026-04-27): announcement timing fix — TG/VK posts must wait for
    # cover image to be ready, otherwise they go out without preview. When
    # these are passed, after a successful republish the pipeline finds the
    # hero img src, writes it to payload["cover"], and dispatches both the
    # @ecosteni announce and the connections-based social announce.
    announce_bot: Any | None = None,
    announce_db: Any | None = None,
    announce_title: str = "",
    announce_url: str | None = None,
    announce_excerpt: str = "",
    announce_extra_text: str = "",
) -> None:
    """Background task: generate images, upload, then re-publish article.

    Flow:
    1. generate_article_images mutates blocks in-place — fills src for each
       img-block that uploaded successfully.
    2. Re-publish via blog_publish (it's upsert-by-slug, allowed for our
       user-level X-Blog-Key). blog_update_article requires admin-only key
       per Side B's BLOG_API_V14 (HTTP 403 'admin only' otherwise).
    3. Announce on TG/VK with the now-ready cover (4Z fix).

    payload — оригинальный JSON, который мы отправляли в blog_publish при
    первой публикации (с пустыми src в img-блоках). После генерации мы
    заменяем blocks на обновлённые и шлём весь payload заново.

    Safe to fire-and-forget — exceptions logged but never re-raised.
    """
    try:
        # Extract material from payload.category for material-aware
        # Gemini prompts (5T). Falls back to None → default suffix.
        material_from_payload = None
        if isinstance(payload, dict):
            cat = payload.get("category")
            if isinstance(cat, str) and cat.strip():
                material_from_payload = cat.strip().lower()
        counter = await generate_article_images(
            slug=slug,
            blocks=blocks,
            http_client=http_client,
            settings=settings,
            parallel=parallel,
            material=material_from_payload,
        )
        log.info("bg_img_pipeline_generated", slug=slug, results=counter)

        # If nothing got generated, no point republishing.
        if not isinstance(counter, dict) or counter.get("ok", 0) == 0:
            log.info("bg_img_pipeline_no_update_needed", slug=slug)
            return

        if not isinstance(payload, dict):
            log.warning("bg_img_pipeline_no_payload_to_republish", slug=slug)
            return

        # 4Z2 (2026-04-27): extract hero_src BEFORE republish so we can fill
        # payload["cover"]. Side B uses cover for /blog listing thumbnails
        # and og:image. Without it the article appears with a grey placeholder
        # on the blog index even though hero img exists inside the article.
        # 5A (2026-04-27): make hero_src absolute. Side B returns src as a
        # path-only string ("/img/blog/<slug>/hero-1.webp"). On the article
        # page B prefixes the host itself, so og:image is fine. But
        # _fetch_image_bytes in services/announce/social.py uses httpx.get()
        # which rejects relative URLs ("Request URL is missing an http(s)
        # protocol"). Resolve to https://bamboodom.ru/<path> when needed.
        hero_src = ""
        for blk in blocks or []:
            if not isinstance(blk, dict) or blk.get("type") != "img":
                continue
            if blk.get("slot") == "hero" and blk.get("src"):
                hero_src = str(blk["src"])
                break
        if not hero_src:
            for blk in blocks or []:
                if isinstance(blk, dict) and blk.get("type") == "img" and blk.get("src"):
                    hero_src = str(blk["src"])
                    break

        if hero_src and hero_src.startswith("/"):
            hero_src = "https://bamboodom.ru" + hero_src
        elif hero_src and not hero_src.startswith(("http://", "https://")):
            # Defensive: just-in-case Side B switches to host-relative without /.
            hero_src = "https://bamboodom.ru/" + hero_src.lstrip("/")

        # Re-publish via blog_publish (upsert by slug). blocks were mutated
        # in-place by generate_article_images, so payload["blocks"] now has
        # real src values where uploads succeeded.
        bamboodom_client = BamboodomClient(http_client=http_client)
        new_payload = dict(payload)
        new_payload["blocks"] = blocks
        if hero_src and not new_payload.get("cover"):
            # Fill cover from hero img — drives /blog listing thumbnail.
            new_payload["cover"] = hero_src
        try:
            resp = await bamboodom_client.publish(new_payload, sandbox=sandbox)
            log.info(
                "bg_img_pipeline_republished",
                slug=slug,
                action_type=getattr(resp, "action_type", "?"),
                blocks_parsed=getattr(resp, "blocks_parsed", -1),
                cover_filled=bool(hero_src and not payload.get("cover")),
            )
        except BamboodomAPIError as exc:
            log.warning(
                "bg_img_pipeline_republish_failed",
                slug=slug,
                error=str(exc)[:1500],
            )
            # No point announcing if the article didn't publish with images.
            return

        # 5M (2026-04-28): auto-promote dropped — side B made bot-key trusted
        # (variant A in LETTER_TO_SIDE_A_5K_trusted_bot_done.md). blog_publish
        # with draft:false without ?sandbox=1 now publishes straight to /blog
        # without draft_forced. No promote step needed.
        #
        # 5H (2026-04-28): canonicalise legacy /article.html?slug=X (production)
        # to /blog/X for cleaner social posts. sandbox URLs untouched.
        if announce_url and "sandbox=1" not in announce_url and "/article.html?slug=" in announce_url:
            after = announce_url.split("/article.html?slug=", 1)[1]
            slug_only = after.split("&", 1)[0].rstrip("/")
            if slug_only:
                prefix = announce_url.split("/article.html?slug=", 1)[0]
                announce_url = f"{prefix}/blog/{slug_only}"
                log.info("bg_img_pipeline_announce_url_canonicalised", slug=slug, url=announce_url)

        if announce_bot is not None and announce_title:
            # 5L (2026-04-28): give beget/CDN a few seconds to actually serve
            # the freshly uploaded webp files before Telegram tries to fetch
            # them. Without this we saw "failed to get HTTP URL content" on
            # cover URL even though the file was on disk a second earlier.
            import asyncio as _aio
            await _aio.sleep(5)
            try:
                from services.announce import announce_article, announce_to_social

                # @ecosteni via bot.send_message (cover-aware after 947a929 fix).
                await announce_article(
                    announce_bot,
                    announce_title,
                    announce_url,
                    excerpt=announce_excerpt,
                    extra_text=announce_extra_text,
                    cover_url=hero_src or None,
                )

                # Connections-based publishers (VK/Pinterest/TG via project).
                if announce_url and announce_db is not None:
                    results = await announce_to_social(
                        db=announce_db,
                        http_client=http_client,
                        settings=settings,
                        title=announce_title,
                        url=announce_url,
                        excerpt=announce_excerpt,
                        image_url=hero_src or "",
                        extra_text=announce_extra_text,
                    )
                    log.info(
                        "bg_img_pipeline_announce_done",
                        slug=slug,
                        with_cover=bool(hero_src),
                        results=results,
                    )
                else:
                    log.info(
                        "bg_img_pipeline_announce_done",
                        slug=slug,
                        with_cover=bool(hero_src),
                        results={"single": "ecosteni-only"},
                    )
            except Exception:
                log.warning(
                    "bg_img_pipeline_announce_failed", slug=slug, exc_info=True
                )
    except Exception:
        log.warning("bg_img_pipeline_unexpected_failure", slug=slug, exc_info=True)
