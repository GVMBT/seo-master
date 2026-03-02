"""VK ID OAuth 2.1 service — PKCE Authorization Code Flow.

VK migrated to OAuth 2.1 (id.vk.com), Implicit Flow no longer works.
All token exchanges require PKCE (code_verifier + code_challenge S256).

Source of truth:
- docs/API_CONTRACTS.md section 3.5 (VK API)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)

Key facts (verified Feb 2026):
- Authorize: https://id.vk.com/authorize
- Token exchange: POST https://id.vk.com/oauth2/auth (x-www-form-urlencoded)
- access_token TTL: 3600s (60 min), refresh_token TTL: 180 days
- device_id: returned in callback, required for token exchange and refresh
- scope offline: disabled — use refresh_token instead
"""

import base64
import hashlib
import json
import secrets

import httpx
import structlog

from api.auth_service import PinterestOAuthError, build_state, parse_and_verify_state
from bot.exceptions import AppError
from cache.client import RedisClient
from cache.keys import VK_AUTH_TTL, CacheKeys

log = structlog.get_logger()

_VK_AUTHORIZE_URL = "https://id.vk.com/authorize"
_VK_TOKEN_URL = "https://id.vk.com/oauth2/auth"  # noqa: S105
_OAUTH_STATE_LOCK_TTL = 600  # 10 min — single-use state lock (H10)

VK_API_VERSION = "5.199"
VK_API_URL = "https://api.vk.ru/method"


class VKOAuthError(AppError):
    """Raised when VK OAuth flow fails."""

    def __init__(
        self,
        message: str = "VK OAuth failed",
        user_message: str = "Не удалось подключить VK",
    ) -> None:
        super().__init__(message=message, user_message=user_message)


def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


