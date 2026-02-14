"""Health check endpoint.

GET /api/health — public status or detailed checks with Bearer token (E29, D7).
"""

import asyncio

import structlog
from aiohttp import web

log = structlog.get_logger()

_VERSION = "2.0.0"


async def health_handler(request: web.Request) -> web.Response:
    """Health check: public or detailed depending on Bearer token."""
    auth = request.headers.get("Authorization", "")
    settings = request.app["settings"]
    token = settings.health_check_token.get_secret_value()

    # Public response (no token or invalid token) — E29: no version/details
    if not token or not auth.startswith("Bearer ") or auth[7:] != token:
        return web.json_response({"status": "ok"})

    # Detailed response
    checks: dict[str, str] = {}
    overall = "ok"

    # Database check
    try:
        db = request.app["db"]
        await db.table("users").select("id").limit(1).execute()
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"
        overall = "down"
        log.warning("health_db_failed", exc_info=True)

    # Redis check
    try:
        redis = request.app["redis"]
        is_ok = await redis.ping()
        checks["redis"] = "ok" if is_ok else "error"
        if not is_ok:
            overall = "down"
    except Exception:
        checks["redis"] = "error"
        overall = "down"
        log.warning("health_redis_failed", exc_info=True)

    # OpenRouter check (non-critical)
    try:
        http_client = request.app["http_client"]
        resp = await http_client.get("https://openrouter.ai/api/v1/models", timeout=5.0)
        checks["openrouter"] = "ok" if resp.status_code == 200 else "error"
        if resp.status_code != 200 and overall != "down":
            overall = "degraded"
    except Exception:
        checks["openrouter"] = "error"
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
        checks["qstash"] = "ok"
    except Exception:
        checks["qstash"] = "error"
        if overall != "down":
            overall = "degraded"

    return web.json_response({
        "status": overall,
        "version": _VERSION,
        "checks": checks,
    })
