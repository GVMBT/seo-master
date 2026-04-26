"""Управление QStash расписанием утреннего дайджеста (4I.4).

Создаёт/удаляет одно QStash schedule, дёргающее /api/bamboodom/digest каждое
утро 07:00 МСК. Расписание сохраняет ID в Redis чтобы повторно не создавать.

Использует существующую инфру `services/scheduler.py` style — qstash.QStash
client из переменной окружения QSTASH_TOKEN.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import structlog

from bot.config import get_settings

log = structlog.get_logger()

SCHEDULE_REDIS_KEY = "bamboodom:digest:qstash_schedule_id"
DIGEST_CRON = "CRON_TZ=Europe/Moscow 0 7 * * *"  # 07:00 МСК ежедневно
DIGEST_BODY = '{"type": "bamboodom_digest"}'


def _digest_url() -> str | None:
    s = get_settings()
    base = (s.railway_public_url or "").rstrip("/")
    if not base:
        return None
    return f"{base}/api/bamboodom/digest"


async def get_schedule_id(redis: Any) -> str | None:
    try:
        raw = await redis.get(SCHEDULE_REDIS_KEY)
    except Exception:
        return None
    return str(raw) if raw else None


async def _save_schedule_id(redis: Any, schedule_id: str) -> None:
    try:
        await redis.set(SCHEDULE_REDIS_KEY, schedule_id)
    except Exception:
        log.warning("digest_schedule_save_failed", exc_info=True)


async def _clear_schedule_id(redis: Any) -> None:
    with contextlib.suppress(Exception):
        await redis.delete(SCHEDULE_REDIS_KEY)


def _qstash_client() -> Any:
    from qstash import QStash

    s = get_settings()
    return QStash(token=s.qstash_token.get_secret_value())


async def create_schedule(redis: Any) -> tuple[bool, str]:
    """Создаёт QStash schedule. Возвращает (success, message_or_id)."""
    s = get_settings()
    if not s.qstash_token.get_secret_value():
        return False, "QSTASH_TOKEN не настроен"
    url = _digest_url()
    if not url:
        return False, "RAILWAY_PUBLIC_URL не настроен"
    existing = await get_schedule_id(redis)
    if existing:
        return False, f"Расписание уже создано: {existing}"
    try:
        q = _qstash_client()

        def _create() -> str:
            res = q.schedule.create(
                destination=url,
                cron=DIGEST_CRON,
                body=DIGEST_BODY,
                content_based_deduplication=False,
            )
            return str(res)

        schedule_id = await asyncio.to_thread(_create)
    except Exception as exc:
        log.warning("digest_schedule_create_failed", exc_info=True)
        return False, f"QStash error: {exc}"
    await _save_schedule_id(redis, schedule_id)
    return True, schedule_id


async def delete_schedule(redis: Any) -> tuple[bool, str]:
    schedule_id = await get_schedule_id(redis)
    if not schedule_id:
        return False, "Расписание не найдено"
    try:
        q = _qstash_client()

        def _delete() -> None:
            q.schedule.delete(schedule_id)

        await asyncio.to_thread(_delete)
    except Exception as exc:
        log.warning("digest_schedule_delete_failed", exc_info=True)
        return False, f"QStash error: {exc}"
    await _clear_schedule_id(redis)
    return True, schedule_id


async def status(redis: Any) -> dict[str, Any]:
    sid = await get_schedule_id(redis)
    return {
        "active": bool(sid),
        "schedule_id": sid,
        "cron": DIGEST_CRON,
        "url": _digest_url(),
    }
