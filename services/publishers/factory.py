"""Shared publisher factory — single source of publisher creation.

Replaces duplicated _get_publisher() in services/publish.py and
routers/publishing/pipeline/social/generation.py.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from .base import BasePublisher, TokenRefreshCallback


class PublisherSettings(Protocol):
    """Minimal settings interface for publisher creation (no bot/ dependency)."""

    vk_app_id: int
    pinterest_app_id: str
    pinterest_app_secret: SecretStr


def create_publisher(
    platform: str,
    http_client: httpx.AsyncClient,
    settings: PublisherSettings,
    on_token_refresh: TokenRefreshCallback | None = None,
) -> BasePublisher:
    """Create publisher for platform with proper credentials from settings."""
    from .pinterest import PinterestPublisher
    from .telegram import TelegramPublisher
    from .vk import VKPublisher
    from .wordpress import WordPressPublisher

    match platform:
        case "wordpress":
            return WordPressPublisher(http_client)
        case "telegram":
            return TelegramPublisher(http_client)
        case "vk":
            return VKPublisher(
                http_client,
                vk_app_id=settings.vk_app_id,
                on_token_refresh=on_token_refresh,
            )
        case "pinterest":
            return PinterestPublisher(
                http_client=http_client,
                client_id=settings.pinterest_app_id,
                client_secret=settings.pinterest_app_secret.get_secret_value(),
                on_token_refresh=on_token_refresh,
            )
        case _:
            msg = f"Unknown platform: {platform}"
            raise ValueError(msg)


def make_token_refresh_cb(
    db: Any,
    connection_id: int,
    enc_key: str,
) -> TokenRefreshCallback:
    """Build callback to persist refreshed OAuth credentials in DB."""

    async def _cb(_old_creds: dict[str, Any], new_creds: dict[str, Any]) -> None:
        from db.credential_manager import CredentialManager
        from db.repositories.connections import ConnectionsRepository

        cm = CredentialManager(enc_key)
        repo = ConnectionsRepository(db, cm)
        await repo.update_credentials(connection_id, new_creds)

    return _cb
