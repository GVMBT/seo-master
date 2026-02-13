"""YooKassa webhook handler (aiohttp.web).

Thin handler — all logic delegated to YooKassaPaymentService.
Source of truth:
- docs/API_CONTRACTS.md §2.4 (webhook IP whitelist)
- docs/API_CONTRACTS.md §2.5 (recurring payments)
"""

import structlog
from aiohttp import web

from services.payments.yookassa import YooKassaPaymentService, verify_ip

log = structlog.get_logger()


async def yookassa_webhook(request: web.Request) -> web.Response:
    """POST /api/yookassa/webhook — process YooKassa payment notifications.

    IP whitelist verification (API_CONTRACTS.md §2.4), then delegate to service.
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

    # 3. Delegate to service (reuse singleton from app, created in bot/main.py)
    service: YooKassaPaymentService = request.app["yookassa_service"]

    try:
        await service.process_webhook(event, obj)
    except Exception:
        log.exception("yookassa_webhook_processing_error", webhook_event=event)

    # Always 200 to prevent retries
    return web.Response(status=200, text="OK")
