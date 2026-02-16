"""QStash notification webhook handler.

POST /api/notify — send batch notifications (low_balance, weekly_digest, reactivation).
Always returns 200.
"""

import asyncio

import structlog
from aiogram import Bot
from aiohttp import web

from api import require_qstash_signature
from api.models import NotifyPayload
from cache.keys import NOTIFY_LOCK_TTL, CacheKeys
from services.notifications import NotifyService

log = structlog.get_logger()


@require_qstash_signature
async def notify_handler(request: web.Request) -> web.Response:
    """Handle QStash notification trigger with idempotency."""
    redis = request.app["redis"]

    # Idempotency lock via Upstash-Message-Id
    msg_id = request["qstash_msg_id"]
    lock_key = CacheKeys.notify_lock(msg_id)
    acquired = await redis.set(lock_key, "1", nx=True, ex=NOTIFY_LOCK_TTL)
    if not acquired:
        return web.json_response({"status": "duplicate"})

    try:
        payload = NotifyPayload.model_validate(request["verified_body"])
    except Exception:
        log.warning("notify_invalid_payload", body=request["verified_body"])
        return web.json_response({"status": "error", "reason": "invalid_payload"})

    try:
        service = NotifyService(db=request.app["db"])

        if payload.type == "low_balance":
            recipients = await service.build_low_balance()
        elif payload.type == "weekly_digest":
            recipients = await service.build_weekly_digest()
        elif payload.type == "reactivation":
            recipients = await service.build_reactivation()
        else:
            return web.json_response({"status": "error", "reason": "unknown_type"})

        sent, failed = await _send_notifications(request.app["bot"], recipients)

        return web.json_response(
            {
                "status": "ok",
                "type": payload.type,
                "sent": sent,
                "failed": failed,
            }
        )

    except Exception:
        log.exception("notify_handler_error")
        return web.json_response({"status": "error", "reason": "internal_error"})


async def _send_notifications(bot: Bot, recipients: list[tuple[int, str]]) -> tuple[int, int]:
    """Send notifications with rate limiting and error handling (D6).

    Returns (sent_count, failed_count).
    """
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

    sent, failed = 0, 0
    for user_id, text in recipients:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML")
            sent += 1
        except TelegramRetryAfter as e:
            log.warning("notify_rate_limited", retry_after=e.retry_after)
            await asyncio.sleep(e.retry_after)
            try:
                await bot.send_message(user_id, text, parse_mode="HTML")
                sent += 1
            except Exception:
                failed += 1
        except TelegramForbiddenError:
            failed += 1  # User blocked bot
        except Exception:
            log.warning("notify_send_error", user_id=user_id)
            failed += 1
        await asyncio.sleep(0.05)  # 20 msg/sec rate limit
    return sent, failed
