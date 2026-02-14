"""Health check endpoint.

GET /api/health — public status or detailed checks with Bearer token (E29, §5.3).
"""

import asyncio
import time
from typing import Any

import structlog
from aiohttp import web

log = structlog.get_logger()

_VERSION = "2.0.0"
_START_TIME = time.monotonic()


async def health_handler(request: web.Request) -> web.Response:
    """Health check: public or detailed depending on Bearer token."""
    auth = request.headers.get("Authorization", "")
    settings = request.app["settings"]
    token = settings.health_check_token.get_secret_value()

    # Public response (no token or invalid token) — E29: no version/details
    if not token or not auth.startswith("Bearer ") or auth[7:] != token:
        return web.json_response({"status": "ok"})

    # Detailed response (ARCHITECTURE.md §5.3)
    checks: dict[str, dict[str, Any]] = {}
    overall = "ok"

    # Database check (with latency)
    t0 = time.monotonic()
    try:
        db = request.app["db"]
        await db.table("users").select("id").limit(1).execute()
        checks["database"] = {"status": "ok", "latency_ms": round((time.monotonic() - t0) * 1000)}
    except Exception:
        checks["database"] = {"status": "error", "latency_ms": round((time.monotonic() - t0) * 1000)}
        overall = "down"
        log.warning("health_db_failed", exc_info=True)

    # Redis check (with latency)
    t0 = time.monotonic()
    try:
        redis = request.app["redis"]
        is_ok = await redis.ping()
        latency = round((time.monotonic() - t0) * 1000)
        if is_ok:
            checks["redis"] = {"status": "ok", "latency_ms": latency}
        else:
            checks["redis"] = {"status": "error", "latency_ms": latency}
            overall = "down"
    except Exception:
        checks["redis"] = {"status": "error", "latency_ms": round((time.monotonic() - t0) * 1000)}
        overall = "down"
        log.warning("health_redis_failed", exc_info=True)

    # OpenRouter check (non-critical, no latency per §5.3)
    try:
        http_client = request.app["http_client"]
        resp = await http_client.get("https://openrouter.ai/api/v1/models", timeout=5.0)
        checks["openrouter"] = {"status": "ok" if resp.status_code == 200 else "error"}
        if resp.status_code != 200 and overall != "down":
            overall = "degraded"
    except Exception:
        checks["openrouter"] = {"status": "error"}
        if overall != "down":
            overall = "degraded"

    # QStash check (non-critical, sync SDK wrapped in thread)
    try:
        from qstash import QStash

        qstash_token = settings.qstash_token.get_secret_value()

        def _qstash_check() -> None:
            q = QStash(token=qstash_token)
            q.schedule.list()

        await asyncio.to_thread(_qstash_check)
        checks["qstash"] = {"status": "ok"}
    except Exception:
        checks["qstash"] = {"status": "error"}
        if overall != "down":
            overall = "degraded"

    return web.json_response({
        "status": overall,
        "version": _VERSION,
        "uptime_seconds": round(time.monotonic() - _START_TIME),
        "checks": checks,
    })
