"""VK OAuth service — community token flow via classic VK OAuth.

Obtains a **community token** for wall.post on behalf of a VK group.

Flow:
1. User provides group URL/ID → resolve to numeric group_id
2. Classic VK OAuth (oauth.vk.ru) with group_ids → community token

Source of truth:
- https://dev.vk.com/ru/api/access-token/authcode-flow-community
- docs/API_CONTRACTS.md section 3.5 (VK API)
- docs/EDGE_CASES.md E20 (30min TTL), E30 (HMAC state)

Key facts:
- Authorize: https://oauth.vk.ru/authorize (group_ids required)
- Exchange: GET https://oauth.vk.ru/access_token (client_secret)
- Community token scope: manage,photos (NOT wall/offline — those are user scopes)
- Community token is permanent (expires_in=0) by default
- Group resolution: scrape vk.com page (no auth), fallback to API + service key
"""

import base64
import contextlib
import hashlib
import json
import re
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

# Classic VK OAuth (community token) — per dev.vk.com docs
_VK_AUTHORIZE_URL = "https://oauth.vk.ru/authorize"
_VK_TOKEN_URL = "https://oauth.vk.ru/access_token"  # noqa: S105

# VK ID OAuth 2.1 (kept for potential future use)
_VKID_AUTHORIZE_URL = "https://id.vk.ru/authorize"
_VKID_TOKEN_URL = "https://id.vk.ru/oauth2/auth"  # noqa: S105

_OAUTH_STATE_LOCK_TTL = 600  # 10 min — single-use state lock (H10)

VK_API_VERSION = "5.199"
VK_API_URL = "https://api.vk.ru/method"

# Regex for parsing VK group URLs
_VK_CLUB_RE = re.compile(
    r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/(?:club|public)(\d+)",
    re.IGNORECASE,
)
_VK_SCREEN_NAME_RE = re.compile(
    r"(?:https?://)?(?:m\.)?vk\.(?:com|ru)/([a-zA-Z][a-zA-Z0-9_.]{1,31})",
    re.IGNORECASE,
)
# Extracts group pid from VK SPA page: "loc":"?act=s&pid=GROUP_ID&subdir=..."
_VK_LOC_PID_RE = re.compile(r'"loc"\s*:\s*"\?act=s&pid=(\d+)&subdir=')


