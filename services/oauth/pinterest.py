"""Pinterest OAuth service — exchange code for tokens + HMAC state validation.

Source of truth:
- docs/API_CONTRACTS.md section 3.6 (Pinterest API v5)
- docs/FSM_SPEC.md section 1 (ConnectPinterestFSM)
- docs/EDGE_CASES.md E20, E30

H10: State token is HMAC-protected (E30) AND single-use via Redis NX lock.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import structlog

from cache.client import RedisClient
from services.oauth.state import OAuthStateError, parse_and_verify_state

log = structlog.get_logger()

_PINTEREST_TOKEN_ENDPOINT = "https://api.pinterest.com/v5/oauth/token"  # noqa: S105
PINTEREST_AUTH_TTL = 1800  # 30 min (E20)
_OAUTH_STATE_LOCK_TTL = 600  # 10 min — single-use state lock (H10)


class PinterestOAuthError(OAuthStateError):
    """Raised when Pinterest OAuth flow fails."""

    def __init__(
        self,
        message: str = "Pinterest OAuth failed",
        user_message: str = "Не удалось подключить Pinterest",
    ) -> None:
        super().__init__(message=message, user_message=user_message)


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
        2. Ensure single-use via Redis NX lock (H10 replay protection)
        3. Exchange code for tokens via Pinterest API
        4. Store tokens in Redis with TTL (E20)
        """
        user_id, nonce = parse_and_verify_state(state, self._encryption_key)

        # H10: prevent replay attacks — state can only be used once
        lock_key = f"oauth_state_used:{nonce}"
        already_used = not await self._redis.set(lock_key, "1", ex=_OAUTH_STATE_LOCK_TTL, nx=True)
        if already_used:
            log.warning("pinterest_oauth_state_replay", user_id=user_id, nonce=nonce)
            raise PinterestOAuthError("OAuth state already used (replay)")

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
                },
                auth=httpx.BasicAuth(self._app_id, self._app_secret),
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
            raise PinterestOAuthError(f"Pinterest token exchange failed: HTTP {resp.status_code}")

        data = resp.json()
        if "access_token" not in data:
            raise PinterestOAuthError("No access_token in Pinterest response")

        expires_in = int(data.get("expires_in", 2592000))
        expires_at = (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()

        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_at": expires_at,
        }

    async def _store_tokens(self, nonce: str, tokens: dict) -> None:
        """Store tokens in Redis: pinterest_auth:{nonce}, TTL=30min (E20)."""
        key = f"pinterest_auth:{nonce}"
        await self._redis.set(key, json.dumps(tokens), ex=PINTEREST_AUTH_TTL)
