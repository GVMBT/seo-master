"""QStash auto-publish webhook handler.

POST /api/publish — thin aiohttp wrapper.
Always returns 200 (except semaphore timeout / shutdown -> 503).
"""

import asyncio

import structlog
from aiohttp import web

from api import require_qstash_signature
from api.models import PublishPayload
from cache.keys import PUBLISH_LOCK_TTL, CacheKeys
from services.publish import PublishOutcome, PublishService

log = structlog.get_logger()

# Notification text templates per EDGE_CASES.md - missed auto-publish notifications
_REASON_TEMPLATES: dict[str, str] = {
    "insufficient_balance": (
        "Автопубликация пропущена: недостаточно токенов. Расписание приостановлено.\n[Пополнить баланс → /start]"
    ),
    "no_keywords": ("Автопубликация пропущена: нет ключевых фраз в категории.\n[Подобрать фразы → /start]"),
    "connection_inactive": (
        "Автопубликация не удалась: платформа не отвечает. Проверьте подключение.\n[Проверить → /start]"
    ),
    "content_validation_failed": ("Автопубликация пропущена: контент не прошёл проверку качества. Токены возвращены."),
    "ai_service_unavailable": ("Автопубликация отложена: AI-сервис временно недоступен. Повторим через 1 час."),
}


_PLATFORM_LABELS: dict[str, str] = {
    "telegram": "Telegram",
    "vk": "VK",
    "pinterest": "Pinterest",
    "wordpress": "WordPress",
}


def _build_notification_text(result: PublishOutcome) -> str:
    """Build user-facing notification text per EDGE_CASES.md templates."""
    import html as html_mod

    if result.status == "ok":
        keyword_safe = html_mod.escape(result.keyword)
        text = f"Автопубликация выполнена: <b>{keyword_safe}</b>"
        if result.post_url:
            text += f"\n\u2713 {result.post_url}"
        # Append cross-post results
        for xp in result.cross_post_results:
            label = html_mod.escape(_PLATFORM_LABELS.get(xp.platform, xp.platform))
            if xp.status == "ok":
                url_part = f" {xp.post_url}" if xp.post_url else ""
                text += f"\n\u2713 {label}:{url_part}"
            else:
                error_safe = html_mod.escape(xp.error or "unknown error")
                text += f"\n\u2717 {label}: {error_safe}"
        return text
    reason_safe = html_mod.escape(result.reason or "unknown")
    return _REASON_TEMPLATES.get(result.reason, f"Ошибка автопубликации: {reason_safe}")


@require_qstash_signature
async def publish_handler(request: web.Request) -> web.Response:
    """Handle QStash publish trigger with idempotency and backpressure."""
    from bot.main import PUBLISH_SEMAPHORE, SHUTDOWN_EVENT

    redis = request.app["redis"]

    # 1. Pre-semaphore shutdown check
    if SHUTDOWN_EVENT.is_set():
        return web.Response(status=503, headers={"Retry-After": "60"})

    # 2. Idempotency lock via Upstash-Message-Id (unique per trigger, same on retry)
    msg_id = request["qstash_msg_id"]
    lock_key = CacheKeys.publish_lock(msg_id)
    acquired = await redis.set(lock_key, "1", nx=True, ex=PUBLISH_LOCK_TTL)
    if not acquired:
        return web.json_response({"status": "duplicate"})

    # 3. Validate payload
    try:
        payload = PublishPayload.model_validate(request["verified_body"])
    except Exception:
        log.warning("publish_invalid_payload", body=request["verified_body"])
        return web.json_response({"status": "error", "reason": "invalid_payload"})

    # 4. Semaphore with timeout (backpressure)
    try:
        async with asyncio.timeout(300):
            async with PUBLISH_SEMAPHORE:
                # 5. Post-semaphore shutdown check
                if SHUTDOWN_EVENT.is_set():
                    await redis.delete(lock_key)
                    return web.Response(status=503, headers={"Retry-After": "60"})

                # 6. Execute pipeline
                service = PublishService(
                    db=request.app["db"],
                    redis=request.app["redis"],
                    http_client=request.app["http_client"],
                    ai_orchestrator=request.app["ai_orchestrator"],
                    image_storage=request.app["image_storage"],
                    admin_ids=request.app["settings"].admin_ids,
                    scheduler_service=request.app.get("scheduler_service"),
                    serper_client=request.app.get("serper_client"),
                    firecrawl_client=request.app.get("firecrawl_client"),
                )
                result = await service.execute(payload)

                # 7. Notify user if configured (EDGE_CASES.md notification table)
                if result.notify and result.user_id:
                    bot = request.app["bot"]
                    try:
                        text = _build_notification_text(result)
                        await bot.send_message(result.user_id, text, parse_mode="HTML")
                    except Exception:
                        log.warning("publish_notify_failed", user_id=result.user_id)

                return web.json_response({"status": result.status, "reason": result.reason})

    except TimeoutError:
        await redis.delete(lock_key)
        return web.Response(status=503, headers={"Retry-After": "120"})
    except Exception:
        log.exception("publish_handler_error")
        # Don't delete lock — prevents double publish on QStash retry.
        # Return 200 to stop QStash retries (aiohttp-handlers rule).
        # Lock expires via TTL (5 min).
        return web.json_response({"status": "error", "reason": "internal_error"})
