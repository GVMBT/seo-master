"""Pinterest OAuth service — exchange code for tokens + HMAC state validation.

Source of truth:
- docs/API_CONTRACTS.md section 3.6 (Pinterest API v5)
- docs/FSM_SPEC.md section 1 (ConnectPinterestFSM)
- docs/EDGE_CASES.md E20, E30
"""

import hashlib
import hmac
import json

import httpx
import structlog

from bot.exceptions import AppError
from cache.client import RedisClient

log = structlog.get_logger()

_PINTEREST_TOKEN_ENDPOINT = "https://api.pinterest.com/v5/oauth/token"  # noqa: S105
PINTEREST_AUTH_TTL = 1800  # 30 min (E20)


class PinterestOAuthError(AppError):
    """Raised when Pinterest OAuth flow fails."""

    def __init__(
        self,
        message: str = "Pinterest OAuth failed",
        user_message: str = "Не удалось подключить Pinterest",  # noqa: RUF001
    ) -> None:
        super().__init__(message=message, user_message=user_message)


def build_state(user_id: int, nonce: str, encryption_key: str) -> str:
    """Build state param: {user_id}_{nonce}_{hmac_hex}.

    HMAC-SHA256(user_id + nonce, ENCRYPTION_KEY) prevents CSRF (E30).
    """
    payload = f"{user_id}_{nonce}"
    mac = hmac.new(
        encryption_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}_{mac}"


def parse_and_verify_state(
    state: str,
    encryption_key: str,
) -> tuple[int, str]:
    """Parse state param and verify HMAC. Returns (user_id, nonce).

    State format: {user_id}_{nonce}_{hmac_hex}
    Raises PinterestOAuthError on invalid/tampered state (E30).
    """
    parts = state.split("_", maxsplit=2)
    expected_parts = 3
    if len(parts) != expected_parts:
        raise PinterestOAuthError("Invalid state format")

    raw_user_id, nonce, received_mac = parts

    try:
        user_id = int(raw_user_id)
    except ValueError as err:
        raise PinterestOAuthError("Invalid user_id in state") from err

    expected_mac = hmac.new(
        encryption_key.encode(),
        f"{user_id}_{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_mac, received_mac):
        log.warning("pinterest_oauth_hmac_mismatch", user_id=user_id)
        raise PinterestOAuthError("State HMAC verification failed (E30)")

    return user_id, nonce


class PinterestOAuthService:
    """Exchange Pinterest OAuth code for tokens and store in Redis."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        redis: RedisClient,
        encryption_key: str,
        pinterest_app_id: str,
        pinterest_app_secret: str,
        redirect_uri: str,
    ) -> None:
        self._http = http_client
        self._redis = redis
        self._encryption_key = encryption_key
        self._app_id = pinterest_app_id
        self._app_secret = pinterest_app_secret
        self._redirect_uri = redirect_uri

    async def handle_callback(
        self,
        code: str,
        state: str,
    ) -> tuple[int, str]:
        """Full OAuth callback flow. Returns (user_id, nonce).

        1. Validate HMAC state (E30)
        2. Exchange code for tokens via Pinterest API
        3. Store tokens in Redis with TTL (E20)
        """
        user_id, nonce = parse_and_verify_state(state, self._encryption_key)

        tokens = await self._exchange_code(code)

        await self._store_tokens(nonce, tokens)

        log.info(
            "pinterest_oauth_success",
            user_id=user_id,
            nonce=nonce,
        )
        return user_id, nonce

    async def _exchange_code(self, code: str) -> dict:
        """Exchange authorization code for access + refresh tokens."""
        try:
            resp = await self._http.post(
                _PINTEREST_TOKEN_ENDPOINT,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                    "client_id": self._app_id,
                    "client_secret": self._app_secret,
                },
            )
        except httpx.HTTPError as exc:
            log.error("pinterest_token_exchange_http_error", error=str(exc))
            raise PinterestOAuthError(f"HTTP error during token exchange: {exc}") from exc

        if resp.status_code != 200:
            log.error(
                "pinterest_token_exchange_failed",
                status=resp.status_code,
                body=resp.text[:500],
            )
            raise PinterestOAuthError(
                f"Pinterest token exchange failed: HTTP {resp.status_code}"
            )

        data = resp.json()
        if "access_token" not in data:
            raise PinterestOAuthError("No access_token in Pinterest response")

        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_in": data.get("expires_in", 2592000),
        }

    async def _store_tokens(self, nonce: str, tokens: dict) -> None:
        """Store tokens in Redis: pinterest_auth:{nonce}, TTL=30min (E20)."""
        key = f"pinterest_auth:{nonce}"
        await self._redis.set(key, json.dumps(tokens), ex=PINTEREST_AUTH_TTL)
