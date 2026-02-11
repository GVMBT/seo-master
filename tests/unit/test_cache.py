"""Tests for cache/client.py — Redis client wrapper."""

from unittest.mock import AsyncMock

import pytest

from cache.client import RedisClient


@pytest.fixture
def mock_redis() -> AsyncMock:
    """Mock the underlying upstash Redis client."""
    return AsyncMock()


@pytest.fixture
def client(mock_redis: AsyncMock) -> RedisClient:
    """RedisClient with mocked internals."""
    c = RedisClient.__new__(RedisClient)
    c._redis = mock_redis
    return c


class TestRedisClientGet:
    @pytest.mark.asyncio
    async def test_get_existing_key(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = "value"
        result = await client.get("key")
        assert result == "value"
        mock_redis.get.assert_awaited_once_with("key")

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.get.return_value = None
        result = await client.get("nonexistent")
        assert result is None


class TestRedisClientSet:
    @pytest.mark.asyncio
    async def test_set_simple(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.set.return_value = "OK"
        await client.set("key", "value")
        mock_redis.set.assert_awaited_once_with("key", "value", ex=None, nx=False)

    @pytest.mark.asyncio
    async def test_set_with_ttl(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.set.return_value = "OK"
        await client.set("key", "value", ex=300)
        mock_redis.set.assert_awaited_once_with("key", "value", ex=300, nx=False)

    @pytest.mark.asyncio
    async def test_set_with_nx(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.set.return_value = True
        await client.set("key", "value", nx=True)
        mock_redis.set.assert_awaited_once_with("key", "value", ex=None, nx=True)

    @pytest.mark.asyncio
    async def test_set_with_ttl_and_nx(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.set.return_value = True
        result = await client.set("key", "value", ex=300, nx=True)
        mock_redis.set.assert_awaited_once_with("key", "value", ex=300, nx=True)
        assert result is True


class TestRedisClientDelete:
    @pytest.mark.asyncio
    async def test_delete_single_key(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.delete.return_value = 1
        result = await client.delete("key")
        assert result == 1

    @pytest.mark.asyncio
    async def test_delete_multiple_keys(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.delete.return_value = 2
        result = await client.delete("a", "b")
        assert result == 2
        mock_redis.delete.assert_awaited_once_with("a", "b")


class TestRedisClientIncr:
    @pytest.mark.asyncio
    async def test_incr_returns_new_value(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.incr.return_value = 5
        result = await client.incr("counter")
        assert result == 5
        mock_redis.incr.assert_awaited_once_with("counter")


class TestRedisClientExpire:
    @pytest.mark.asyncio
    async def test_expire(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.expire.return_value = True
        result = await client.expire("key", 60)
        assert result is True


class TestRedisClientExists:
    @pytest.mark.asyncio
    async def test_exists(self, client: RedisClient, mock_redis: AsyncMock) -> None:
        mock_redis.exists.return_value = 1
        result = await client.exists("key")
        assert result == 1
