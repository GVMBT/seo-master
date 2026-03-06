"""Shared HMAC state functions for OAuth flows (Pinterest, VK).

HMAC-SHA256(user_id + nonce, ENCRYPTION_KEY) prevents CSRF (E30).
Single-use enforcement via Redis NX lock (H10).

State is encoded WITHOUT delimiters (VK ID strips special characters).
Parsing uses fixed lengths: nonce=22 chars (token_urlsafe(16)), HMAC=64 hex chars.

Source of truth:
- docs/EDGE_CASES.md E30 (HMAC state)
"""

import hashlib
import hmac

import structlog

from bot.exceptions import AppError

log = structlog.get_logger()

_NONCE_LEN = 22  # secrets.token_urlsafe(16) always produces 22 chars
_HMAC_LEN = 64  # SHA-256 hex digest length


class OAuthStateError(AppError):
    """Raised when OAuth state validation fails (E30)."""

    def __init__(
        self,
        message: str = "OAuth state validation failed",
        user_message: str = "Ошибка авторизации",
    ) -> None:
        super().__init__(message=message, user_message=user_message)


def build_state(user_id: int, nonce: str, encryption_key: str) -> str:
    """Build state param: {user_id}{nonce}{hmac_hex} (no delimiters).

    HMAC-SHA256(user_id + nonce, ENCRYPTION_KEY) prevents CSRF (E30).
    No delimiters — VK ID strips special characters from state.
    """
    payload = f"{user_id}{nonce}"
    mac = hmac.new(
        encryption_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}{mac}"


def parse_and_verify_state(
    state: str,
    encryption_key: str,
) -> tuple[int, str]:
    """Parse state param and verify HMAC. Returns (user_id, nonce).

    State format: {user_id}{nonce}{hmac_hex} — no delimiters.
    Fixed lengths: nonce=22 chars, hmac=64 hex chars, user_id=remainder.
    Raises OAuthStateError on invalid/tampered state (E30).
    """
    min_len = 1 + _NONCE_LEN + _HMAC_LEN  # at least 1 digit for user_id
    if len(state) < min_len:
        raise OAuthStateError("Invalid state format")

    received_mac = state[-_HMAC_LEN:]
    prefix = state[:-_HMAC_LEN]
    nonce = prefix[-_NONCE_LEN:]
    raw_user_id = prefix[:-_NONCE_LEN]

    if not raw_user_id:
        raise OAuthStateError("Invalid state format")

    try:
        user_id = int(raw_user_id)
    except ValueError as err:
        raise OAuthStateError("Invalid user_id in state") from err

    expected_mac = hmac.new(
        encryption_key.encode(),
        f"{user_id}{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_mac, received_mac):
        log.warning("oauth_state_hmac_mismatch", user_id=user_id)
        raise OAuthStateError("State HMAC verification failed (E30)")

    return user_id, nonce
