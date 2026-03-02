"""Shared HMAC state functions for OAuth flows (Pinterest, VK).

HMAC-SHA256(user_id + nonce, ENCRYPTION_KEY) prevents CSRF (E30).
Single-use enforcement via Redis NX lock (H10).

Source of truth:
- docs/EDGE_CASES.md E30 (HMAC state)
"""

import hashlib
import hmac

import structlog

from bot.exceptions import AppError

log = structlog.get_logger()


class OAuthStateError(AppError):
    """Raised when OAuth state validation fails (E30)."""

    def __init__(
        self,
        message: str = "OAuth state validation failed",
        user_message: str = "Ошибка авторизации",
    ) -> None:
        super().__init__(message=message, user_message=user_message)


def build_state(user_id: int, nonce: str, encryption_key: str) -> str:
    """Build state param: {user_id}|{nonce}|{hmac_hex}.

    HMAC-SHA256(user_id + nonce, ENCRYPTION_KEY) prevents CSRF (E30).
    """
    payload = f"{user_id}|{nonce}"
    mac = hmac.new(
        encryption_key.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}|{mac}"


def parse_and_verify_state(
    state: str,
    encryption_key: str,
) -> tuple[int, str]:
    """Parse state param and verify HMAC. Returns (user_id, nonce).

    State format: {user_id}|{nonce}|{hmac_hex}
    Raises OAuthStateError on invalid/tampered state (E30).
    """
    parts = state.split("|", maxsplit=2)
    expected_parts = 3
    if len(parts) != expected_parts:
        raise OAuthStateError("Invalid state format")

    raw_user_id, nonce, received_mac = parts

    try:
        user_id = int(raw_user_id)
    except ValueError as err:
        raise OAuthStateError("Invalid user_id in state") from err

    expected_mac = hmac.new(
        encryption_key.encode(),
        f"{user_id}|{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_mac, received_mac):
        log.warning("oauth_state_hmac_mismatch", user_id=user_id)
        raise OAuthStateError("State HMAC verification failed (E30)")

    return user_id, nonce
