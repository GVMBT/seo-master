"""Google OAuth 2.0 client для GSC (4G).

Standard OAuth Code Flow:
1. /api/auth/google/redirect — генерим URL и редиректим
2. user authorize в Google → callback /api/auth/google/callback?code=...
3. Обмен code на access_token + refresh_token
4. Сохраняем refresh_token в Redis (yandex и google разделены)
5. При API-вызовах: используем refresh_token для получения свежего access_token
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx
import structlog

log = structlog.get_logger()

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105
_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"


class GoogleTokenError(Exception):
    """Ошибка обмена кода на токен / рефреша токена."""


def build_auth_url(client_id: str, redirect_uri: str, state: str = "") -> str:
    """Собирает URL для редиректа пользователя на Google authorize."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": _SCOPE,
        "access_type": "offline",  # запрашиваем refresh_token
        "prompt": "consent",  # принудительно показываем consent (чтобы получить refresh)
        "state": state or "bamboodom-gsc",
    }
    return f"{_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Обменивает code на {access_token, refresh_token, expires_in, scope}."""
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        if http_client is not None:
            resp = await http_client.post(_TOKEN_URL, data=data, timeout=15.0)
        else:
            async with httpx.AsyncClient(timeout=15.0) as c:
                resp = await c.post(_TOKEN_URL, data=data, timeout=15.0)
    except httpx.HTTPError as exc:
        raise GoogleTokenError(f"network: {exc}") from exc
    if resp.status_code >= 400:
        raise GoogleTokenError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()


async def refresh_access_token(
    refresh_token: str,
    client_id: str,
    client_secret: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Получить свежий access_token из refresh_token."""
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        if http_client is not None:
            resp = await http_client.post(_TOKEN_URL, data=data, timeout=15.0)
        else:
            async with httpx.AsyncClient(timeout=15.0) as c:
                resp = await c.post(_TOKEN_URL, data=data, timeout=15.0)
    except httpx.HTTPError as exc:
        raise GoogleTokenError(f"network: {exc}") from exc
    if resp.status_code >= 400:
        raise GoogleTokenError(f"HTTP {resp.status_code}: {resp.text[:300]}")
    return resp.json()
