"""QStash YooKassa subscription renewal handler.

POST /api/yookassa/renew — triggered by QStash cron every 30 days.
Source of truth: API_CONTRACTS.md §2.5 step 3.
Idempotency: Redis NX lock `yookassa_renew:{user_id}` (TTL 1h).
"""

import structlog
from aiohttp import web

from api import require_qstash_signature
from api.models import RenewPayload
from cache.keys import RENEW_LOCK_TTL, CacheKeys
from services.payments.yookassa import YooKassaPaymentService

log = structlog.get_logger()


@require_qstash_signature
async def renew_handler(request: web.Request) -> web.Response:
    """POST /api/yookassa/renew — auto-renew YooKassa subscription.

    Always returns 200 (QStash will retry on non-2xx).
    On failure: logs error, does NOT retry (to avoid duplicate payments).
    """
    body = request["verified_body"]

    try:
        payload = RenewPayload.model_validate(body)
    except Exception:
        log.warning("renew_invalid_payload", body=body)
        return web.json_response({"status": "error", "reason": "invalid_payload"})

    # Idempotency lock per user (TTL 1h — one renewal per hour max)
    redis = request.app["redis"]
    lock_key = CacheKeys.renew_lock(payload.user_id)
    acquired = await redis.set(lock_key, "1", nx=True, ex=RENEW_LOCK_TTL)
    if not acquired:
        log.info("renew_duplicate", user_id=payload.user_id)
        return web.json_response({"status": "ok", "reason": "duplicate"})

    service: YooKassaPaymentService = request.app["yookassa_service"]

    try:
        success = await service.renew_subscription(
            user_id=payload.user_id,
            payment_method_id=payload.payment_method_id,
            package_name=payload.package,
        )
    except Exception:
        log.exception("renew_error", user_id=payload.user_id)
        return web.json_response({"status": "error", "reason": "service_error"})

    if not success:
        # Notify user about failed renewal (E37)
        bot = request.app["bot"]
        try:
            await bot.send_message(
                payload.user_id,
                "Не удалось продлить подписку. Проверьте способ оплаты.\n"
                "[Управление подпиской → /start]",
            )
        except Exception:
            log.warning("renew_notify_failed", user_id=payload.user_id)

    status = "ok" if success else "error"
    return web.json_response({"status": status, "renewed": success})
