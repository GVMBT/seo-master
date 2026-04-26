"""QStash webhook для утреннего дайджеста Bamboodom (4I.4).

POST /api/bamboodom/digest — каждое утро 07:00 МСК.
Подписан QStash, обрабатывается через @require_qstash_signature.
Собирает дайджест (Метрика + blog_list + Я.Вебмастер) и шлёт в TG_ADMIN_ID.

Идемпотентность: Redis-lock по Upstash-Message-Id (5 минут).
"""

from __future__ import annotations

import structlog
from aiohttp import web

from api import require_qstash_signature
from services.analytics.digest import collect_and_render

log = structlog.get_logger()

_DIGEST_LOCK_TTL = 5 * 60


@require_qstash_signature
async def bamboodom_digest_handler(request: web.Request) -> web.Response:
    """QStash POST /api/bamboodom/digest — отправляет утренний дайджест админам."""
    redis = request.app["redis"]
    bot = request.app["bot"]
    settings = request.app["settings"]

    msg_id = request.get("qstash_msg_id", "")
    lock_key = f"bamboodom:digest_lock:{msg_id}"
    try:
        acquired = await redis.set(lock_key, "1", nx=True, ex=_DIGEST_LOCK_TTL)
    except Exception:
        acquired = True
    if not acquired:
        return web.json_response({"status": "duplicate"})

    try:
        text = await collect_and_render()
    except Exception:
        log.exception("bamboodom_digest_collect_failed")
        return web.json_response({"status": "error", "reason": "collect_failed"})

    sent = 0
    failed = 0
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
            sent += 1
        except Exception:
            failed += 1
            log.warning("bamboodom_digest_send_failed", admin_id=admin_id)

    log.info("bamboodom_digest_sent", sent=sent, failed=failed, msg_id=msg_id)
    return web.json_response({"status": "ok", "sent": sent, "failed": failed})
