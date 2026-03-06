"""VK OAuth service — Authorization Code Flow via oauth.vk.com.

Uses the classic VK OAuth (oauth.vk.com) which provides full VK API access
(groups.get, wall.post, photos). VK ID (id.vk.ru) tokens do NOT support
VK API methods (error 1051).

Source of truth:
- docs/API_CONTRACTS.md section 3.5 (VK API)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)

Key facts:
- Authorize: https://oauth.vk.com/authorize
- Token exchange: https://oauth.vk.com/access_token (requires client_secret)
- No PKCE — uses client_secret instead
- access_token TTL: 86400s (24h) or 0 (infinite with offline scope)
"""

import contextlib
import json
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from bot.exceptions import AppError
from cache.client import RedisClient
from cache.keys import VK_AUTH_TTL, CacheKeys
from services.oauth.state import OAuthStateError, build_state, parse_and_verify_state

log = structlog.get_logger()

_VK_AUTHORIZE_URL = "https://oauth.vk.com/authorize"
_VK_TOKEN_URL = "https://oauth.vk.com/access_token"  # noqa: S105
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


@dataclass
class VKDeepLinkResult:
    """Result of processing a VK OAuth deep-link."""

    groups: list[dict[str, Any]] = field(default_factory=list)
    project_id: int | None = None
    access_token: str = ""
    refresh_token: str = ""
    expires_at: str = ""
    device_id: str = ""
    raw_result: dict[str, Any] = field(default_factory=dict)
    from_pipeline: bool = False


