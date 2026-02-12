"""Thin async wrapper around Upstash Redis HTTP client."""

import structlog
from upstash_redis.asyncio import Redis as AsyncRedis

log = structlog.get_logger()


class RedisClient:
    """Async Redis client backed by Upstash REST API.

    HTTP-based and stateless -- no persistent connections to manage.
    """

    def __init__(self, url: str, token: str) -> None:
        self._redis = AsyncRedis(url=url, token=token)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> str | None:
        """Set key-value with optional TTL (ex) and NX flag."""
        return await self._redis.set(key, value, ex=ex, nx=nx)

    async def delete(self, *keys: str) -> int:
        return await self._redis.delete(*keys)

    async def incr(self, key: str) -> int:
        return await self._redis.incr(key)

    async def expire(self, key: str, seconds: int) -> bool:
        return await self._redis.expire(key, seconds)

    async def exists(self, *keys: str) -> int:
        return await self._redis.exists(*keys)

    async def ttl(self, key: str) -> int:
        return await self._redis.ttl(key)

    async def ping(self) -> bool:
        """Check Redis connectivity. Returns True if healthy."""
        try:
            result = await self._redis.ping()
            return result == "PONG"
        except Exception:
            log.warning("redis_ping_failed", exc_info=True)
            return False