class VKOAuthService:
    """VK ID OAuth 2.1 + PKCE — exchange code for tokens, fetch groups."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        redis: RedisClient,
        encryption_key: str,
        vk_app_id: int,
        redirect_uri: str,
    ) -> None:
        self._http = http_client
        self._redis = redis
        self._encryption_key = encryption_key
        self._app_id = vk_app_id
        self._redirect_uri = redirect_uri

    def build_authorize_url(self, user_id: int, nonce: str) -> tuple[str, str, str]:
        """Build VK ID authorize URL with PKCE + HMAC state.

        Returns (authorize_url, code_verifier, state).
        Caller must await store_pkce() to persist code_verifier in Redis.
        """
        code_verifier, code_challenge = _generate_pkce()
        state = build_state(user_id, nonce, self._encryption_key)

        params = (
            f"response_type=code"
            f"&client_id={self._app_id}"
            f"&redirect_uri={self._redirect_uri}"
            f"&scope=wall,groups,photos"
            f"&state={state}"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
        )
        return f"{_VK_AUTHORIZE_URL}?{params}", code_verifier, state

    async def store_pkce(self, nonce: str, code_verifier: str, user_id: int) -> None:
        """Store PKCE code_verifier + user_id in Redis (TTL 30 min)."""
        data = json.dumps({"code_verifier": code_verifier, "user_id": user_id})
        await self._redis.set(CacheKeys.vk_auth(nonce), data, ex=VK_AUTH_TTL)

    async def handle_callback(
        self,
        code: str,
        state: str,
        device_id: str,
    ) -> tuple[int, str]:
        """Full OAuth callback flow. Returns (user_id, nonce).

        1. Validate HMAC state (E30)
        2. Ensure single-use via Redis NX lock (H10)
        3. Retrieve code_verifier from Redis
        4. Exchange code for tokens via VK ID API
        5. Fetch user's admin/editor groups
        6. Store tokens + groups in Redis
        """
        try:
            user_id, nonce = parse_and_verify_state(state, self._encryption_key)
        except PinterestOAuthError as exc:
            raise VKOAuthError(str(exc)) from exc

        # H10: prevent replay attacks — state can only be used once
        lock_key = f"oauth_state_used:{nonce}"
        already_used = not await self._redis.set(lock_key, "1", ex=_OAUTH_STATE_LOCK_TTL, nx=True)
        if already_used:
            log.warning("vk_oauth_state_replay", user_id=user_id, nonce=nonce)
            raise VKOAuthError("OAuth state already used (replay)")

        # Retrieve code_verifier from Redis
        auth_raw = await self._redis.get(CacheKeys.vk_auth(nonce))
        if not auth_raw:
            raise VKOAuthError("VK auth session expired or not found")

        try:
            auth_data = json.loads(auth_raw)
            code_verifier = auth_data["code_verifier"]
        except (json.JSONDecodeError, KeyError) as exc:
            raise VKOAuthError("Invalid VK auth session data") from exc

        # Exchange code for tokens
        tokens = await self._exchange_code(code, code_verifier, device_id, state)

        # Fetch groups with new access_token
        groups = await self._fetch_groups(tokens["access_token"])

        # Store complete OAuth result in Redis
        await self._store_result(nonce, tokens, groups, device_id)

        # Clean up auth session
        await self._redis.delete(CacheKeys.vk_auth(nonce))

        log.info("vk_oauth_success", user_id=user_id, nonce=nonce, groups_count=len(groups))
        return user_id, nonce

    async def get_oauth_result(self, nonce: str) -> dict[str, object] | None:
        """Read and delete OAuth result from Redis (single-use)."""
        key = CacheKeys.vk_oauth(nonce)
        raw = await self._redis.get(key)
        if not raw:
            return None
        await self._redis.delete(key)
        try:
            result: dict[str, object] = json.loads(raw)
            return result
        except (json.JSONDecodeError, TypeError):
            return None

    async def _exchange_code(
        self,
        code: str,
        code_verifier: str,
        device_id: str,
        state: str,
    ) -> dict:
        """Exchange authorization code for tokens via VK ID API."""
        try:
            resp = await self._http.post(
                _VK_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                    "client_id": str(self._app_id),
                    "device_id": device_id,
                    "code_verifier": code_verifier,
                    "state": state,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            log.error("vk_token_exchange_http_error", error=str(exc))
            raise VKOAuthError(f"HTTP error during VK token exchange: {exc}") from exc

        if resp.status_code != 200:
            log.error("vk_token_exchange_failed", status=resp.status_code, body=resp.text[:500])
            raise VKOAuthError(f"VK token exchange failed: HTTP {resp.status_code}")

        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "unknown"))
            raise VKOAuthError(f"No access_token in VK response: {error_desc}")

        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", ""),
            "expires_in": data.get("expires_in", 3600),
            "user_id": data.get("user_id"),
        }

    async def _fetch_groups(self, access_token: str) -> list[dict]:
        """Fetch user's admin/editor groups via VK API."""
        try:
            resp = await self._http.post(
                f"{VK_API_URL}/groups.get",
                data={
                    "access_token": access_token,
                    "v": VK_API_VERSION,
                    "filter": "admin,editor",
                    "extended": "1",
                    "count": "50",
                },
                timeout=10,
            )
            data = resp.json()
            items: list[dict] = data.get("response", {}).get("items", [])
            return items
        except Exception:
            log.exception("vk_oauth_fetch_groups_failed")
            return []

    async def _store_result(
        self,
        nonce: str,
        tokens: dict,
        groups: list[dict],
        device_id: str,
    ) -> None:
        """Store OAuth result in Redis: vk_oauth:{nonce}, TTL=30min."""
        # Compact groups to minimize Redis storage
        compact_groups = [{"id": g["id"], "name": g.get("name", "")} for g in groups]
        result = {
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"],
            "expires_in": tokens["expires_in"],
            "device_id": device_id,
            "groups": compact_groups,
        }
        await self._redis.set(
            CacheKeys.vk_oauth(nonce),
            json.dumps(result),
            ex=VK_AUTH_TTL,
        )
