"""Tests for bot/middlewares/ — all 5 middleware classes."""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.middlewares.auth import AuthMiddleware, FSMInactivityMiddleware
from bot.middlewares.db import DBSessionMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware


def _make_tg_user(user_id: int = 123) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    return user


def _make_mock_redis(cached_user: str | None = None) -> MagicMock:
    """Create mock Redis that returns cached_user on get()."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=cached_user)
    redis.set = AsyncMock(return_value=None)
    return redis


def _make_handler() -> AsyncMock:
    return AsyncMock(return_value="handler_result")


def _make_event() -> MagicMock:
    return MagicMock()


# === DBSessionMiddleware ===


class TestDBSessionMiddleware:
    async def test_injects_all_clients_into_data(self) -> None:
        db = MagicMock()
        redis = MagicMock()
        http_client = MagicMock()
        mw = DBSessionMiddleware(db, redis, http_client)
        handler = _make_handler()
        data: dict = {}

        await mw(handler, _make_event(), data)

        assert data["db"] is db
        assert data["redis"] is redis
        assert data["http_client"] is http_client
        handler.assert_called_once()

    async def test_returns_handler_result(self) -> None:
        mw = DBSessionMiddleware(MagicMock(), MagicMock(), MagicMock())
        handler = _make_handler()

        result = await mw(handler, _make_event(), {})

        assert result == "handler_result"


# === AuthMiddleware ===


class TestAuthMiddleware:
    @pytest.fixture
    def mock_user(self) -> MagicMock:
        user = MagicMock()
        user.id = 123
        user.balance = 1500
        user.role = "user"
        user.model_copy = lambda update: MagicMock(
            id=update.get("id", user.id),
            balance=update.get("balance", user.balance),
            role=update.get("role", user.role),
            model_dump=MagicMock(
                return_value={
                    "id": update.get("id", user.id),
                    "role": update.get("role", user.role),
                    "balance": user.balance,
                }
            ),
        )
        return user

    async def test_registers_user_and_injects_data(self, mock_user: MagicMock) -> None:
        mw = AuthMiddleware(admin_ids=[999])
        handler = _make_handler()
        tg_user = _make_tg_user(123)
        redis = _make_mock_redis()  # cache miss
        db = MagicMock()
        data: dict = {"event_from_user": tg_user, "db": db, "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            repo_cls.return_value.get_or_create = AsyncMock(return_value=(mock_user, False))
            await mw(handler, _make_event(), data)

        assert data["user"] is mock_user
        assert data["is_admin"] is False
        assert data["is_new_user"] is False
        handler.assert_called_once()
        redis.set.assert_called_once()  # cached after Supabase hit

    async def test_cache_hit_skips_supabase(self, mock_user: MagicMock) -> None:
        mw = AuthMiddleware(admin_ids=[999])
        handler = _make_handler()
        cached_json = json.dumps({"id": 123, "balance": 1500, "role": "user"})
        redis = _make_mock_redis(cached_user=cached_json)
        data: dict = {"event_from_user": _make_tg_user(123), "db": MagicMock(), "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            await mw(handler, _make_event(), data)
            repo_cls.return_value.get_or_create.assert_not_called()

        assert data["user"].id == 123
        handler.assert_called_once()

    async def test_new_user_flag_set_when_created(self, mock_user: MagicMock) -> None:
        mw = AuthMiddleware(admin_ids=[999])
        redis = _make_mock_redis()
        data: dict = {"event_from_user": _make_tg_user(123), "db": MagicMock(), "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            repo_cls.return_value.get_or_create = AsyncMock(return_value=(mock_user, True))
            await mw(_make_handler(), _make_event(), data)

        assert data["is_new_user"] is True

    async def test_get_or_create_called_with_user_data(self, mock_user: MagicMock) -> None:
        mw = AuthMiddleware(admin_ids=[999])
        tg_user = _make_tg_user(123)
        redis = _make_mock_redis()
        data: dict = {"event_from_user": tg_user, "db": MagicMock(), "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            repo_cls.return_value.get_or_create = AsyncMock(return_value=(mock_user, True))
            await mw(_make_handler(), _make_event(), data)
            repo_cls.return_value.get_or_create.assert_called_once()

    async def test_admin_flag_set_correctly(self, mock_user: MagicMock) -> None:
        mock_user.id = 999
        mw = AuthMiddleware(admin_ids=[999])
        redis = _make_mock_redis()
        data: dict = {"event_from_user": _make_tg_user(999), "db": MagicMock(), "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            repo_cls.return_value.get_or_create = AsyncMock(return_value=(mock_user, False))
            repo_cls.return_value.update = AsyncMock(return_value=mock_user)
            await mw(_make_handler(), _make_event(), data)

        assert data["is_admin"] is True

    async def test_admin_auto_promote_updates_role_in_db(self, mock_user: MagicMock) -> None:
        """ADMIN_IDS is single source of truth: auto-promote role in DB."""
        mock_user.id = 999
        mock_user.role = "user"
        mw = AuthMiddleware(admin_ids=[999])
        redis = _make_mock_redis()
        data: dict = {"event_from_user": _make_tg_user(999), "db": MagicMock(), "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            repo_cls.return_value.get_or_create = AsyncMock(return_value=(mock_user, False))
            repo_cls.return_value.update = AsyncMock(return_value=mock_user)
            await mw(_make_handler(), _make_event(), data)
            repo_cls.return_value.update.assert_called_once()

        assert data["user"].role == "admin"

    async def test_admin_no_promote_when_already_admin(self, mock_user: MagicMock) -> None:
        """Skip DB update if role is already admin."""
        mock_user.id = 999
        mock_user.role = "admin"
        mw = AuthMiddleware(admin_ids=[999])
        redis = _make_mock_redis()
        data: dict = {"event_from_user": _make_tg_user(999), "db": MagicMock(), "redis": redis}

        with patch("bot.middlewares.auth.UsersRepository") as repo_cls:
            repo_cls.return_value.get_or_create = AsyncMock(return_value=(mock_user, False))
            repo_cls.return_value.update = AsyncMock()
            await mw(_make_handler(), _make_event(), data)
            repo_cls.return_value.update.assert_not_called()

    async def test_no_user_passes_through(self) -> None:
        mw = AuthMiddleware(admin_ids=[999])
        handler = _make_handler()
        data: dict = {}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        assert "user" not in data


# === ThrottlingMiddleware ===


class TestThrottlingMiddleware:
    @pytest.fixture
    def redis(self) -> AsyncMock:
        mock = AsyncMock()
        mock.incr = AsyncMock(return_value=1)
        mock.expire = AsyncMock(return_value=True)
        return mock

    async def test_allows_under_limit(self, redis: AsyncMock) -> None:
        redis.incr.return_value = 5
        mw = ThrottlingMiddleware(redis, rate_limit=30, window=60)
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        handler.assert_called_once()

    async def test_allows_at_exact_limit(self, redis: AsyncMock) -> None:
        redis.incr.return_value = 30
        mw = ThrottlingMiddleware(redis, rate_limit=30, window=60)
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        handler.assert_called_once()

    async def test_drops_over_limit(self, redis: AsyncMock) -> None:
        redis.incr.return_value = 31
        mw = ThrottlingMiddleware(redis, rate_limit=30, window=60)
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        result = await mw(handler, _make_event(), data)

        assert result is None
        handler.assert_not_called()

    async def test_sets_expire_on_first_hit(self, redis: AsyncMock) -> None:
        redis.incr.return_value = 1
        mw = ThrottlingMiddleware(redis, rate_limit=30, window=60)
        data: dict = {"event_from_user": _make_tg_user()}

        await mw(_make_handler(), _make_event(), data)

        redis.expire.assert_called_once()

    async def test_expire_called_on_every_hit(self, redis: AsyncMock) -> None:
        """EXPIRE is always called (not just count==1) to prevent orphaned keys."""
        redis.incr.return_value = 5
        mw = ThrottlingMiddleware(redis, rate_limit=30, window=60)
        data: dict = {"event_from_user": _make_tg_user()}

        await mw(_make_handler(), _make_event(), data)

        redis.expire.assert_called_once()

    async def test_no_user_passes_through(self, redis: AsyncMock) -> None:
        mw = ThrottlingMiddleware(redis)
        handler = _make_handler()
        data: dict = {}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        redis.incr.assert_not_called()

    async def test_callback_query_uses_separate_counter(self, redis: AsyncMock) -> None:
        """Callback queries use 'callback' key, not 'message'."""
        from aiogram.types import CallbackQuery

        redis.incr.return_value = 1
        mw = ThrottlingMiddleware(redis)
        cb = MagicMock(spec=CallbackQuery)
        data: dict = {"event_from_user": _make_tg_user()}

        await mw(_make_handler(), cb, data)

        key_arg = redis.incr.call_args[0][0]
        assert ":callback" in key_arg
        assert ":message" not in key_arg

    async def test_callback_query_allows_up_to_60(self, redis: AsyncMock) -> None:
        """Callback queries have a higher limit (60/min) than messages (30/min)."""
        from aiogram.types import CallbackQuery

        redis.incr.return_value = 60
        mw = ThrottlingMiddleware(redis)
        cb = MagicMock(spec=CallbackQuery)
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        result = await mw(handler, cb, data)

        assert result == "handler_result"
        handler.assert_called_once()

    async def test_callback_query_drops_over_60(self, redis: AsyncMock) -> None:
        """Callback queries are dropped when exceeding 60/min."""
        from aiogram.types import CallbackQuery

        redis.incr.return_value = 61
        mw = ThrottlingMiddleware(redis)
        cb = MagicMock(spec=CallbackQuery)
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        result = await mw(handler, cb, data)

        assert result is None
        handler.assert_not_called()

    async def test_message_does_not_affect_callback_budget(self, redis: AsyncMock) -> None:
        """Message and callback have independent counters."""
        redis.incr.return_value = 1
        mw = ThrottlingMiddleware(redis)
        data: dict = {"event_from_user": _make_tg_user()}

        # First call with message event
        await mw(_make_handler(), _make_event(), data)
        msg_key = redis.incr.call_args[0][0]

        # Second call with callback event
        from aiogram.types import CallbackQuery

        cb = MagicMock(spec=CallbackQuery)
        await mw(_make_handler(), cb, data)
        cb_key = redis.incr.call_args[0][0]

        assert msg_key != cb_key


# === FSMInactivityMiddleware ===


class TestFSMInactivityMiddleware:
    @pytest.fixture
    def state(self) -> AsyncMock:
        s = AsyncMock()
        s.get_state = AsyncMock(return_value="SomeState:step")
        s.get_data = AsyncMock(return_value={"last_update_time": time.time()})
        s.update_data = AsyncMock()
        s.clear = AsyncMock()
        return s

    async def test_updates_timestamp_when_active(self, state: AsyncMock) -> None:
        state.get_data.return_value = {"last_update_time": time.time()}
        mw = FSMInactivityMiddleware(inactivity_timeout=1800)
        handler = _make_handler()
        data: dict = {"state": state, "event_from_user": _make_tg_user()}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        state.update_data.assert_called_once()

    async def test_clears_state_on_timeout(self, state: AsyncMock) -> None:
        state.get_data.return_value = {"last_update_time": time.time() - 2000}
        mw = FSMInactivityMiddleware(inactivity_timeout=1800)
        handler = _make_handler()
        event = MagicMock(spec=[])  # no answer method
        data: dict = {"state": state, "event_from_user": _make_tg_user()}

        result = await mw(handler, event, data)

        assert result is None
        state.clear.assert_called_once()
        handler.assert_not_called()

    async def test_no_state_passes_through(self) -> None:
        mw = FSMInactivityMiddleware()
        handler = _make_handler()
        data: dict = {}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"

    async def test_no_current_state_passes_through(self, state: AsyncMock) -> None:
        state.get_state.return_value = None
        mw = FSMInactivityMiddleware()
        handler = _make_handler()
        data: dict = {"state": state}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        state.get_data.assert_not_called()

    async def test_no_last_update_time_passes_through(self, state: AsyncMock) -> None:
        state.get_data.return_value = {}
        mw = FSMInactivityMiddleware(inactivity_timeout=1800)
        handler = _make_handler()
        data: dict = {"state": state, "event_from_user": _make_tg_user()}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"
        state.update_data.assert_called_once()


# === LoggingMiddleware ===


class TestLoggingMiddleware:
    async def test_sets_correlation_id(self) -> None:
        mw = LoggingMiddleware()
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        await mw(handler, _make_event(), data)

        assert "correlation_id" in data
        assert len(data["correlation_id"]) == 36  # UUID4 format

    async def test_returns_handler_result(self) -> None:
        mw = LoggingMiddleware()
        handler = _make_handler()
        data: dict = {}

        result = await mw(handler, _make_event(), data)

        assert result == "handler_result"

    async def test_logs_on_success(self) -> None:
        mw = LoggingMiddleware()
        handler = _make_handler()
        data: dict = {"event_from_user": _make_tg_user()}

        with patch("bot.middlewares.logging.log") as mock_log:
            await mw(handler, _make_event(), data)
            mock_log.info.assert_called_once()
            call_kwargs = mock_log.info.call_args[1]
            assert "correlation_id" in call_kwargs
            assert "latency_ms" in call_kwargs
            assert call_kwargs["user_id"] == 123

    async def test_logs_on_error(self) -> None:
        mw = LoggingMiddleware()
        handler = AsyncMock(side_effect=ValueError("boom"))
        data: dict = {"event_from_user": _make_tg_user()}

        with patch("bot.middlewares.logging.log") as mock_log, pytest.raises(ValueError, match="boom"):
            await mw(handler, _make_event(), data)

        mock_log.error.assert_called_once()

    async def test_no_user_still_works(self) -> None:
        mw = LoggingMiddleware()
        handler = _make_handler()
        data: dict = {}

        with patch("bot.middlewares.logging.log") as mock_log:
            await mw(handler, _make_event(), data)
            assert mock_log.info.call_args[1]["user_id"] is None
