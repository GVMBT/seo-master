"""VK OAuth service — two-step community token flow.

Two DIFFERENT OAuth systems to obtain a **community token**:
1. Step 1: VK ID OAuth 2.1 (id.vk.ru) + PKCE → user token → groups.get(filter=admin)
2. Step 2: Classic VK OAuth (oauth.vk.com) + client_secret + group_ids → community token

Source of truth:
- https://id.vk.com/about/business/go/docs/ru/vkid/latest/oauth/oauth-vkontakte/authcode-flow-community
- https://id.vk.com/about/business/go/docs/ru/vkid/latest/vk-id/connection/api-description
- docs/API_CONTRACTS.md section 3.5 (VK API)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)

Key facts:
- Step 1 authorize: https://id.vk.ru/authorize (PKCE, code_challenge S256)
- Step 1 exchange: POST https://id.vk.ru/oauth2/auth (code_verifier, device_id)
- Step 2 authorize: https://oauth.vk.com/authorize (group_ids required)
- Step 2 exchange: POST https://oauth.vk.com/access_token (client_secret)
- Community token with offline scope: permanent (expires_in=0)
"""

import base64
import contextlib
import hashlib
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

# Step 1: VK ID OAuth 2.1 (user token for groups.get)
_VKID_AUTHORIZE_URL = "https://id.vk.ru/authorize"
_VKID_TOKEN_URL = "https://id.vk.ru/oauth2/auth"  # noqa: S105

# Step 2: Classic VK OAuth (community token)
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

    step: str = "groups"  # "groups" (step 1) or "community" (step 2)
    groups: list[dict[str, Any]] = field(default_factory=list)
    group_id: int | None = None
    group_name: str = ""
    project_id: int | None = None
    access_token: str = ""
    expires_at: str = ""
    raw_result: dict[str, Any] = field(default_factory=dict)
    from_pipeline: bool = False


# ---------------------------------------------------------------------------
# PKCE helpers (for VK ID OAuth 2.1, step 1)
# ---------------------------------------------------------------------------


def _generate_code_verifier() -> str:
    """Generate PKCE code_verifier (43-128 chars, URL-safe)."""
    return secrets.token_urlsafe(64)


