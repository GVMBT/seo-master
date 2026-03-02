"""Tests for api/vk_oauth.py — VK ID OAuth 2.1 + PKCE service.

Covers: PKCE generation, HMAC state, code exchange, groups fetch,
Redis storage, single-use nonce, error handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from api.vk_oauth import VKOAuthError, VKOAuthService, _generate_pkce
from cache.keys import CacheKeys

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENCRYPTION_KEY = "test-encryption-key-32chars-long!"


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
        redirect_uri="https://example.com/api/auth/vk/callback",
    )
    return service, redis


# ---------------------------------------------------------------------------
# PKCE generation
# ---------------------------------------------------------------------------


class TestPKCE:
    def test_generate_pkce_returns_pair(self) -> None:
        verifier, challenge = _generate_pkce()
        assert len(verifier) > 40  # token_urlsafe(64)
        assert len(challenge) > 20  # base64url(sha256(...))
        assert "=" not in challenge  # padding stripped

    def test_generate_pkce_different_each_time(self) -> None:
        v1, c1 = _generate_pkce()
        v2, c2 = _generate_pkce()
        assert v1 != v2
        assert c1 != c2


# ---------------------------------------------------------------------------
# build_authorize_url
# ---------------------------------------------------------------------------


class TestBuildAuthorizeUrl:
    def test_returns_url_with_pkce_params(self) -> None:
        service, _ = _make_service()
        url, verifier, state = service.build_authorize_url(user_id=42, nonce="test_nonce")
        assert "id.vk.com/authorize" in url
        assert "response_type=code" in url
        assert "client_id=123456" in url
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url
        assert "scope=wall,groups,photos" in url
        assert len(verifier) > 40
        assert "|" in state  # HMAC state format

    def test_state_contains_user_id_and_nonce(self) -> None:
        service, _ = _make_service()
        _, _, state = service.build_authorize_url(user_id=42, nonce="abc123")
        parts = state.split("|")
        assert parts[0] == "42"
        assert parts[1] == "abc123"
        assert len(parts) == 3  # user_id|nonce|hmac


# ---------------------------------------------------------------------------
# store_pkce
# ---------------------------------------------------------------------------


class TestStorePkce:
    async def test_stores_code_verifier_in_redis(self) -> None:
        service, redis = _make_service()
        await service.store_pkce("nonce123", "verifier_abc", 42)
        redis.set.assert_called_once()
        key = redis.set.call_args[0][0]
        data = json.loads(redis.set.call_args[0][1])
        assert key == CacheKeys.vk_auth("nonce123")
        assert data["code_verifier"] == "verifier_abc"
        assert data["user_id"] == 42


# ---------------------------------------------------------------------------
# handle_callback
# ---------------------------------------------------------------------------


class TestHandleCallback:
    async def test_happy_path(self) -> None:
        """Full callback flow: verify state → exchange code → fetch groups → store."""
        service, redis = _make_service(handler=self._mock_vk_api)

        # Build state and store PKCE
        _, verifier, state = service.build_authorize_url(user_id=42, nonce="n1")
        auth_data = json.dumps({"code_verifier": verifier, "user_id": 42})

        # Configure Redis mock
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(side_effect=lambda key: auth_data if "vk_auth:" in key else None)
        redis.delete = AsyncMock()

        user_id, nonce = await service.handle_callback(
            code="auth_code_123",
            state=state,
            device_id="device_abc",
        )
        assert user_id == 42
        assert nonce == "n1"

        # Verify result was stored in vk_oauth:{nonce}
        set_calls = [c for c in redis.set.call_args_list if "vk_oauth:" in str(c)]
        assert len(set_calls) >= 1

    async def test_invalid_state_raises(self) -> None:
        service, redis = _make_service()
        redis.set = AsyncMock(return_value=True)

        with pytest.raises(VKOAuthError):
            await service.handle_callback(
                code="code",
                state="invalid|state",
                device_id="dev",
            )

    async def test_replay_attack_blocked(self) -> None:
        """Second use of same state should fail (H10)."""
        service, redis = _make_service()

        _, verifier, state = service.build_authorize_url(user_id=42, nonce="n1")
        auth_data = json.dumps({"code_verifier": verifier, "user_id": 42})
        redis.get = AsyncMock(return_value=auth_data)
        # Simulate NX lock already taken (replay)
        redis.set = AsyncMock(return_value=False)

        with pytest.raises(VKOAuthError, match="replay"):
            await service.handle_callback(
                code="code",
                state=state,
                device_id="dev",
            )

    async def test_expired_session_raises(self) -> None:
        """Missing vk_auth:{nonce} in Redis → expired."""
        service, redis = _make_service()
        _, _, state = service.build_authorize_url(user_id=42, nonce="n1")
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=None)  # No PKCE data

        with pytest.raises(VKOAuthError, match="expired"):
            await service.handle_callback(
                code="code",
                state=state,
                device_id="dev",
            )

    @staticmethod
    async def _mock_vk_api(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "oauth2/auth" in url:
            return httpx.Response(200, json={
                "access_token": "new_access_token",
                "refresh_token": "new_refresh_token",
                "expires_in": 3600,
                "user_id": 42,
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
# get_oauth_result
# ---------------------------------------------------------------------------


class TestGetOAuthResult:
    async def test_returns_and_deletes(self) -> None:
        result = {"access_token": "tok", "groups": [{"id": 1, "name": "G"}]}
        service, redis = _make_service()
        redis.get = AsyncMock(return_value=json.dumps(result))

        data = await service.get_oauth_result("nonce123")
        assert data is not None
        assert data["access_token"] == "tok"
        redis.delete.assert_called_once_with(CacheKeys.vk_oauth("nonce123"))

    async def test_returns_none_when_missing(self) -> None:
        service, redis = _make_service()
        redis.get = AsyncMock(return_value=None)

        data = await service.get_oauth_result("missing")
        assert data is None

    async def test_returns_none_on_invalid_json(self) -> None:
        service, redis = _make_service()
        redis.get = AsyncMock(return_value="not-json")

        data = await service.get_oauth_result("bad")
        assert data is None


# ---------------------------------------------------------------------------
# Token exchange errors
# ---------------------------------------------------------------------------


class TestExchangeErrors:
    async def test_http_error_during_exchange(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                raise httpx.ConnectError("VK down")
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        _, verifier, state = service.build_authorize_url(user_id=42, nonce="n1")
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=json.dumps({"code_verifier": verifier, "user_id": 42}))

        with pytest.raises(VKOAuthError, match="HTTP error"):
            await service.handle_callback(code="code", state=state, device_id="dev")

    async def test_non_200_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(400, json={"error": "invalid_code"})
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        _, verifier, state = service.build_authorize_url(user_id=42, nonce="n1")
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=json.dumps({"code_verifier": verifier, "user_id": 42}))

        with pytest.raises(VKOAuthError, match="HTTP 400"):
            await service.handle_callback(code="code", state=state, device_id="dev")

    async def test_no_access_token_in_response(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if "oauth2/auth" in str(request.url):
                return httpx.Response(200, json={"error": "invalid_grant"})
            return httpx.Response(404)

        service, redis = _make_service(handler=handler)
        _, verifier, state = service.build_authorize_url(user_id=42, nonce="n1")
        redis.set = AsyncMock(return_value=True)
        redis.get = AsyncMock(return_value=json.dumps({"code_verifier": verifier, "user_id": 42}))

        with pytest.raises(VKOAuthError, match="No access_token"):
            await service.handle_callback(code="code", state=state, device_id="dev")
