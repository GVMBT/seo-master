"""QStash auto-publish webhook handler.

POST /api/publish — thin aiohttp wrapper.
Always returns 200 (except semaphore timeout -> 503).
"""

import asyncio

import structlog
from aiohttp import web

from api import require_qstash_signature
from api.models import PublishPayload
from cache.keys import PUBLISH_LOCK_TTL, CacheKeys
from services.publish import PublishService

log = structlog.get_logger()


@require_qstash_signature
async def publish_handler(request: web.Request) -> web.Response:
    """Handle QStash publish trigger with idempotency and backpressure."""
    from bot.main import PUBLISH_SEMAPHORE, SHUTDOWN_EVENT

    redis = request.app["redis"]

    # 1. Pre-semaphore shutdown check
    if SHUTDOWN_EVENT.is_set():
        return web.Response(status=503, headers={"Retry-After": "60"})

    # 2. Idempotency lock via Upstash-Message-Id
    msg_id = request["qstash_msg_id"]
    lock_key = CacheKeys.publish_lock(msg_id)
    acquired = await redis.set(lock_key, "1", nx=True, ex=PUBLISH_LOCK_TTL)
    if not acquired:
        return web.json_response({"status": "duplicate"})

    # 3. Semaphore with timeout (backpressure)
    try:
        async with asyncio.timeout(300):
            async with PUBLISH_SEMAPHORE:
                # 4. Post-semaphore shutdown check
                if SHUTDOWN_EVENT.is_set():
                    await redis.delete(lock_key)
                    return web.Response(status=503, headers={"Retry-After": "60"})

                # 5. Validate and execute
                try:
                    payload = PublishPayload.model_validate(request["verified_body"])
                except Exception:
                    log.warning("publish_invalid_payload", body=request["verified_body"])
                    return web.json_response({"status": "error", "reason": "invalid_payload"})

                service = PublishService(
                    db=request.app["db"],
                    redis=request.app["redis"],
                    http_client=request.app["http_client"],
                    ai_orchestrator=request.app["ai_orchestrator"],
                    image_storage=request.app["image_storage"],
                    admin_id=request.app["settings"].admin_id,
                )
                result = await service.execute(payload)

                # 6. Notify user if configured
                if result.notify and result.user_id:
                    bot = request.app["bot"]
                    try:
                        if result.status == "ok":
                            text = f"Автопубликация выполнена: {result.keyword}"
                            if result.post_url:
                                text += f"\n{result.post_url}"
                        else:
                            text = f"Ошибка автопубликации: {result.reason}"
                        await bot.send_message(result.user_id, text)
                    except Exception:
                        log.warning("publish_notify_failed", user_id=result.user_id)

                return web.json_response({"status": result.status, "reason": result.reason})

    except TimeoutError:
        await redis.delete(lock_key)
        return web.Response(status=503, headers={"Retry-After": "120"})
    except Exception:
        log.exception("publish_handler_error")
        await redis.delete(lock_key)
        return web.json_response({"status": "error", "reason": "internal_error"})
