"""Tests for db/credential_manager.py — Fernet encrypt/decrypt."""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from db.credential_manager import CredentialManager


@pytest.fixture
def encryption_key() -> str:
    """Generate a fresh Fernet key for testing."""
    return Fernet.generate_key().decode()


@pytest.fixture
def cm(encryption_key: str) -> CredentialManager:
    """CredentialManager instance with test key."""
    return CredentialManager(encryption_key)


class TestCredentialManager:
    def test_encrypt_returns_string(self, cm: CredentialManager) -> None:
        result = cm.encrypt({"token": "abc123"})
        assert isinstance(result, str)
        assert len(result) > 0

    def test_encrypt_decrypt_roundtrip(self, cm: CredentialManager) -> None:
        original = {"token": "abc123", "url": "https://example.com"}
        encrypted = cm.encrypt(original)
        decrypted = cm.decrypt(encrypted)
        assert decrypted == original

    def test_encrypt_decrypt_unicode(self, cm: CredentialManager) -> None:
        original = {"name": "Тест", "emoji": "🔑"}
        encrypted = cm.encrypt(original)
        assert cm.decrypt(encrypted) == original

    def test_encrypt_produces_different_ciphertexts(self, cm: CredentialManager) -> None:
        data = {"key": "value"}
        enc1 = cm.encrypt(data)
        enc2 = cm.encrypt(data)
        assert enc1 != enc2  # Fernet uses random IV

    def test_decrypt_wrong_key_raises(self, cm: CredentialManager) -> None:
        encrypted = cm.encrypt({"secret": "data"})
        other_key = Fernet.generate_key().decode()
        other_cm = CredentialManager(other_key)
        with pytest.raises(InvalidToken):
            other_cm.decrypt(encrypted)

    def test_decrypt_corrupted_data_raises(self, cm: CredentialManager) -> None:
        with pytest.raises(Exception):  # noqa: B017
            cm.decrypt("not-a-valid-fernet-token")

    def test_encrypt_empty_dict(self, cm: CredentialManager) -> None:
        encrypted = cm.encrypt({})
        assert cm.decrypt(encrypted) == {}

    def test_encrypt_nested_dict(self, cm: CredentialManager) -> None:
        original = {
            "wordpress": {"url": "https://site.com", "user": "admin", "app_password": "xxxx"},
            "options": {"verify_ssl": True},
        }
        encrypted = cm.encrypt(original)
        assert cm.decrypt(encrypted) == original

    def test_encrypt_with_numbers_and_booleans(self, cm: CredentialManager) -> None:
        original = {"port": 443, "verify": True, "retries": 0}
        assert cm.decrypt(cm.encrypt(original)) == original
