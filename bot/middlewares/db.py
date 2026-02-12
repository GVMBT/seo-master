"""DBSessionMiddleware — injects shared clients into handler data."""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from cache.client import RedisClient
from db.client import SupabaseClient


class DBSessionMiddleware(BaseMiddleware):
    """Outer middleware: injects data["db"], data["redis"], data["http_client"].

    All clients are created once at startup (main.py) and shared
    across all requests (ARCHITECTURE.md §2.2).
    """

    def __init__(
        self,
        db: SupabaseClient,
        redis: RedisClient,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._db = db
        self._redis = redis
        self._http_client = http_client

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["db"] = self._db
        data["redis"] = self._redis
        data["http_client"] = self._http_client
        return await handler(event, data)
