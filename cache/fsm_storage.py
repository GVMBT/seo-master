"""Aiogram FSM storage backed by Upstash Redis (HTTP)."""

import json
from collections.abc import Mapping
from typing import Any, cast

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, DefaultKeyBuilder, StateType, StorageKey

from cache.client import RedisClient
from cache.keys import FSM_TTL


class UpstashFSMStorage(BaseStorage):
    """FSM storage using Upstash Redis HTTP API.

    Unlike aiogram's built-in RedisStorage (which uses redis.asyncio TCP),
    this uses our HTTP-based RedisClient for serverless Upstash.
    """

    def __init__(
        self,
        redis: RedisClient,
        state_ttl: int = FSM_TTL,
        key_builder: DefaultKeyBuilder | None = None,
    ) -> None:
        self._redis = redis
        self._state_ttl = state_ttl
        self._key_builder = key_builder or DefaultKeyBuilder(prefix="fsm")

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        redis_key = self._key_builder.build(key, "state")
        if state is None:
            await self._redis.delete(redis_key)
        else:
            state_str = cast(str, state.state if isinstance(state, State) else state)
            await self._redis.set(redis_key, state_str, ex=self._state_ttl)

    async def get_state(self, key: StorageKey) -> str | None:
        redis_key = self._key_builder.build(key, "state")
        return await self._redis.get(redis_key)

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        redis_key = self._key_builder.build(key, "data")
        if not data:
            await self._redis.delete(redis_key)
            return
        await self._redis.set(
            redis_key,
            json.dumps(dict(data), ensure_ascii=False, default=str),
            ex=self._state_ttl,
        )

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        redis_key = self._key_builder.build(key, "data")
        value = await self._redis.get(redis_key)
        if value is None:
            return {}
        return cast(dict[str, Any], json.loads(value))

    async def close(self) -> None:
        """No-op: Upstash HTTP is stateless."""
