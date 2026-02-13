"""Pinterest OAuth callback handler (aiohttp.web).

Thin handler — all logic delegated to PinterestOAuthService.
Source of truth:
- docs/ARCHITECTURE.md section 2.3 (aiohttp routes)
- docs/FSM_SPEC.md section 1 (ConnectPinterestFSM)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)
"""

from urllib.parse import quote

import structlog
from aiohttp import web

from api.auth_service import PinterestOAuthError, PinterestOAuthService
from bot.config import get_settings

log = structlog.get_logger()


async def pinterest_callback(request: web.Request) -> web.Response:
    """GET /api/auth/pinterest/callback?code=xxx&state=user_id_nonce_hmac."""
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
        return web.Response(status=403, text="Authorization failed. Please try again.")

    bot_username: str = request.app["bot_username"]
    deep_link = f"tg://resolve?domain={quote(bot_username)}&start=pinterest_auth_{quote(nonce)}"
    raise web.HTTPFound(location=deep_link)