class VKOAuthService:
    """VK OAuth — exchange code for tokens, fetch groups."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        redis: RedisClient,
        encryption_key: str,
        vk_app_id: int,
        vk_app_secret: str,
        redirect_uri: str,
    ) -> None:
        self._http = http_client
        self._redis = redis
        self._encryption_key = encryption_key
        self._app_id = vk_app_id
        self._app_secret = vk_app_secret
        self._redirect_uri = redirect_uri

    def build_authorize_url(self, user_id: int, nonce: str) -> tuple[str, str]:
        """Build VK authorize URL with HMAC state.

        Returns (authorize_url, state).
        """
        state = build_state(user_id, nonce, self._encryption_key)

        params = (
            f"client_id={self._app_id}"
            f"&display=page"
            f"&redirect_uri={self._redirect_uri}"
            f"&scope=wall,groups,photos,offline"
            f"&response_type=code"
            f"&v={VK_API_VERSION}"
            f"&state={state}"
        )
        return f"{_VK_AUTHORIZE_URL}?{params}", state

    async def store_auth(self, nonce: str, user_id: int) -> None:
        """Store user_id in Redis for callback verification (TTL 30 min)."""
        data = json.dumps({"user_id": user_id})
        await self._redis.set(CacheKeys.vk_auth(nonce), data, ex=VK_AUTH_TTL)

    async def handle_callback(
        self,
        code: str,
        state: str,
    ) -> tuple[int, str]:
        """Full OAuth callback flow. Returns (user_id, nonce).

        1. Validate HMAC state (E30)
        2. Ensure single-use via Redis NX lock (H10)
        3. Exchange code for tokens via oauth.vk.com
        4. Fetch user's admin/editor groups
        5. Store tokens + groups in Redis
        """
        try:
            user_id, nonce = parse_and_verify_state(state, self._encryption_key)
        except OAuthStateError as exc:
            raise VKOAuthError(str(exc)) from exc

        # H10: prevent replay attacks — state can only be used once
        lock_key = f"oauth_state_used:{nonce}"
        already_used = not await self._redis.set(lock_key, "1", ex=_OAUTH_STATE_LOCK_TTL, nx=True)
        if already_used:
            log.warning("vk_oauth_state_replay", user_id=user_id, nonce=nonce)
            raise VKOAuthError("OAuth state already used (replay)")

        # Verify auth session exists in Redis
        auth_raw = await self._redis.get(CacheKeys.vk_auth(nonce))
        if not auth_raw:
            raise VKOAuthError("VK auth session expired or not found")

        # Exchange code for tokens
        tokens = await self._exchange_code(code)

        # Fetch groups with new access_token
        groups = await self._fetch_groups(tokens["access_token"])

        # Store complete OAuth result in Redis
        await self._store_result(nonce, tokens, groups)

        # Clean up auth session
        await self._redis.delete(CacheKeys.vk_auth(nonce))

        log.info("vk_oauth_success", user_id=user_id, nonce=nonce, groups_count=len(groups))
        return user_id, nonce

    async def get_oauth_result(self, nonce: str) -> dict[str, object] | None:
        """Atomically read and delete OAuth result from Redis (single-use)."""
        key = CacheKeys.vk_oauth(nonce)
        raw = await self._redis.getdel(key)
        if not raw:
            return None
        try:
            result: dict[str, object] = json.loads(raw)
            return result
        except (json.JSONDecodeError, TypeError):
            return None

    async def _exchange_code(self, code: str) -> dict:
        """Exchange authorization code for tokens via oauth.vk.com."""
        try:
            resp = await self._http.get(
                _VK_TOKEN_URL,
                params={
                    "client_id": str(self._app_id),
                    "client_secret": self._app_secret,
                    "redirect_uri": self._redirect_uri,
                    "code": code,
                },
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
            "expires_in": data.get("expires_in", 0),
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

            if "error" in data:
                err = data["error"]
                log.error(
                    "vk_groups_get_api_error",
                    error_code=err.get("error_code"),
                    error_msg=err.get("error_msg"),
                )
                return []

            items: list[dict] = data.get("response", {}).get("items", [])
            log.info("vk_groups_get_result", count=len(items))
            return items
        except Exception:
            log.exception("vk_oauth_fetch_groups_failed")
            return []

    async def _store_result(
        self,
        nonce: str,
        tokens: dict,
        groups: list[dict],
    ) -> None:
        """Store OAuth result in Redis: vk_oauth:{nonce}, TTL=30min."""
        compact_groups = [{"id": g["id"], "name": g.get("name", "")} for g in groups]
        result = {
            "access_token": tokens["access_token"],
            "expires_in": tokens["expires_in"],
            "groups": compact_groups,
        }
        await self._redis.set(
            CacheKeys.vk_oauth(nonce),
            json.dumps(result),
            ex=VK_AUTH_TTL,
        )

    # ------------------------------------------------------------------
    # Meta storage (nonce -> project_id, used by toolbox & pipeline)
    # ------------------------------------------------------------------

    async def store_meta(
        self,
        nonce: str,
        project_id: int,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Store nonce -> project_id mapping in Redis (30 min TTL)."""
        data: dict[str, Any] = {"project_id": project_id}
        if extra:
            data.update(extra)
        await self._redis.set(
            CacheKeys.vk_oauth_meta(nonce),
            json.dumps(data),
            ex=VK_AUTH_TTL,
        )

    async def get_meta(self, nonce: str) -> dict[str, Any] | None:
        """Read meta (project_id etc.) from Redis. Returns None if missing."""
        raw = await self._redis.get(CacheKeys.vk_oauth_meta(nonce))
        if not raw:
            return None
        try:
            meta: dict[str, Any] = json.loads(raw)
            return meta
        except (json.JSONDecodeError, TypeError):
            return None

    async def cleanup_meta(self, nonce: str) -> None:
        """Delete meta key from Redis."""
        await self._redis.delete(CacheKeys.vk_oauth_meta(nonce))

    # ------------------------------------------------------------------
    # Deep-link processing (replaces business logic from routers/start.py)
    # ------------------------------------------------------------------

    async def process_deep_link(self, nonce: str) -> VKDeepLinkResult | None:
        """Process VK OAuth deep-link — read result + meta, compute expires_at.

        Returns VKDeepLinkResult with all data needed by the router to show UI,
        or None if the OAuth result is missing/expired.
        """
        result: dict[str, Any] | None = await self.get_oauth_result(nonce)  # type: ignore[assignment]
        if not result:
            return None

        groups: list[dict[str, Any]] = result.get("groups") or []

        # Read project_id and pipeline context from meta
        meta = await self.get_meta(nonce)
        project_id: int | None = None
        from_pipeline = False
        if meta:
            with contextlib.suppress(ValueError, TypeError, KeyError):
                project_id = int(meta["project_id"])
            from_pipeline = meta.get("from_pipeline") is True

        expires_in = int(result.get("expires_in") or 0)
        expires_at = (
            (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
            if expires_in > 0
            else ""
        )

        return VKDeepLinkResult(
            groups=groups,
            project_id=project_id,
            access_token=str(result.get("access_token", "")),
            refresh_token="",
            expires_at=expires_at,
            device_id="",
            raw_result=result,
            from_pipeline=from_pipeline,
        )

    async def restore_result_for_group_select(
        self,
        nonce: str,
        result: dict[str, Any],
    ) -> None:
        """Re-store OAuth result in Redis for multi-group selection flow (10 min TTL)."""
        await self._redis.set(CacheKeys.vk_oauth(nonce), json.dumps(result), ex=600)

    async def get_stored_result(self, nonce: str) -> dict[str, Any] | None:
        """Read stored OAuth result (for group selection callback)."""
        raw = await self._redis.get(CacheKeys.vk_oauth(nonce))
        if not raw:
            return None
        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except (json.JSONDecodeError, TypeError):
            return None

    async def cleanup(self, nonce: str) -> None:
        """Clean up all Redis keys for a completed OAuth flow."""
        await self._redis.delete(CacheKeys.vk_oauth(nonce))
        await self.cleanup_meta(nonce)

    def generate_nonce(self) -> str:
        """Generate a cryptographic nonce for OAuth flow."""
        return secrets.token_urlsafe(16)

    def build_oauth_url(self, user_id: int, nonce: str) -> str:
        """Build the redirect URL: /api/auth/vk?user_id=...&nonce=...

        Requires self._redirect_uri to be set (includes base_url).
        """
        base_url = self._redirect_uri.rsplit("/api/auth/vk/callback", 1)[0]
        return f"{base_url}/api/auth/vk?user_id={user_id}&nonce={nonce}"
