"""Tests for services/oauth/vk.py — VK OAuth service (two-step community token flow).

Covers: step 1 (VK ID OAuth 2.1 + PKCE), step 2 (classic OAuth + group_ids),
code exchange, groups fetch, community token extraction, Redis storage,
single-use nonce, error handling.
"""

from __future__ import annotations

import json
import secrets
from unittest.mock import AsyncMock

import httpx
import pytest

from cache.keys import CacheKeys
from services.oauth.vk import VKOAuthError, VKOAuthService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENCRYPTION_KEY = "test-encryption-key-32chars-long!"
_APP_SECRET = "test_app_secret_value"


def _nonce() -> str:
    """Generate a valid 22-char nonce (same as production)."""
    return secrets.token_urlsafe(16)


def _make_service(
    handler: object = None,
    redis: AsyncMock | None = None,
) -> tuple[VKOAuthService, AsyncMock]:
    """Create VKOAuthService with mock transport and Redis."""
    if handler is None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    client = httpx.AsyncClient(transport=transport)

    if redis is None:
        redis = AsyncMock()
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)
        redis.delete = AsyncMock()

    service = VKOAuthService(
        http_client=client,
        redis=redis,
        encryption_key=_ENCRYPTION_KEY,
        vk_app_id=123456,
        vk_app_secret=_APP_SECRET,
        redirect_uri="https://example.com/api/auth/vk/callback",
    )
    return service, redis


# ---------------------------------------------------------------------------
# build_authorize_url — two different OAuth systems
# ---------------------------------------------------------------------------


class TestBuildAuthorizeUrl:
    def test_step1_uses_vkid_oauth(self) -> None:
        """Step 1 (no group_ids): VK ID OAuth 2.1 at id.vk.ru with PKCE."""
        service, _ = _make_service()
        nonce = _nonce()
        url, state = service.build_authorize_url(user_id=42, nonce=nonce)
        assert "id.vk.ru/authorize" in url
        assert "response_type=code" in url
        assert "client_id=123456" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "scope=groups" in url
        assert "group_ids" not in url
        assert nonce in state

    def test_step1_generates_code_verifier(self) -> None:
        """Step 1 generates PKCE code_verifier accessible via get_last_code_verifier."""
        service, _ = _make_service()
        nonce = _nonce()
        service.build_authorize_url(user_id=42, nonce=nonce)
        cv = service.get_last_code_verifier()
        assert len(cv) >= 43  # PKCE minimum

    def test_step2_uses_classic_vk_oauth(self) -> None:
        """Step 2 (with group_ids): classic OAuth at oauth.vk.com."""
        service, _ = _make_service()
        nonce = _nonce()
        url, state = service.build_authorize_url(user_id=42, nonce=nonce, group_ids=12345)
        assert "oauth.vk.com/authorize" in url
        assert "scope=wall,photos,offline" in url
        assert "group_ids=12345" in url
        assert "code_challenge" not in url  # No PKCE for step 2
        assert nonce in state

    def test_state_contains_user_id_and_nonce(self) -> None:
        service, _ = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        assert state.startswith("42")
        assert nonce in state
        # user_id(2) + nonce(22) + hmac(64) = 88
        assert len(state) == 2 + 22 + 64


# ---------------------------------------------------------------------------
# store_auth
# ---------------------------------------------------------------------------


class TestStoreAuth:
    async def test_stores_step1_auth_with_code_verifier(self) -> None:
        service, redis = _make_service()
        await service.store_auth("nonce123", 42, code_verifier="test_verifier")
        redis.set.assert_called_once()
        key = redis.set.call_args[0][0]
        data = json.loads(redis.set.call_args[0][1])
        assert key == CacheKeys.vk_auth("nonce123")
        assert data["user_id"] == 42
        assert data["step"] == "groups"
        assert data["code_verifier"] == "test_verifier"

    async def test_stores_step2_auth_with_group(self) -> None:
        service, redis = _make_service()
        await service.store_auth("nonce456", 42, step="community", group_id=999, group_name="My Group")
        data = json.loads(redis.set.call_args[0][1])
        assert data["step"] == "community"
        assert data["group_id"] == 999
        assert data["group_name"] == "My Group"
        assert "code_verifier" not in data  # No PKCE for step 2


# ---------------------------------------------------------------------------
# handle_callback — step 1 (VK ID OAuth 2.1 + PKCE)
# ---------------------------------------------------------------------------


