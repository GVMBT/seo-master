"""ThrottlingMiddleware — Redis-based rate limiting (token-bucket via INCR+EXPIRE)."""

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, TelegramObject

from cache.client import RedisClient
from cache.keys import CacheKeys

# Anti-flood limits (API_CONTRACTS.md §4.1)
_MSG_RATE_LIMIT = 30  # text messages per window
_MSG_WINDOW = 60

_CB_RATE_LIMIT = 60  # callback queries per window (inline buttons)
_CB_WINDOW = 60


class ThrottlingMiddleware(BaseMiddleware):
    """Inner middleware: silently drops events when user exceeds rate limit.

    Uses Redis INCR + EXPIRE for a sliding-window counter per user.
    Separate counters for messages vs callback queries — inline button
    clicks should not exhaust the message budget.
    """

    def __init__(
        self,
        redis: RedisClient,
        rate_limit: int = _MSG_RATE_LIMIT,
        window: int = _MSG_WINDOW,
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

        if isinstance(event, CallbackQuery):
            action = "callback"
            limit = _CB_RATE_LIMIT
            window = _CB_WINDOW
        else:
            action = "message"
            limit = self._rate_limit
            window = self._window

        key = CacheKeys.throttle(user.id, action)
        count = await self._redis.incr(key)
        # Always set EXPIRE — prevents key from persisting forever if
        # a previous INCR succeeded but EXPIRE failed (crash/timeout).
        await self._redis.expire(key, window)

        if count > limit:
            return None  # silently drop (anti-flood)

        return await handler(event, data)
