"""VK ID OAuth 2.1 callback handlers (aiohttp.web).

Thin handlers — all logic delegated to VKOAuthService.
Source of truth:
- docs/ARCHITECTURE.md section 2.3 (aiohttp routes)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)
"""

import html
import secrets
from urllib.parse import quote

import sentry_sdk
import structlog
from aiohttp import web

from bot.config import get_settings
from services.oauth.vk import VKOAuthError, VKOAuthService

log = structlog.get_logger()


def _build_vk_oauth_service(request: web.Request) -> VKOAuthService:
    """Build VKOAuthService from app context."""
    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    redirect_uri = f"{base_url}/api/auth/vk/callback"
    return VKOAuthService(
        http_client=request.app["http_client"],
        redis=request.app["redis"],
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=settings.vk_app_id,
        redirect_uri=redirect_uri,
    )


async def vk_auth_redirect(request: web.Request) -> web.Response:
    """GET /api/auth/vk?user_id=123&nonce=abc — redirect to VK ID authorize."""
    user_id_raw = request.query.get("user_id", "")
    nonce = request.query.get("nonce", "")
    if not user_id_raw or not nonce:
        return web.Response(status=400, text="Missing user_id or nonce")

    try:
        user_id = int(user_id_raw)
    except ValueError:
        return web.Response(status=400, text="Invalid user_id")

    service = _build_vk_oauth_service(request)
    authorize_url, code_verifier, _state = service.build_authorize_url(user_id, nonce)
    await service.store_pkce(nonce, code_verifier, user_id)

    raise web.HTTPFound(location=authorize_url)


async def vk_auth_callback(request: web.Request) -> web.Response:
    """GET /api/auth/vk/callback?code=xxx&state=yyy&device_id=zzz."""
    # Handle user denial
    error = request.query.get("error")
    if error:
        error_desc = request.query.get("error_description", "Authorization denied")
        log.warning("vk_oauth_user_denied", error=error, description=error_desc)
        safe_desc = html.escape(error_desc, quote=True)
        return web.Response(
            status=200,
            content_type="text/html",
            text=f"<h3>Авторизация отменена</h3><p>{safe_desc}</p>"
            "<p>Вернитесь в бот и попробуйте снова.</p>",
        )

    code = request.query.get("code", "")
    state = request.query.get("state", "")
    device_id = request.query.get("device_id", "")
    if not code or not state:
        return web.Response(status=400, text="Missing code or state")

    if not device_id:
        # device_id is required by VK ID for token exchange
        device_id = secrets.token_hex(16)
        log.warning("vk_oauth_missing_device_id", msg="Generated fallback device_id")

    service = _build_vk_oauth_service(request)

    try:
        _user_id, nonce = await service.handle_callback(code, state, device_id)
    except VKOAuthError:
        log.exception("vk_callback_failed")
        sentry_sdk.capture_exception()
        return web.Response(status=403, text="Authorization failed. Please try again.")

    bot_username: str = request.app["bot_username"]
    deep_link = f"tg://resolve?domain={quote(bot_username)}&start=vk_auth_{quote(nonce)}"
    raise web.HTTPFound(location=deep_link)