def parse_vk_group_input(text: str) -> tuple[int | None, str | None]:
    """Parse VK group URL or ID into (numeric_id, screen_name).

    Returns exactly one non-None value:
    - ``123456``, ``club123456``, ``vk.com/club123456`` → (123456, None)
    - ``vk.com/mygroup`` → (None, "mygroup")
    - Invalid input → (None, None)
    """
    text = text.strip().rstrip("/")

    # Plain numeric ID
    if text.isdigit():
        return int(text), None

    # vk.com/club123456 or vk.com/public123456
    m = _VK_CLUB_RE.match(text)
    if m:
        return int(m.group(1)), None

    # vk.com/screen_name (must start with letter)
    m = _VK_SCREEN_NAME_RE.match(text)
    if m:
        return None, m.group(1)

    return None, None


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
        *,
        vk_service_key: str = "",
    ) -> None:
        self._http = http_client
        self._redis = redis
        self._encryption_key = encryption_key
        self._app_id = vk_app_id
        self._app_secret = vk_app_secret
        self._redirect_uri = redirect_uri
        self._service_key = vk_service_key

    async def resolve_group(self, group_id_or_name: str) -> tuple[int, str]:
        """Resolve VK group by numeric ID or screen_name.

        Strategy:
        1. Scrape vk.com/{screen_name} page → extract pid from "loc" field (no auth)
        2. Fallback: VK API groups.getById with service token (if available)

        Returns (group_id, group_name).  group_name may be screen_name if
        the actual name is unavailable (will be fetched later with user token).
        """
        # For numeric IDs, try scraping first to verify it's a real group
        is_numeric = group_id_or_name.isdigit()

        # --- Strategy 1: scrape vk.com page (no auth needed) ---
        scraped_id = await self._resolve_by_scraping(group_id_or_name)
        if scraped_id is not None:
            if is_numeric and scraped_id != int(group_id_or_name):
                # Mismatch: user typed one ID but page has a different pid.
                # Don't silently swap — fall through to API or fail.
                log.warning(
                    "vk_resolve_id_mismatch",
                    input=group_id_or_name,
                    scraped=scraped_id,
                )
            else:
                display_name = group_id_or_name if not is_numeric else f"club{scraped_id}"
                return scraped_id, display_name

        # --- Strategy 2: VK API with service token ---
        if self._service_key:
            return await self._resolve_by_api(group_id_or_name)

        # Both strategies failed
        raise VKOAuthError(
            f"Cannot resolve VK group: {group_id_or_name}",
            user_message="Группа VK не найдена или недоступна. Проверьте ссылку.",
        )

    async def _resolve_by_scraping(self, screen_name: str) -> int | None:
        """Scrape vk.com/{screen_name} and extract group ID from "loc" field.

        VK SPA pages contain a JSON snippet with "loc":"?act=s&pid=GROUP_ID&subdir=NAME"
        for group pages.  User pages have "loc":"?subdir=NAME" (no pid).

        Returns numeric group_id or None if not found / not a group.
        """
        url = f"https://vk.com/{screen_name}"
        try:
            resp = await self._http.get(
                url,
                headers={"User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )},
                timeout=10,
                follow_redirects=True,
            )
        except httpx.HTTPError as exc:
            log.warning("vk_scrape_http_error", screen_name=screen_name, error=str(exc))
            return None

        if resp.status_code != 200:
            log.warning("vk_scrape_bad_status", screen_name=screen_name, status=resp.status_code)
            return None

        # Extract pid from "loc":"?act=s&pid=GROUP_ID&subdir=..."
        m = _VK_LOC_PID_RE.search(resp.text)
        if not m:
            log.info("vk_scrape_no_pid", screen_name=screen_name)
            return None

        group_id = int(m.group(1))
        log.info("vk_scrape_resolved", screen_name=screen_name, group_id=group_id)
        return group_id

    async def _resolve_by_api(self, group_id_or_name: str) -> tuple[int, str]:
        """Resolve group via VK API groups.getById with service token."""
        service_token = await self._get_service_token()
        try:
            resp = await self._http.post(
                f"{VK_API_URL}/groups.getById",
                data={
                    "access_token": service_token,
                    "v": VK_API_VERSION,
                    "group_id": group_id_or_name,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPError as exc:
            log.error("vk_resolve_group_http_error", input=group_id_or_name, error=str(exc))
            raise VKOAuthError(
                "Ошибка соединения с VK API",
                user_message="Не удалось связаться с VK. Попробуйте позже.",
            ) from exc
        except ValueError as exc:
            log.error("vk_resolve_group_json_error", input=group_id_or_name, error=str(exc))
            raise VKOAuthError(
                "VK вернул некорректный ответ",
                user_message="VK вернул некорректный ответ. Попробуйте позже.",
            ) from exc

        if "error" in data:
            err = data["error"]
            error_code = err.get("error_code")
            log.warning(
                "vk_resolve_group_api_error",
                error_code=error_code,
                error_msg=err.get("error_msg"),
                input=group_id_or_name,
            )
            raise VKOAuthError(
                f"VK API error {error_code}",
                user_message="Группа VK не найдена или недоступна",
            )

        # API v5.199: response.groups[] or response[] (depends on version)
        response = data.get("response", {})
        groups: list[dict[str, Any]] = (
            response.get("groups", []) if isinstance(response, dict) else response
        )
        if not groups:
            raise VKOAuthError(
                "Группа VK не найдена",
                user_message="Группа VK не найдена или недоступна",
            )

        group = groups[0]
        return int(group["id"]), str(group.get("name", ""))

    async def _get_service_token(self) -> str:
        """Get VK service token.

        Uses pre-configured service key if available (from VK app settings).
        Falls back to client_credentials grant.
        """
        # Static service key from VK app settings — no HTTP call needed
        if self._service_key:
            return self._service_key

        try:
            resp = await self._http.get(
                _VK_TOKEN_URL,
                params={
                    "client_id": str(self._app_id),
                    "client_secret": self._app_secret,
                    "v": VK_API_VERSION,
                    "grant_type": "client_credentials",
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.error("vk_service_token_failed", error=str(exc))
            raise VKOAuthError("Не удалось получить сервисный токен VK") from exc

        token = data.get("access_token", "")
        if not token:
            error_desc = data.get("error_description", data.get("error", "unknown"))
            raise VKOAuthError(f"VK service token error: {error_desc}")
        return str(token)

    def build_authorize_url(
        self,
        user_id: int,
        nonce: str,
        *,
        group_ids: int | None = None,
    ) -> tuple[str, str]:
        """Build VK authorize URL with HMAC state.

        group_ids is REQUIRED for community token flow (classic VK OAuth).
        Without group_ids, falls back to VK ID OAuth 2.1 (step 1, rarely used).

        Returns (authorize_url, state).
        """
        state = build_state(user_id, nonce, self._encryption_key)

        if group_ids is not None:
            # Classic VK OAuth → community token
            scope = "manage,photos"
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

        # VK ID OAuth 2.1 (fallback — user token for groups.get)
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
            token_key = f"access_token_{group_id}"
            community_token = str(tokens.get(token_key, ""))
            if not community_token:
                log.error("vk_community_token_missing", group_id=group_id, keys=list(tokens.keys()))
                raise VKOAuthError(f"No community token for group {group_id}")
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

        GET https://oauth.vk.ru/access_token with client_secret.
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
