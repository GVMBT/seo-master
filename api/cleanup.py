"""QStash daily cleanup webhook handler.

POST /api/cleanup — expire drafts, refund tokens, delete old logs.
Always returns 200.
"""

import structlog
from aiohttp import web

from api import require_qstash_signature
from api.models import CleanupPayload
from cache.keys import CLEANUP_LOCK_TTL, CacheKeys
from services.cleanup import CleanupService

log = structlog.get_logger()


@require_qstash_signature
async def cleanup_handler(request: web.Request) -> web.Response:
    """Handle QStash cleanup trigger with idempotency."""
    redis = request.app["redis"]

    # Idempotency lock via Upstash-Message-Id
    msg_id = request["qstash_msg_id"]
    lock_key = CacheKeys.cleanup_lock(msg_id)
    acquired = await redis.set(lock_key, "1", nx=True, ex=CLEANUP_LOCK_TTL)
    if not acquired:
        return web.json_response({"status": "duplicate"})

    try:
        CleanupPayload.model_validate(request["verified_body"])
    except Exception:
        log.warning("cleanup_invalid_payload", body=request["verified_body"])
        return web.json_response({"status": "error", "reason": "invalid_payload"})

    try:
        service = CleanupService(
            db=request.app["db"],
            http_client=request.app["http_client"],
            image_storage=request.app["image_storage"],
            admin_ids=request.app["settings"].admin_ids,
        )
        result = await service.execute()

        # Notify users about refunded previews (refund = balance notification)
        bot = request.app["bot"]
        for entry in result.refunded:
            if not entry.get("notify_balance", True):
                continue
            try:
                text = f"Превью «{entry['keyword']}» истекло.\nВозвращено {entry['tokens_refunded']} токенов."
                await bot.send_message(entry["user_id"], text)
            except Exception:
                log.warning("cleanup_notify_failed", user_id=entry["user_id"])

        return web.json_response(
            {
                "status": "ok",
                "expired": result.expired_count,
                "refunds": len(result.refunded),
                "logs_deleted": result.logs_deleted,
            }
        )

    except Exception:
        log.exception("cleanup_handler_error")
        return web.json_response({"status": "error", "reason": "internal_error"})
