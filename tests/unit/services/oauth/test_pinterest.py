"""Tests for services/oauth/pinterest.py — Pinterest OAuth service.

Covers: handle_callback flow, _exchange_code, _store_tokens.
E20 (30min TTL), E30 (HMAC state protection).
State build/parse tests are in test_state.py.
"""

from __future__ import annotations

import json
import secrets
from unittest.mock import AsyncMock

import httpx
import pytest

from services.oauth.pinterest import (
    PINTEREST_AUTH_TTL,
    PinterestOAuthError,
    PinterestOAuthService,
)
from services.oauth.state import OAuthStateError, build_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENCRYPTION_KEY = "test-encryption-key-for-hmac-32ch"


def _nonce() -> str:
    """Generate a valid 22-char nonce (same as production)."""
    return secrets.token_urlsafe(16)


def _make_service(handler: object, redis: AsyncMock | None = None) -> PinterestOAuthService:
    transport = httpx.MockTransport(handler)  # type: ignore[arg-type]
    http = httpx.AsyncClient(transport=transport)
    return PinterestOAuthService(
        http_client=http,
        redis=redis or AsyncMock(),
        encryption_key=_ENCRYPTION_KEY,
        pinterest_app_id="test_app_id",
        pinterest_app_secret="test_app_secret",
        redirect_uri="https://example.com/callback",
    )


# ---------------------------------------------------------------------------
# PinterestOAuthError
# ---------------------------------------------------------------------------


class TestPinterestOAuthError:
    def test_default_message(self) -> None:
        err = PinterestOAuthError()
        assert str(err) == "Pinterest OAuth failed"
        assert "Pinterest" in err.user_message

    def test_custom_message(self) -> None:
        err = PinterestOAuthError("Custom error")
        assert str(err) == "Custom error"

    def test_is_app_error_subclass(self) -> None:
        from bot.exceptions import AppError

        err = PinterestOAuthError()
        assert isinstance(err, AppError)

    def test_is_oauth_state_error_subclass(self) -> None:
        err = PinterestOAuthError()
        assert isinstance(err, OAuthStateError)


# ---------------------------------------------------------------------------
# PinterestOAuthService._exchange_code
# ---------------------------------------------------------------------------


class TestExchangeCode:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            assert "authorization_code" in body
            assert "test_code_123" in body
            return httpx.Response(
                200,
                json={
                    "access_token": "pin_at",
                    "refresh_token": "pin_rt",
                    "expires_in": 2592000,
                },
            )

        service = _make_service(handler)
        tokens = await service._exchange_code("test_code_123")
        assert tokens["access_token"] == "pin_at"
        assert tokens["refresh_token"] == "pin_rt"
        assert "expires_at" in tokens  # expires_in → expires_at (ISO datetime)

    async def test_no_access_token_raises(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"error": "invalid_grant"})

        service = _make_service(handler)
        with pytest.raises(PinterestOAuthError, match="No access_token"):
            await service._exchange_code("bad_code")

    async def test_http_error_status_raises(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "invalid_grant"})

        service = _make_service(handler)
        with pytest.raises(PinterestOAuthError, match="HTTP 400"):
            await service._exchange_code("code")

    async def test_network_error_raises(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("Pinterest down")

        service = _make_service(handler)
        with pytest.raises(PinterestOAuthError, match="HTTP error"):
            await service._exchange_code("code")

    async def test_missing_refresh_token_defaults_empty(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "at"})

        service = _make_service(handler)
        tokens = await service._exchange_code("code")
        assert tokens["refresh_token"] == ""
        assert "expires_at" in tokens  # expires_in converted to ISO datetime


# ---------------------------------------------------------------------------
# PinterestOAuthService._store_tokens
# ---------------------------------------------------------------------------


class TestStoreTokens:
    async def test_stores_with_correct_key_and_ttl(self) -> None:
        redis = AsyncMock()

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        service = _make_service(handler, redis=redis)
        tokens = {"access_token": "at", "refresh_token": "rt"}
        await service._store_tokens("nonce_abc", tokens)

        redis.set.assert_awaited_once()
        call_args = redis.set.call_args
        assert call_args.args[0] == "pinterest_auth:nonce_abc"
        stored = json.loads(call_args.args[1])
        assert stored["access_token"] == "at"
        assert call_args.kwargs.get("ex") == PINTEREST_AUTH_TTL or call_args.args[2] == PINTEREST_AUTH_TTL


# ---------------------------------------------------------------------------
# PinterestOAuthService.handle_callback
# ---------------------------------------------------------------------------


class TestHandleCallback:
    async def test_full_flow(self) -> None:
        redis = AsyncMock()
        redis.set.return_value = "OK"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "new_at",
                    "refresh_token": "new_rt",
                    "expires_in": 2592000,
                },
            )

        nonce = _nonce()
        service = _make_service(handler, redis=redis)
        state = build_state(12345, nonce, _ENCRYPTION_KEY)
        user_id, parsed_nonce = await service.handle_callback("auth_code_xyz", state)

        assert user_id == 12345
        assert parsed_nonce == nonce
        # 2 calls: 1 for single-use NX lock (H10), 1 for token storage
        assert redis.set.await_count == 2

    async def test_invalid_state_raises(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        service = _make_service(handler)
        with pytest.raises(OAuthStateError):
            await service.handle_callback("code", "invalid_state")

    async def test_exchange_failure_propagates(self) -> None:
        redis = AsyncMock()
        redis.set.return_value = "OK"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad"})

        nonce = _nonce()
        service = _make_service(handler, redis=redis)
        state = build_state(12345, nonce, _ENCRYPTION_KEY)
        with pytest.raises(PinterestOAuthError):
            await service.handle_callback("bad_code", state)

    async def test_replay_attack_rejected(self) -> None:
        """H10: second use of same state token should be rejected."""
        redis = AsyncMock()
        redis.set.return_value = None

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"access_token": "at"})

        nonce = _nonce()
        service = _make_service(handler, redis=redis)
        state = build_state(12345, nonce, _ENCRYPTION_KEY)
        with pytest.raises(PinterestOAuthError, match="replay"):
            await service.handle_callback("code", state)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_auth_ttl_30_min(self) -> None:
        """E20: 30min TTL for OAuth state."""
        assert PINTEREST_AUTH_TTL == 1800
