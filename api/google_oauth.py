"""OAuth Google для GSC (4G).

Два endpoint:
- GET /api/auth/google/redirect — формирует URL и редиректит юзера на Google authorize
- GET /api/auth/google/callback?code=... — принимает code, обменивает на refresh_token,
  сохраняет в Redis. Юзеру показываем простую HTML-страничку «успех».

Безопасность:
- В redirect добавляем `state` — короткий токен из Redis (TTL 10 минут).
- В callback сверяем state. Без state callback не работает.
"""

from __future__ import annotations

import contextlib
import secrets

import structlog
from aiohttp import web

from bot.config import get_settings
from integrations.google_search_console.client import GSC_REFRESH_REDIS_KEY
from integrations.google_search_console.oauth import (
    build_auth_url,
    exchange_code_for_tokens,
)

log = structlog.get_logger()

_STATE_PREFIX = "bamboodom:gsc:oauth_state:"
_STATE_TTL = 600  # 10 минут


def _redirect_uri() -> str:
    s = get_settings()
    base = (s.railway_public_url or "").rstrip("/")
    return f"{base}/api/auth/google/callback"


async def google_redirect_handler(request: web.Request) -> web.Response:
    """Стартует OAuth-flow."""
    redis = request.app["redis"]
    settings = request.app["settings"]
    if not settings.google_oauth_client_id:
        return web.Response(status=500, text="GOOGLE_OAUTH_CLIENT_ID не настроен")

    state = secrets.token_urlsafe(16)
    try:
        await redis.set(_STATE_PREFIX + state, "1", ex=_STATE_TTL)
    except Exception:
        log.warning("gsc_state_save_failed", exc_info=True)

    url = build_auth_url(settings.google_oauth_client_id, _redirect_uri(), state=state)
    raise web.HTTPFound(location=url)


async def google_callback_handler(request: web.Request) -> web.Response:
    """Принимает code от Google, обменивает на refresh_token."""
    redis = request.app["redis"]
    settings = request.app["settings"]

    code = request.query.get("code")
    state = request.query.get("state")
    err = request.query.get("error")
    if err:
        return web.Response(status=400, text=f"Google вернул ошибку: {err}")
    if not code or not state:
        return web.Response(status=400, text="Нет code/state в запросе")

    try:
        ok = await redis.get(_STATE_PREFIX + state)
    except Exception:
        ok = None
    if not ok:
        return web.Response(status=400, text="state не найден или истёк (>10 минут)")
    with contextlib.suppress(Exception):
        await redis.delete(_STATE_PREFIX + state)

    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret.get_secret_value():
        return web.Response(status=500, text="GOOGLE_OAUTH_* не настроены")

    try:
        tokens = await exchange_code_for_tokens(
            code=code,
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret.get_secret_value(),
            redirect_uri=_redirect_uri(),
        )
    except Exception as exc:
        log.warning("gsc_token_exchange_failed", exc_info=True)
        return web.Response(status=500, text=f"Ошибка обмена кода: {exc}")

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return web.Response(
            status=400,
            text="Google не вернул refresh_token. Проверьте что в URL был prompt=consent. "
            "Также попробуйте отозвать приложение в Google Account и повторить.",
        )

    try:
        await redis.set(GSC_REFRESH_REDIS_KEY, str(refresh_token))
    except Exception:
        log.warning("gsc_refresh_save_failed", exc_info=True)
        return web.Response(status=500, text="Не удалось сохранить refresh_token")

    log.info("gsc_authorized")
    return web.Response(
        text=(
            "<!doctype html><html><body style='font-family:sans-serif'>"
            "<h2>✅ Google Search Console подключён</h2>"
            "<p>Refresh-токен сохранён. Возвращайтесь в Telegram-бот.</p>"
            "</body></html>"
        ),
        content_type="text/html",
    )
