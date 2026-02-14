"""Per-action rate limiting using Redis INCR + EXPIRE.

Source of truth: API_CONTRACTS.md section 4.1.
"""

import structlog

from bot.exceptions import RateLimitError
from cache.client import RedisClient
from cache.keys import CacheKeys

log = structlog.get_logger()

# {action: (max_requests, window_seconds)}
RATE_LIMITS: dict[str, tuple[int, int]] = {
    "text_generation": (10, 3600),       # 10/hour
    "image_generation": (20, 3600),      # 20/hour
    "keyword_generation": (5, 3600),     # 5/hour
    "token_purchase": (5, 600),          # 5/10min
    "platform_connection": (10, 3600),   # 10/hour
}


class RateLimiter:
    """Redis-backed per-action rate limiter."""

    def __init__(self, redis: RedisClient) -> None:
        self._redis = redis

    async def check(self, user_id: int, action: str) -> None:
        """Check rate limit for user+action. Raises RateLimitError if exceeded.

        Pattern: INCR first (atomic), then check. If over limit, DECR back
        to undo the increment and raise. This avoids the GET-then-INCR race.
        """
        limit_config = RATE_LIMITS.get(action)
        if limit_config is None:
            return  # No limit configured for this action

        max_requests, window_seconds = limit_config
        key = CacheKeys.rate_limit(user_id, action)

        current = await self._redis.incr(key)

        # Set TTL on first increment to start the window.
        # Also defensively set TTL if it's missing (race condition recovery).
        if current == 1:
            await self._redis.expire(key, window_seconds)
        elif current == 2:
            # Defensive: if key lost its TTL between first and second call
            ttl = await self._redis.ttl(key)
            if ttl is not None and ttl < 0:
                await self._redis.expire(key, window_seconds)

        if current > max_requests:
            # Undo the increment — this request should not count
            await self._redis.decr(key)
            ttl = await self._redis.ttl(key)
            # Ensure TTL exists even if it was lost (defensive)
            if ttl < 0:
                await self._redis.expire(key, window_seconds)
                ttl = window_seconds
            remaining_seconds = max(ttl, 0)
            log.warning(
                "rate_limit_exceeded",
                user_id=user_id,
                action=action,
                current=current,
                max_requests=max_requests,
                retry_after=remaining_seconds,
            )
            minutes = (remaining_seconds + 59) // 60  # ceil to minutes
            raise RateLimitError(
                message=f"Rate limit exceeded for {action}: {current}/{max_requests}",
                user_message=f"Превышен лимит запросов. Подождите {minutes} мин.",
                retry_after_seconds=remaining_seconds,
            )

    async def check_batch(self, user_id: int, action: str, count: int) -> None:
        """Reserve N rate limit slots atomically.

        Used by ImageService to reserve N slots before parallel generation.
        Pattern: INCRBY(key, count), check. If over limit, DECRBY back and raise.
        """
        if count <= 0:
            return

        limit_config = RATE_LIMITS.get(action)
        if limit_config is None:
            return

        max_requests, window_seconds = limit_config
        key = CacheKeys.rate_limit(user_id, action)

        # Atomic increment-first pattern: INCRBY returns new value.
        # If new_value == count, the key was just created → set TTL.
        # Defensive TTL check when new_value == count*2 (second call).
        new_value = await self._redis.incrby(key, count)

        if new_value == count:
            await self._redis.expire(key, window_seconds)
        elif new_value <= count * 2:
            ttl = await self._redis.ttl(key)
            if ttl is not None and ttl < 0:
                await self._redis.expire(key, window_seconds)

        if new_value > max_requests:
            # Undo the batch increment
            await self._redis.decrby(key, count)
            ttl = await self._redis.ttl(key)
            if ttl < 0:
                await self._redis.expire(key, window_seconds)
                ttl = window_seconds
            remaining_seconds = max(ttl, 0)
            log.warning(
                "rate_limit_batch_exceeded",
                user_id=user_id,
                action=action,
                requested=count,
                current=new_value - count,
                max_requests=max_requests,
                retry_after=remaining_seconds,
            )
            minutes = (remaining_seconds + 59) // 60
            raise RateLimitError(
                message=(
                    f"Rate limit exceeded for {action}: "
                    f"need {count} slots, {max_requests - (new_value - count)} available"
                ),
                user_message=f"Превышен лимит запросов. Подождите {minutes} мин.",
                retry_after_seconds=remaining_seconds,
            )
