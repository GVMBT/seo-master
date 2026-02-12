"""ThrottlingMiddleware — Redis-based rate limiting (token-bucket via INCR+EXPIRE)."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from cache.client import RedisClient
from cache.keys import CacheKeys

# Default anti-flood: 30 messages per 60 seconds (API_CONTRACTS.md §4.1)
_DEFAULT_RATE_LIMIT = 30
_DEFAULT_WINDOW = 60


class ThrottlingMiddleware(BaseMiddleware):
    """Inner middleware: silently drops events when user exceeds rate limit.

    Uses Redis INCR + EXPIRE for a sliding-window counter per user.
    """

    def __init__(
        self,
        redis: RedisClient,
        rate_limit: int = _DEFAULT_RATE_LIMIT,
        window: int = _DEFAULT_WINDOW,
    ) -> None:
        self._redis = redis
        self._rate_limit = rate_limit
        self._window = window

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)

        key = CacheKeys.throttle(user.id, "message")
        count = await self._redis.incr(key)
        # Always set EXPIRE — prevents key from persisting forever if
        # a previous INCR succeeded but EXPIRE failed (crash/timeout).
        await self._redis.expire(key, self._window)

        if count > self._rate_limit:
            return None  # silently drop (anti-flood)

        return await handler(event, data)
