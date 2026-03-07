"""VK OAuth service — two-step Authorization Code Flow via oauth.vk.ru.

Two-step flow to obtain a **community token** (not a user token):
1. Step 1: scope=groups → user token → groups.get(filter=admin) → show picker
2. Step 2: scope=wall,photos + group_ids=ID → community token → save

Source of truth:
- https://dev.vk.com/ru/api/access-token/authcode-flow-community
- docs/API_CONTRACTS.md section 3.5 (VK API)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)

Key facts:
- Authorize: https://oauth.vk.ru/authorize
- Token exchange: https://oauth.vk.ru/access_token (requires client_secret)
- No PKCE — uses client_secret instead
- Community token with offline scope: permanent (expires_in=0)
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

_VK_AUTHORIZE_URL = "https://oauth.vk.ru/authorize"
_VK_TOKEN_URL = "https://oauth.vk.ru/access_token"  # noqa: S105
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

    step: str = "groups"  # "groups" (step 1) or "community" (step 2)
    groups: list[dict[str, Any]] = field(default_factory=list)
    group_id: int | None = None
    group_name: str = ""
    project_id: int | None = None
    access_token: str = ""
    expires_at: str = ""
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

    def build_authorize_url(
        self,
        user_id: int,
        nonce: str,
        *,
        group_ids: int | None = None,
    ) -> tuple[str, str]:
        """Build VK authorize URL with HMAC state.

        Two-step flow (authcode-flow-community):
        - Step 1 (group_ids=None): scope=groups → user token for groups.get
        - Step 2 (group_ids=ID): scope=wall,photos,offline + group_ids → community token

        Returns (authorize_url, state).
        """
        state = build_state(user_id, nonce, self._encryption_key)

        if group_ids is not None:
            # Step 2: community token for specific group
            scope = "wall,photos,offline"
            params = (
                f"client_id={self._app_id}"
                f"&display=page"
                f"&redirect_uri={self._redirect_uri}"
                f"&scope={scope}"
                f"&response_type=code"
                f"&v={VK_API_VERSION}"
                f"&state={state}"
                f"&group_ids={group_ids}"
            )
        else:
            # Step 1: user token to fetch admin groups
            scope = "groups"
            params = (
                f"client_id={self._app_id}"
                f"&display=page"
                f"&redirect_uri={self._redirect_uri}"
                f"&scope={scope}"
                f"&response_type=code"
                f"&v={VK_API_VERSION}"
                f"&state={state}"
            )
        return f"{_VK_AUTHORIZE_URL}?{params}", state

    async def store_auth(
        self,
        nonce: str,
        user_id: int,
        *,
        step: str = "groups",
        group_id: int | None = None,
        group_name: str = "",
    ) -> None:
        """Store auth session in Redis for callback verification (TTL 30 min).

        Args:
            step: "groups" (step 1: fetch groups) or "community" (step 2: get token)
            group_id: VK group ID (required for step 2)
            group_name: VK group name (for step 2 metadata)
        """
        data: dict[str, Any] = {"user_id": user_id, "step": step}
        if group_id is not None:
            data["group_id"] = group_id
            data["group_name"] = group_name
        await self._redis.set(CacheKeys.vk_auth(nonce), json.dumps(data), ex=VK_AUTH_TTL)

    async def handle_callback(
        self,
        code: str,
        state: str,
    ) -> tuple[int, str]:
        """Full OAuth callback flow. Returns (user_id, nonce).

        Two-step community token flow:
        - Step 1: exchange code → user token → groups.get → store groups in Redis
        - Step 2: exchange code → community token (access_token_GROUP_ID) → store

        The step is determined by auth session data in Redis (has "step" field).

        1. Validate HMAC state (E30)
        2. Ensure single-use via Redis NX lock (H10)
        3. Exchange code for tokens
        4. Step 1: fetch groups + store | Step 2: store community token
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

        auth_data: dict[str, Any] = {}
        with contextlib.suppress(json.JSONDecodeError, TypeError):
            auth_data = json.loads(auth_raw)

        step = auth_data.get("step", "groups")

        # Exchange code for tokens
        tokens = await self._exchange_code(code)

        if step == "community":
            # Step 2: we got a community token — extract it
            group_id = auth_data.get("group_id")
            community_token = self._extract_community_token(tokens, group_id)
            await self._store_community_result(nonce, community_token, group_id, auth_data)
        else:
            # Step 1: user token → fetch admin groups
            groups = await self._fetch_groups(tokens["access_token"])
            await self._store_result(nonce, tokens, groups)

        # Clean up auth session
        await self._redis.delete(CacheKeys.vk_auth(nonce))

        log.info("vk_oauth_success", user_id=user_id, nonce=nonce, step=step)
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

    async def _exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for tokens via oauth.vk.ru."""
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
        # Step 1 returns "access_token", step 2 returns "access_token_GROUP_ID"
        has_token = "access_token" in data or any(
            k.startswith("access_token_") for k in data
        )
        if not has_token:
            error_desc = data.get("error_description", data.get("error", "unknown"))
            raise VKOAuthError(f"No access_token in VK response: {error_desc}")

        result: dict[str, Any] = data
        return result

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

    @staticmethod
    def _extract_community_token(
        data: dict[str, Any],
        group_id: int | None,
    ) -> str:
        """Extract community access token from VK response.

        VK returns community token as `access_token_GROUP_ID` key.
        """
        if group_id:
            key = f"access_token_{group_id}"
            if key in data:
                return str(data[key])
        # Fallback: search for any access_token_* key
        for k, v in data.items():
            if k.startswith("access_token_") and v:
                return str(v)
        # Last resort: plain access_token
        return str(data.get("access_token", ""))

    async def _store_result(
        self,
        nonce: str,
        tokens: dict,
        groups: list[dict],
    ) -> None:
        """Store step-1 result (groups list) in Redis: vk_oauth:{nonce}, TTL=30min."""
        compact_groups = [{"id": g["id"], "name": g.get("name", "")} for g in groups]
        result: dict[str, Any] = {
            "step": "groups",
            "groups": compact_groups,
        }
        await self._redis.set(
            CacheKeys.vk_oauth(nonce),
            json.dumps(result),
            ex=VK_AUTH_TTL,
        )

    async def _store_community_result(
        self,
        nonce: str,
        community_token: str,
        group_id: int | None,
        auth_data: dict[str, Any],
    ) -> None:
        """Store step-2 result (community token) in Redis: vk_oauth:{nonce}, TTL=30min."""
        result: dict[str, Any] = {
            "step": "community",
            "access_token": community_token,
            "group_id": group_id,
            "group_name": auth_data.get("group_name", ""),
            "expires_in": 0,  # community token with offline scope is permanent
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
        """Process VK OAuth deep-link — read result + meta.

        Returns VKDeepLinkResult with step info:
        - step="groups": groups list available, user must pick one
        - step="community": community token ready, create connection

        Returns None if the OAuth result is missing/expired.
        """
        result: dict[str, Any] | None = await self.get_oauth_result(nonce)  # type: ignore[assignment]
        if not result:
            return None

        # Read project_id and pipeline context from meta
        meta = await self.get_meta(nonce)
        project_id: int | None = None
        from_pipeline = False
        if meta:
            with contextlib.suppress(ValueError, TypeError, KeyError):
                project_id = int(meta["project_id"])
            from_pipeline = meta.get("from_pipeline") is True

        step = result.get("step", "groups")

        if step == "community":
            # Step 2 result: community token ready
            expires_in = int(result.get("expires_in") or 0)
            expires_at = (
                (datetime.now(UTC) + timedelta(seconds=expires_in)).isoformat()
                if expires_in > 0
                else ""
            )
            group_id_val = result.get("group_id")
            return VKDeepLinkResult(
                step="community",
                group_id=int(group_id_val) if group_id_val else None,
                group_name=str(result.get("group_name", "")),
                project_id=project_id,
                access_token=str(result.get("access_token", "")),
                expires_at=expires_at,
                raw_result=result,
                from_pipeline=from_pipeline,
            )

        # Step 1 result: groups list
        groups: list[dict[str, Any]] = result.get("groups") or []
        return VKDeepLinkResult(
            step="groups",
            groups=groups,
            project_id=project_id,
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

    def build_oauth_url(
        self, user_id: int, nonce: str, *, group_ids: int | None = None,
    ) -> str:
        """Build the redirect URL: /api/auth/vk?user_id=...&nonce=...[&group_ids=...]

        Requires self._redirect_uri to be set (includes base_url).
        """
        base_url = self._redirect_uri.rsplit("/api/auth/vk/callback", 1)[0]
        url = f"{base_url}/api/auth/vk?user_id={user_id}&nonce={nonce}"
        if group_ids is not None:
            url += f"&group_ids={group_ids}"
        return url