class TestHandleCallbackStep1:
    async def test_step1_fetches_groups(self) -> None:
        """Step 1: VK ID exchange (PKCE) → user token → groups.get → store groups."""
        service, redis = _make_service(handler=self._mock_step1_api)

        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({
            "user_id": 42,
            "step": "groups",
            "code_verifier": "test_verifier_123",
        })

        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)
        redis.delete = AsyncMock()

        user_id, parsed_nonce = await service.handle_callback(
            code="auth_code", state=state, device_id="test_device",
        )
        assert user_id == 42
        assert parsed_nonce == nonce

        # Verify groups were stored
        set_calls = [c for c in redis.set.call_args_list if "vk_oauth:" in str(c)]
        assert len(set_calls) >= 1
        stored = json.loads(set_calls[0][0][1])
        assert stored["step"] == "groups"
        assert len(stored["groups"]) == 2

    async def test_invalid_state_raises(self) -> None:
        service, redis = _make_service()
        redis.set = AsyncMock(return_value=True)

        with pytest.raises(VKOAuthError):
            await service.handle_callback(code="code", state="invalid_state_too_short")

    async def test_replay_attack_blocked(self) -> None:
        """Second use of same state should fail (H10)."""
        service, redis = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        redis.get = AsyncMock(return_value=json.dumps({"user_id": 42}))
        redis.set = AsyncMock(return_value=False)

        with pytest.raises(VKOAuthError, match="replay"):
            await service.handle_callback(code="code", state=state)

    async def test_expired_session_raises(self) -> None:
        """Missing vk_auth:{nonce} in Redis -> expired."""
        service, redis = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)

        with pytest.raises(VKOAuthError, match="expired"):
            await service.handle_callback(code="code", state=state)

    async def test_corrupted_session_raises(self) -> None:
        """Corrupted JSON in Redis → error before any I/O."""
        service, redis = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: "not-json{" if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="Corrupted"):
            await service.handle_callback(code="code", state=state)

    async def test_invalid_step_raises(self) -> None:
        """Unknown step value in session → error before I/O."""
        service, redis = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({"user_id": 42, "step": "unknown"})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="Invalid.*step"):
            await service.handle_callback(code="code", state=state)

    async def test_missing_pkce_data_raises(self) -> None:
        """Step 1 without code_verifier or device_id → error before exchange."""
        service, redis = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({"user_id": 42, "step": "groups"})  # no code_verifier
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="PKCE"):
            await service.handle_callback(code="code", state=state, device_id="dev")

    async def test_missing_group_id_in_community_step_raises(self) -> None:
        """Step 2 without group_id → error before exchange."""
        service, redis = _make_service()
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce, group_ids=100)
        auth_data = json.dumps({"user_id": 42, "step": "community"})  # no group_id
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="group_id"):
            await service.handle_callback(code="code", state=state)

    @staticmethod
    async def _mock_step1_api(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        # Step 1: VK ID OAuth 2.1 token exchange
        if "id.vk.ru/oauth2/auth" in url:
            return httpx.Response(200, json={
                "access_token": "user_token_123",
                "refresh_token": "refresh_123",
                "expires_in": 3600,
                "user_id": "42",
            })
        if "groups.get" in url:
            return httpx.Response(200, json={
                "response": {
                    "count": 2,
                    "items": [
                        {"id": 100, "name": "Group A"},
                        {"id": 200, "name": "Group B"},
                    ],
                },
            })
        return httpx.Response(404)


# ---------------------------------------------------------------------------
# handle_callback — step 2 (classic VK OAuth + community token)
# ---------------------------------------------------------------------------


class TestHandleCallbackStep2:
    async def test_step2_stores_community_token(self) -> None:
        """Step 2: classic exchange (client_secret) → community token → store."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth.vk.com/access_token" in str(request.url):
                return httpx.Response(200, json={
                    "access_token_100": "community_token_for_100",
                    "expires_in": 0,
                })
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce, group_ids=100)

        auth_data = json.dumps({
            "user_id": 42, "step": "community", "group_id": 100, "group_name": "Group A",
        })
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)
        redis.delete = AsyncMock()

        user_id, parsed_nonce = await service.handle_callback(code="code", state=state)
        assert user_id == 42
        assert parsed_nonce == nonce

        # Verify community token was stored
        set_calls = [c for c in redis.set.call_args_list if "vk_oauth:" in str(c)]
        assert len(set_calls) >= 1
        stored = json.loads(set_calls[0][0][1])
        assert stored["step"] == "community"
        assert stored["access_token"] == "community_token_for_100"
        assert stored["group_id"] == 100
        assert stored["group_name"] == "Group A"


# ---------------------------------------------------------------------------
# get_oauth_result
# ---------------------------------------------------------------------------


class TestGetOAuthResult:
    async def test_returns_and_deletes_atomically(self) -> None:
        result = {"step": "community", "access_token": "tok", "group_id": 1}
        service, redis = _make_service()
        redis.getdel = AsyncMock(return_value=json.dumps(result))

        data = await service.get_oauth_result("nonce123")
        assert data is not None
        assert data["access_token"] == "tok"
        redis.getdel.assert_called_once_with(CacheKeys.vk_oauth("nonce123"))

    async def test_returns_none_when_missing(self) -> None:
        service, redis = _make_service()
        redis.getdel = AsyncMock(return_value=None)

        data = await service.get_oauth_result("missing")
        assert data is None

    async def test_returns_none_on_invalid_json(self) -> None:
        service, redis = _make_service()
        redis.getdel = AsyncMock(return_value="not-json")

        data = await service.get_oauth_result("bad")
        assert data is None


# ---------------------------------------------------------------------------
# Token exchange errors
# ---------------------------------------------------------------------------


class TestExchangeErrors:
    async def test_http_error_during_vkid_exchange(self) -> None:
        """Step 1: VK ID OAuth 2.1 HTTP error."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "id.vk.ru/oauth2/auth" in str(request.url):
                raise httpx.ConnectError("VK ID down")
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({"user_id": 42, "step": "groups", "code_verifier": "cv"})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="HTTP error"):
            await service.handle_callback(code="code", state=state, device_id="dev")

    async def test_http_error_during_classic_exchange(self) -> None:
        """Step 2: classic OAuth HTTP error."""

        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth.vk.com/access_token" in str(request.url):
                raise httpx.ConnectError("VK down")
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce, group_ids=100)
        auth_data = json.dumps({"user_id": 42, "step": "community", "group_id": 100})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="HTTP error"):
            await service.handle_callback(code="code", state=state)

    async def test_non_200_vkid_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "id.vk.ru/oauth2/auth" in str(request.url):
                return httpx.Response(400, json={"error": "invalid_code"})
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({"user_id": 42, "step": "groups", "code_verifier": "cv"})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="HTTP 400"):
            await service.handle_callback(code="code", state=state, device_id="dev")

    async def test_non_200_classic_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth.vk.com/access_token" in str(request.url):
                return httpx.Response(400, json={"error": "invalid_code"})
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce, group_ids=100)
        auth_data = json.dumps({"user_id": 42, "step": "community", "group_id": 100})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="HTTP 400"):
            await service.handle_callback(code="code", state=state)

    async def test_no_access_token_in_vkid_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "id.vk.ru/oauth2/auth" in str(request.url):
                return httpx.Response(200, json={"error": "invalid_grant"})
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({"user_id": 42, "step": "groups", "code_verifier": "cv"})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="No access_token"):
            await service.handle_callback(code="code", state=state, device_id="dev")

    async def test_no_access_token_in_classic_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth.vk.com/access_token" in str(request.url):
                return httpx.Response(200, json={"error": "invalid_grant"})
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce, group_ids=100)
        auth_data = json.dumps({"user_id": 42, "step": "community", "group_id": 100})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)

        with pytest.raises(VKOAuthError, match="No access_token"):
            await service.handle_callback(code="code", state=state)


