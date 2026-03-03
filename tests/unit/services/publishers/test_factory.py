"""Tests for services/publishers/factory.py — publisher factory.

Covers: create_publisher() for all 4 platforms + unknown platform ValueError.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from services.publishers.factory import create_publisher
from services.publishers.pinterest import PinterestPublisher
from services.publishers.telegram import TelegramPublisher
from services.publishers.vk import VKPublisher
from services.publishers.wordpress import WordPressPublisher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_settings() -> MagicMock:
    """Create a mock Settings with required publisher fields."""
    settings = MagicMock()
    settings.vk_app_id = 12345
    settings.pinterest_app_id = "pin_app"
    settings.pinterest_app_secret = SecretStr("pin_secret")
    return settings


def _noop_http_client() -> httpx.AsyncClient:
    """AsyncClient with a dummy transport (never actually used)."""
    transport = httpx.MockTransport(lambda _: httpx.Response(200))
    return httpx.AsyncClient(transport=transport)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCreatePublisher:
    def test_create_wordpress_publisher(self) -> None:
        """create_publisher('wordpress') returns a WordPressPublisher."""
        client = _noop_http_client()
        settings = _mock_settings()

        pub = create_publisher("wordpress", client, settings)

        assert isinstance(pub, WordPressPublisher)

    def test_create_telegram_publisher(self) -> None:
        """create_publisher('telegram') returns a TelegramPublisher."""
        client = _noop_http_client()
        settings = _mock_settings()

        pub = create_publisher("telegram", client, settings)

        assert isinstance(pub, TelegramPublisher)

    def test_create_vk_publisher_with_credentials(self) -> None:
        """create_publisher('vk') returns VKPublisher with correct app_id from settings."""
        client = _noop_http_client()
        settings = _mock_settings()

        pub = create_publisher("vk", client, settings)

        assert isinstance(pub, VKPublisher)
        assert pub._app_id == 12345

    def test_create_pinterest_publisher_with_credentials(self) -> None:
        """create_publisher('pinterest') returns PinterestPublisher with correct client_id/secret."""
        client = _noop_http_client()
        settings = _mock_settings()

        pub = create_publisher("pinterest", client, settings)

        assert isinstance(pub, PinterestPublisher)
        assert pub._client_id == "pin_app"
        assert pub._client_secret == "pin_secret"

    def test_create_vk_with_token_refresh_callback(self) -> None:
        """on_token_refresh callback is passed through to VKPublisher."""
        client = _noop_http_client()
        settings = _mock_settings()

        async def my_callback(old_creds: dict, new_creds: dict) -> None:
            pass  # pragma: no cover

        pub = create_publisher("vk", client, settings, on_token_refresh=my_callback)

        assert isinstance(pub, VKPublisher)
        assert pub._on_token_refresh is my_callback

    def test_create_pinterest_with_token_refresh_callback(self) -> None:
        """on_token_refresh callback is passed through to PinterestPublisher."""
        client = _noop_http_client()
        settings = _mock_settings()

        async def my_callback(old_creds: dict, new_creds: dict) -> None:
            pass  # pragma: no cover

        pub = create_publisher("pinterest", client, settings, on_token_refresh=my_callback)

        assert isinstance(pub, PinterestPublisher)
        assert pub._on_token_refresh is my_callback

    def test_unknown_platform_raises_value_error(self) -> None:
        """Unknown platform name raises ValueError with descriptive message."""
        client = _noop_http_client()
        settings = _mock_settings()

        with pytest.raises(ValueError, match="Unknown platform: bitrix"):
            create_publisher("bitrix", client, settings)

    def test_unknown_platform_empty_string_raises(self) -> None:
        """Empty string platform name raises ValueError."""
        client = _noop_http_client()
        settings = _mock_settings()

        with pytest.raises(ValueError, match="Unknown platform: "):
            create_publisher("", client, settings)

    def test_wordpress_does_not_pass_callback(self) -> None:
        """WordPress publisher ignores on_token_refresh (no OAuth refresh)."""
        client = _noop_http_client()
        settings = _mock_settings()

        async def my_callback(old_creds: dict, new_creds: dict) -> None:
            pass  # pragma: no cover

        pub = create_publisher("wordpress", client, settings, on_token_refresh=my_callback)

        assert isinstance(pub, WordPressPublisher)
        # WordPressPublisher has no _on_token_refresh attribute
        assert not hasattr(pub, "_on_token_refresh")

    def test_telegram_does_not_pass_callback(self) -> None:
        """Telegram publisher ignores on_token_refresh (no OAuth refresh)."""
        client = _noop_http_client()
        settings = _mock_settings()

        async def my_callback(old_creds: dict, new_creds: dict) -> None:
            pass  # pragma: no cover

        pub = create_publisher("telegram", client, settings, on_token_refresh=my_callback)

        assert isinstance(pub, TelegramPublisher)
        assert not hasattr(pub, "_on_token_refresh")
