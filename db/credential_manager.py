"""Fernet-based credential encryption/decryption.

Used ONLY in repository layer for platform_connections.credentials.
Source: docs/API_CONTRACTS.md section 8.6.
"""

import json

from cryptography.fernet import Fernet


class CredentialManager:
    """Encrypt/decrypt platform credentials using Fernet symmetric encryption."""

    def __init__(self, encryption_key: str) -> None:
        self._fernet = Fernet(encryption_key.encode())

    def encrypt(self, credentials: dict) -> str:
        """Dict -> encrypted string for DB storage."""
        json_bytes = json.dumps(credentials, ensure_ascii=False).encode()
        return self._fernet.encrypt(json_bytes).decode()

    def decrypt(self, encrypted: str) -> dict:
        """Encrypted string from DB -> dict. Raises InvalidToken on bad key/data."""
        json_bytes = self._fernet.decrypt(encrypted.encode())
        return json.loads(json_bytes)  # type: ignore[no-any-return]
