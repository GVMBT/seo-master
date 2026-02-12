"""Tests for cache/fsm_storage.py — UpstashFSMStorage."""

from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey

from cache.fsm_storage import UpstashFSMStorage


class TestStates(StatesGroup):
    step_one = State()
    step_two = State()


def _make_key(user_id: int = 123, chat_id: int = 123) -> StorageKey:
    return StorageKey(
        bot_id=1, chat_id=chat_id, user_id=user_id,
        thread_id=None, business_connection_id=None, destiny="default",
    )


@pytest.fixture
def redis() -> AsyncMock:
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=None)
    mock.delete = AsyncMock(return_value=1)
    return mock


@pytest.fixture
def storage(redis: AsyncMock) -> UpstashFSMStorage:
    return UpstashFSMStorage(redis=redis, state_ttl=86400)


class TestSetState:
    async def test_set_state_with_state_object(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key()
        await storage.set_state(key, TestStates.step_one)
        redis.set.assert_called_once()
        args = redis.set.call_args
        assert args[1]["ex"] == 86400
        assert "step_one" in args[0][1]

    async def test_set_state_with_string(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key()
        await storage.set_state(key, "TestStates:step_two")
        redis.set.assert_called_once()
        assert redis.set.call_args[0][1] == "TestStates:step_two"

    async def test_set_state_none_deletes(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key()
        await storage.set_state(key, None)
        redis.delete.assert_called_once()
        redis.set.assert_not_called()


class TestGetState:
    async def test_get_state_exists(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        redis.get.return_value = "TestStates:step_one"
        key = _make_key()
        result = await storage.get_state(key)
        assert result == "TestStates:step_one"

    async def test_get_state_not_exists(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        redis.get.return_value = None
        key = _make_key()
        result = await storage.get_state(key)
        assert result is None


class TestSetData:
    async def test_set_data_with_dict(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key()
        await storage.set_data(key, {"name": "test", "step": 1})
        redis.set.assert_called_once()
        stored = redis.set.call_args[0][1]
        assert '"name": "test"' in stored
        assert '"step": 1' in stored

    async def test_set_data_empty_deletes(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key()
        await storage.set_data(key, {})
        redis.delete.assert_called_once()
        redis.set.assert_not_called()

    async def test_set_data_with_ttl(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key()
        await storage.set_data(key, {"x": 1})
        assert redis.set.call_args[1]["ex"] == 86400


class TestGetData:
    async def test_get_data_exists(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        redis.get.return_value = '{"name": "test", "step": 1}'
        key = _make_key()
        result = await storage.get_data(key)
        assert result == {"name": "test", "step": 1}

    async def test_get_data_not_exists(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        redis.get.return_value = None
        key = _make_key()
        result = await storage.get_data(key)
        assert result == {}

    async def test_get_data_unicode(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        redis.get.return_value = '{"city": "Москва"}'
        key = _make_key()
        result = await storage.get_data(key)
        assert result["city"] == "Москва"


class TestKeyFormat:
    async def test_state_key_format(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key(user_id=42, chat_id=42)
        await storage.set_state(key, TestStates.step_one)
        redis_key = redis.set.call_args[0][0]
        assert redis_key == "fsm:42:42:state"

    async def test_data_key_format(self, storage: UpstashFSMStorage, redis: AsyncMock) -> None:
        key = _make_key(user_id=42, chat_id=42)
        await storage.set_data(key, {"x": 1})
        redis_key = redis.set.call_args[0][0]
        assert redis_key == "fsm:42:42:data"


class TestClose:
    async def test_close_is_noop(self, storage: UpstashFSMStorage) -> None:
        await storage.close()  # should not raise
