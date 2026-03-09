"""Pinterest OAuth redirect + callback handlers (aiohttp.web).

Thin handlers — all logic delegated to PinterestOAuthService.
Source of truth:
- docs/ARCHITECTURE.md section 2.3 (aiohttp routes)
- docs/FSM_SPEC.md section 1 (ConnectPinterestFSM)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)
"""

from urllib.parse import quote, urlencode

import sentry_sdk
import structlog
from aiohttp import web

from bot.config import get_settings
from services.oauth.pinterest import PinterestOAuthError, PinterestOAuthService
from services.oauth.state import build_state

log = structlog.get_logger()

_PINTEREST_AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
_PINTEREST_SCOPES = "boards:read,pins:read,pins:write"


async def pinterest_redirect(request: web.Request) -> web.Response:
    """GET /api/auth/pinterest?user_id=123&nonce=abc — redirect to Pinterest OAuth."""
    user_id_raw = request.query.get("user_id", "")
    nonce = request.query.get("nonce", "")
    if not user_id_raw or not nonce:
        return web.Response(status=400, text="Missing user_id or nonce")

    try:
        user_id = int(user_id_raw)
    except ValueError:
        return web.Response(status=400, text="Invalid user_id")

    settings = get_settings()
    state = build_state(user_id, nonce, settings.encryption_key.get_secret_value())
    redirect_uri = f"{settings.railway_public_url}/api/auth/pinterest/callback"

    params = urlencode({
        "response_type": "code",
        "client_id": settings.pinterest_app_id,
        "redirect_uri": redirect_uri,
        "scope": _PINTEREST_SCOPES,
        "state": state,
    })
    raise web.HTTPFound(location=f"{_PINTEREST_AUTHORIZE_URL}?{params}")


async def pinterest_callback(request: web.Request) -> web.Response:
    """GET /api/auth/pinterest/callback?code=xxx&state=user_id_nonce_hmac."""
    # Handle Pinterest error redirect (user denied or Pinterest returned error)
    error = request.query.get("error", "")
    if error:
        log.warning("pinterest_callback_error_param", error=error)
        bot_username: str = request.app["bot_username"]
        deep_link = f"tg://resolve?domain={quote(bot_username)}&start=pinterest_error"
        raise web.HTTPFound(location=deep_link)

    code = request.query.get("code", "")
    state = request.query.get("state", "")
    if not code or not state:
        return web.Response(status=400, text="Missing code or state")

    settings = get_settings()
    redirect_uri = f"{settings.railway_public_url}/api/auth/pinterest/callback"
    service = PinterestOAuthService(
        http_client=request.app["http_client"],
        redis=request.app["redis"],
        encryption_key=settings.encryption_key.get_secret_value(),
        pinterest_app_id=settings.pinterest_app_id,
        pinterest_app_secret=settings.pinterest_app_secret.get_secret_value(),
        redirect_uri=redirect_uri,
    )

    try:
        _user_id, nonce = await service.handle_callback(code, state)
    except PinterestOAuthError:
        log.exception("pinterest_callback_failed")
        sentry_sdk.capture_exception()
        bot_username_err: str = request.app["bot_username"]
        deep_link_err = f"tg://resolve?domain={quote(bot_username_err)}&start=pinterest_error"
        raise web.HTTPFound(location=deep_link_err) from None

    bot_username_ok: str = request.app["bot_username"]
    deep_link = f"tg://resolve?domain={quote(bot_username_ok)}&start=pinterest_auth_{quote(nonce)}"
    raise web.HTTPFound(location=deep_link)
