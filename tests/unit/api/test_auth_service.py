"""Tests for api/auth_service.py — Pinterest OAuth service.

Covers: build_state, parse_and_verify_state (valid/invalid/tampered),
handle_callback flow, _exchange_code, _store_tokens.
E20 (30min TTL), E30 (HMAC state protection).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from api.auth_service import (
    PINTEREST_AUTH_TTL,
    PinterestOAuthError,
    PinterestOAuthService,
    build_state,
    parse_and_verify_state,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ENCRYPTION_KEY = "test-encryption-key-for-hmac-32ch"


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
# build_state
# ---------------------------------------------------------------------------


class TestBuildState:
    def test_format_user_nonce_hmac(self) -> None:
        state = build_state(12345, "abc123", _ENCRYPTION_KEY)
        parts = state.split("_", maxsplit=2)
        assert len(parts) == 3
        assert parts[0] == "12345"
        assert parts[1] == "abc123"
        assert len(parts[2]) == 64  # SHA-256 hex

    def test_different_users_different_hmac(self) -> None:
        s1 = build_state(111, "nonce", _ENCRYPTION_KEY)
        s2 = build_state(222, "nonce", _ENCRYPTION_KEY)
        assert s1 != s2

    def test_different_nonces_different_hmac(self) -> None:
        s1 = build_state(111, "nonce_a", _ENCRYPTION_KEY)
        s2 = build_state(111, "nonce_b", _ENCRYPTION_KEY)
        assert s1 != s2

    def test_different_keys_different_hmac(self) -> None:
        s1 = build_state(111, "nonce", "key_one")
        s2 = build_state(111, "nonce", "key_two")
        assert s1 != s2

    def test_reproducible(self) -> None:
        s1 = build_state(111, "nonce", _ENCRYPTION_KEY)
        s2 = build_state(111, "nonce", _ENCRYPTION_KEY)
        assert s1 == s2


# ---------------------------------------------------------------------------
# parse_and_verify_state
# ---------------------------------------------------------------------------


class TestParseAndVerifyState:
    def test_valid_state(self) -> None:
        # Nonce must not contain underscores (production uses token_hex)
        state = build_state(12345, "abc123def456", _ENCRYPTION_KEY)
        user_id, nonce = parse_and_verify_state(state, _ENCRYPTION_KEY)
        assert user_id == 12345
        assert nonce == "abc123def456"

    def test_invalid_format_too_few_parts(self) -> None:
        with pytest.raises(PinterestOAuthError, match="Invalid state format"):
            parse_and_verify_state("12345_nonce", _ENCRYPTION_KEY)

    def test_invalid_format_no_separator(self) -> None:
        with pytest.raises(PinterestOAuthError, match="Invalid state format"):
            parse_and_verify_state("garbage", _ENCRYPTION_KEY)

    def test_invalid_user_id_not_integer(self) -> None:
        """E30: tampered user_id."""
        with pytest.raises(PinterestOAuthError, match="Invalid user_id"):
            parse_and_verify_state("abc_nonce_" + "0" * 64, _ENCRYPTION_KEY)

    def test_tampered_hmac(self) -> None:
        """E30: CSRF protection via HMAC verification."""
        state = build_state(12345, "nonce", _ENCRYPTION_KEY)
        # Replace last char of HMAC
        tampered = state[:-1] + ("0" if state[-1] != "0" else "1")
        with pytest.raises(PinterestOAuthError, match="HMAC"):
            parse_and_verify_state(tampered, _ENCRYPTION_KEY)

    def test_wrong_encryption_key(self) -> None:
        state = build_state(12345, "nonce", _ENCRYPTION_KEY)
        with pytest.raises(PinterestOAuthError, match="HMAC"):
            parse_and_verify_state(state, "wrong-key")

    def test_tampered_user_id_hmac_mismatch(self) -> None:
        """E30: attacker changes user_id but keeps old HMAC."""
        state = build_state(12345, "nonce", _ENCRYPTION_KEY)
        parts = state.split("_", maxsplit=2)
        tampered = f"99999_{parts[1]}_{parts[2]}"
        with pytest.raises(PinterestOAuthError, match="HMAC"):
            parse_and_verify_state(tampered, _ENCRYPTION_KEY)


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


# ---------------------------------------------------------------------------
# PinterestOAuthService._exchange_code
# ---------------------------------------------------------------------------


class TestExchangeCode:
    async def test_success(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = request.content.decode()
            assert "authorization_code" in body
            assert "test_code_123" in body
            return httpx.Response(200, json={
                "access_token": "pin_at",
                "refresh_token": "pin_rt",
                "expires_in": 2592000,
            })

        service = _make_service(handler)
        tokens = await service._exchange_code("test_code_123")
        assert tokens["access_token"] == "pin_at"
        assert tokens["refresh_token"] == "pin_rt"
        assert tokens["expires_in"] == 2592000

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
        assert tokens["expires_in"] == 2592000


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

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={
                "access_token": "new_at",
                "refresh_token": "new_rt",
                "expires_in": 2592000,
            })

        service = _make_service(handler, redis=redis)
        state = build_state(12345, "testnonce123", _ENCRYPTION_KEY)
        user_id, nonce = await service.handle_callback("auth_code_xyz", state)

        assert user_id == 12345
        assert nonce == "testnonce123"
        redis.set.assert_awaited_once()

    async def test_invalid_state_raises(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        service = _make_service(handler)
        with pytest.raises(PinterestOAuthError):
            await service.handle_callback("code", "invalid_state")

    async def test_exchange_failure_propagates(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad"})

        service = _make_service(handler)
        state = build_state(12345, "nonce", _ENCRYPTION_KEY)
        with pytest.raises(PinterestOAuthError):
            await service.handle_callback("bad_code", state)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_auth_ttl_30_min(self) -> None:
        """E20: 30min TTL for OAuth state."""
        assert PINTEREST_AUTH_TTL == 1800