# ---------------------------------------------------------------------------
# groups.get API errors (step 1)
# ---------------------------------------------------------------------------


class TestFetchGroupsErrors:
    async def test_api_error_returns_empty_list(self) -> None:
        """groups.get returns VK API error -> empty groups, OAuth still succeeds."""

        async def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if "id.vk.ru/oauth2/auth" in url:
                return httpx.Response(200, json={
                    "access_token": "tok",
                    "expires_in": 3600,
                    "user_id": "42",
                })
            if "groups.get" in url:
                return httpx.Response(200, json={
                    "error": {
                        "error_code": 15,
                        "error_msg": "Access denied: no access to call this method",
                    },
                })
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        nonce = _nonce()
        _, state = service.build_authorize_url(user_id=42, nonce=nonce)
        auth_data = json.dumps({"user_id": 42, "step": "groups", "code_verifier": "cv"})
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)
        redis.delete = AsyncMock()

        user_id, parsed_nonce = await service.handle_callback(
            code="code", state=state, device_id="dev",
        )
        assert user_id == 42
        assert parsed_nonce == nonce


# ---------------------------------------------------------------------------
# build_oauth_url
# ---------------------------------------------------------------------------


class TestBuildOAuthUrl:
    def test_without_group_ids(self) -> None:
        service, _ = _make_service()
        url = service.build_oauth_url(42, "nonce123")
        assert "user_id=42" in url
        assert "nonce=nonce123" in url
        assert "group_ids" not in url

    def test_with_group_ids(self) -> None:
        service, _ = _make_service()
        url = service.build_oauth_url(42, "nonce123", group_ids=555)
        assert "group_ids=555" in url


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


class TestPKCE:
    def test_code_verifier_length(self) -> None:
        from services.oauth.vk import _generate_code_verifier
        cv = _generate_code_verifier()
        assert 43 <= len(cv) <= 128

    def test_code_challenge_is_base64url(self) -> None:
        from services.oauth.vk import _generate_code_challenge, _generate_code_verifier
        cv = _generate_code_verifier()
        cc = _generate_code_challenge(cv)
        # base64url characters only (no padding)
        assert "=" not in cc
        assert all(c.isalnum() or c in "-_" for c in cc)
