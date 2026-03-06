"""Tests for services/oauth/state.py — HMAC state build/parse (E30).

State format: {user_id}{nonce}{hmac_hex} — no delimiters.
Fixed lengths: nonce=22 chars (token_urlsafe(16)), HMAC=64 hex chars.
"""

from __future__ import annotations

import secrets

import pytest

from services.oauth.state import OAuthStateError, build_state, parse_and_verify_state

_KEY = "test-encryption-key-for-hmac-32ch"


class TestBuildState:
    def test_format_no_delimiters(self) -> None:
        nonce = secrets.token_urlsafe(16)  # 22 chars
        state = build_state(12345, nonce, _KEY)
        # No special delimiters — VK-safe
        assert "|" not in state
        assert "." not in state
        # user_id digits + 22 nonce + 64 hmac
        assert len(state) == len("12345") + 22 + 64

    def test_roundtrip(self) -> None:
        nonce = secrets.token_urlsafe(16)
        state = build_state(99999, nonce, _KEY)
        user_id, parsed_nonce = parse_and_verify_state(state, _KEY)
        assert user_id == 99999
        assert parsed_nonce == nonce

    def test_different_users_different_state(self) -> None:
        nonce = secrets.token_urlsafe(16)
        s1 = build_state(111, nonce, _KEY)
        s2 = build_state(222, nonce, _KEY)
        assert s1 != s2

    def test_different_nonces_different_state(self) -> None:
        s1 = build_state(111, secrets.token_urlsafe(16), _KEY)
        s2 = build_state(111, secrets.token_urlsafe(16), _KEY)
        assert s1 != s2

    def test_different_keys_different_state(self) -> None:
        nonce = secrets.token_urlsafe(16)
        s1 = build_state(111, nonce, "key_one_padded_to_len!")
        s2 = build_state(111, nonce, "key_two_padded_to_len!")
        assert s1 != s2

    def test_reproducible(self) -> None:
        nonce = secrets.token_urlsafe(16)
        s1 = build_state(111, nonce, _KEY)
        s2 = build_state(111, nonce, _KEY)
        assert s1 == s2


class TestParseAndVerifyState:
    def test_valid_state(self) -> None:
        nonce = secrets.token_urlsafe(16)
        state = build_state(12345, nonce, _KEY)
        user_id, parsed_nonce = parse_and_verify_state(state, _KEY)
        assert user_id == 12345
        assert parsed_nonce == nonce

    def test_long_user_id(self) -> None:
        nonce = secrets.token_urlsafe(16)
        state = build_state(339469894, nonce, _KEY)
        user_id, parsed_nonce = parse_and_verify_state(state, _KEY)
        assert user_id == 339469894
        assert parsed_nonce == nonce

    def test_too_short_raises(self) -> None:
        with pytest.raises(OAuthStateError, match="Invalid state format"):
            parse_and_verify_state("tooshort", _KEY)

    def test_garbage_raises(self) -> None:
        with pytest.raises(OAuthStateError, match="Invalid state format"):
            parse_and_verify_state("x" * 86, _KEY)  # 86 = min_len but no valid user_id

    def test_tampered_hmac(self) -> None:
        nonce = secrets.token_urlsafe(16)
        state = build_state(12345, nonce, _KEY)
        tampered = state[:-1] + ("0" if state[-1] != "0" else "1")
        with pytest.raises(OAuthStateError, match="HMAC"):
            parse_and_verify_state(tampered, _KEY)

    def test_wrong_key(self) -> None:
        nonce = secrets.token_urlsafe(16)
        state = build_state(12345, nonce, _KEY)
        with pytest.raises(OAuthStateError, match="HMAC"):
            parse_and_verify_state(state, "wrong-key-that-is-different!!")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(OAuthStateError, match="Invalid state format"):
            parse_and_verify_state("", _KEY)

    def test_non_numeric_user_id_raises(self) -> None:
        # Craft a state where user_id position has letters
        with pytest.raises(OAuthStateError):
            parse_and_verify_state("abc" + "A" * 22 + "0" * 64, _KEY)
