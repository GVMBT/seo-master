"""YooKassa webhook handler (aiohttp.web).

Thin handler -- all logic delegated to YooKassaPaymentService.
Source of truth:
- docs/API_CONTRACTS.md §2.4 (webhook IP whitelist)
- docs/API_CONTRACTS.md §2.5 (recurring payments)
- EDGE_CASES.md E39 (idempotency by object.id)
"""

import structlog
from aiohttp import web

from cache.client import RedisClient
from cache.keys import CacheKeys
from services.payments.yookassa import YooKassaPaymentService, verify_ip

log = structlog.get_logger()

# H16: idempotency lock TTL for YooKassa webhooks (24 hours)
_YOOKASSA_IDEMPOTENCY_TTL = 86400


async def yookassa_webhook(request: web.Request) -> web.Response:
    """POST /api/yookassa/webhook -- process YooKassa payment notifications.

    IP whitelist verification (API_CONTRACTS.md §2.4), then delegate to service.
    H16: Redis NX idempotency lock on payment_id (E39).
    Always returns 200 to prevent retries.
    """
    # 1. Verify IP
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.remote or ""
    if not verify_ip(client_ip):
        log.warning("yookassa_webhook_ip_rejected", ip=client_ip)
        return web.Response(status=403, text="Forbidden")

    # 2. Parse body
    try:
        body = await request.json()
    except Exception:
        log.warning("yookassa_webhook_invalid_json")
        return web.Response(status=400, text="Invalid JSON")

    event = body.get("event", "")
    obj = body.get("object", {})

    if not event or not obj:
        log.warning("yookassa_webhook_missing_fields", body_keys=list(body.keys()))
        return web.Response(status=200, text="OK")

    # H16: Redis NX idempotency lock on object.id (E39: prevent replay)
    payment_id = obj.get("id", "")
    if payment_id and event == "payment.succeeded":
        redis: RedisClient = request.app["redis"]
        lock_key = CacheKeys.yookassa_idempotency(payment_id)
        acquired = await redis.set(lock_key, "1", ex=_YOOKASSA_IDEMPOTENCY_TTL, nx=True)
        if not acquired:
            log.warning("yookassa_webhook_duplicate", payment_id=payment_id, webhook_event=event)
            return web.Response(status=200, text="OK")

    # 3. Delegate to service (reuse singleton from app, created in bot/main.py)
    service: YooKassaPaymentService = request.app["yookassa_service"]

    try:
        notification = await service.process_webhook(event, obj)

        # Send user notification if service returned one (e.g. canceled payment)
        if notification and notification.get("user_id"):
            try:
                bot = request.app["bot"]
                await bot.send_message(notification["user_id"], notification["text"])
            except Exception:
                log.warning("yookassa_notify_failed", user_id=notification["user_id"])
    except Exception:
        log.exception("yookassa_webhook_processing_error", webhook_event=event)

    # Always 200 to prevent retries
    return web.Response(status=200, text="OK")