def _generate_code_challenge(code_verifier: str) -> str:
    """Generate PKCE code_challenge from code_verifier (S256)."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class VKOAuthService:
    """VK OAuth — two-step community token flow with two OAuth systems."""

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

        Two-step flow uses TWO DIFFERENT OAuth systems:
        - Step 1 (group_ids=None): VK ID OAuth 2.1 (id.vk.ru) + PKCE
        - Step 2 (group_ids=ID): Classic VK OAuth (oauth.vk.com) + group_ids

        Returns (authorize_url, state).
        For step 1, also generates code_verifier (retrieve via get_last_code_verifier).
        """
        state = build_state(user_id, nonce, self._encryption_key)

        if group_ids is not None:
            # Step 2: Classic VK OAuth → community token
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
            return f"{_VK_AUTHORIZE_URL}?{params}", state

        # Step 1: VK ID OAuth 2.1 → user token for groups.get
        code_verifier = _generate_code_verifier()
        code_challenge = _generate_code_challenge(code_verifier)
        self._last_code_verifier = code_verifier
        params = (
            f"response_type=code"
            f"&client_id={self._app_id}"
            f"&redirect_uri={self._redirect_uri}"
            f"&code_challenge={code_challenge}"
            f"&code_challenge_method=S256"
            f"&state={state}"
            f"&scope=groups"
        )
        return f"{_VKID_AUTHORIZE_URL}?{params}", state

    def get_last_code_verifier(self) -> str:
        """Get the code_verifier generated by the last build_authorize_url() call.

        Must be called IMMEDIATELY after build_authorize_url() for step 1.
        """
        return getattr(self, "_last_code_verifier", "")

    async def store_auth(
        self,
        nonce: str,
        user_id: int,
        *,
        step: str = "groups",
        group_id: int | None = None,
        group_name: str = "",
        code_verifier: str = "",
    ) -> None:
        """Store auth session in Redis for callback verification (TTL 30 min).

        Args:
            step: "groups" (step 1: fetch groups) or "community" (step 2: get token)
            group_id: VK group ID (required for step 2)
            group_name: VK group name (for step 2 metadata)
            code_verifier: PKCE code_verifier (required for step 1)
        """
        data: dict[str, Any] = {"user_id": user_id, "step": step}
        if group_id is not None:
            data["group_id"] = group_id
            data["group_name"] = group_name
        if code_verifier:
            data["code_verifier"] = code_verifier
        await self._redis.set(CacheKeys.vk_auth(nonce), json.dumps(data), ex=VK_AUTH_TTL)

    async def handle_callback(
        self,
        code: str,
        state: str,
        *,
        device_id: str = "",
    ) -> tuple[int, str]:
        """Full OAuth callback flow. Returns (user_id, nonce).

        Two-step community token flow using two OAuth systems:
        - Step 1: VK ID OAuth 2.1 exchange (code_verifier + device_id) → groups.get
        - Step 2: Classic VK OAuth exchange (client_secret) → community token

        Args:
            device_id: Device ID from VK ID callback (required for step 1).
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

        try:
            auth_data: dict[str, Any] = json.loads(auth_raw)
        except (json.JSONDecodeError, TypeError) as exc:
            raise VKOAuthError("Corrupted VK auth session") from exc

        step = auth_data.get("step")
        if step not in {"groups", "community"}:
            raise VKOAuthError("Invalid VK auth session step")

        if step == "community":
            group_id = auth_data.get("group_id")
            if group_id is None:
                raise VKOAuthError("Missing group_id in VK auth session")
            # Step 2: Classic VK OAuth → community token
            tokens = await self._exchange_code_classic(code)
            community_token = self._extract_community_token(tokens, group_id)
            await self._store_community_result(nonce, community_token, group_id, auth_data)
        else:
            # Step 1: VK ID OAuth 2.1 → user token → groups.get
            code_verifier = str(auth_data.get("code_verifier", ""))
            if not code_verifier or not device_id:
                raise VKOAuthError("Missing PKCE session data")
            tokens = await self._exchange_code_vkid(code, code_verifier, device_id)
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

    # ------------------------------------------------------------------
    # Token exchange — two different systems
    # ------------------------------------------------------------------

    async def _exchange_code_vkid(
        self,
        code: str,
        code_verifier: str,
        device_id: str,
    ) -> dict[str, Any]:
        """Exchange code via VK ID OAuth 2.1 (step 1).

        POST https://id.vk.ru/oauth2/auth with PKCE code_verifier + device_id.
        """
        try:
            resp = await self._http.post(
                _VKID_TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code_verifier": code_verifier,
                    "redirect_uri": self._redirect_uri,
                    "code": code,
                    "client_id": str(self._app_id),
                    "device_id": device_id,
                },
                timeout=15,
            )
        except httpx.HTTPError as exc:
            log.error("vk_token_exchange_http_error", error=str(exc), system="vkid")
            raise VKOAuthError(f"HTTP error during VK ID token exchange: {exc}") from exc

        if resp.status_code != 200:
            log.error(
                "vk_token_exchange_failed",
                status=resp.status_code,
                body=resp.text[:500],
                system="vkid",
            )
            raise VKOAuthError(f"VK ID token exchange failed: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            log.error("vk_token_exchange_invalid_json", body=resp.text[:200], system="vkid")
            raise VKOAuthError("VK ID returned invalid JSON") from exc

        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "unknown"))
            raise VKOAuthError(f"No access_token in VK ID response: {error_desc}")

        result: dict[str, Any] = data
        return result

    async def _exchange_code_classic(self, code: str) -> dict[str, Any]:
        """Exchange code via classic VK OAuth (step 2).

        GET https://oauth.vk.com/access_token with client_secret.
        """
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
            log.error("vk_token_exchange_http_error", error=str(exc), system="classic")
            raise VKOAuthError(f"HTTP error during VK token exchange: {exc}") from exc

        if resp.status_code != 200:
            log.error(
                "vk_token_exchange_failed",
                status=resp.status_code,
                body=resp.text[:500],
                system="classic",
            )
            raise VKOAuthError(f"VK token exchange failed: HTTP {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as exc:
            log.error("vk_token_exchange_invalid_json", body=resp.text[:200], system="classic")
            raise VKOAuthError("VK returned invalid JSON") from exc

        # Step 2 returns "access_token_GROUP_ID"
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
