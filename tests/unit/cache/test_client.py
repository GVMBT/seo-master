"""Tests for cache/client.py — RedisClient wrapper."""

from unittest.mock import AsyncMock

import pytest


class TestRedisPing:
    @pytest.mark.asyncio
    async def test_ping_returns_true_on_pong(self) -> None:
        from cache.client import RedisClient

        client = RedisClient(url="https://test.upstash.io", token="test-token")  # noqa: S106
        client._redis = AsyncMock()
        client._redis.ping = AsyncMock(return_value="PONG")
        assert await client.ping() is True

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_error(self) -> None:
        from cache.client import RedisClient

        client = RedisClient(url="https://test.upstash.io", token="test-token")  # noqa: S106
        client._redis = AsyncMock()
        client._redis.ping = AsyncMock(side_effect=ConnectionError("unreachable"))
        assert await client.ping() is False

    @pytest.mark.asyncio
    async def test_ping_returns_false_on_unexpected_response(self) -> None:
        from cache.client import RedisClient

        client = RedisClient(url="https://test.upstash.io", token="test-token")  # noqa: S106
        client._redis = AsyncMock()
        client._redis.ping = AsyncMock(return_value="NOT_PONG")
        assert await client.ping() is False
