"""Shared publisher factory — single source of publisher creation.

Replaces duplicated _get_publisher() in services/publish.py and
routers/publishing/pipeline/social/generation.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from .base import BasePublisher, TokenRefreshCallback

if TYPE_CHECKING:
    from bot.config import Settings


def create_publisher(
    platform: str,
    http_client: httpx.AsyncClient,
    settings: Settings,
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
