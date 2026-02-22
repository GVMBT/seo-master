"""Tests for bot/main.py — dispatcher creation, middleware chain, error handler, shutdown."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram import Dispatcher
from aiogram.types import ErrorEvent, Update

from bot.main import (
    _global_error_handler,
    _refund_active_generations,
    create_bot,
    create_dispatcher,
    create_http_client,
)


@pytest.fixture
def mock_settings() -> MagicMock:
    settings = MagicMock()
    settings.telegram_bot_token.get_secret_value.return_value = "123:ABC"
    settings.admin_ids = [999]
    settings.fsm_ttl_seconds = 86400
    settings.fsm_inactivity_timeout = 1800
    settings.railway_public_url = "https://test.up.railway.app"
    settings.telegram_webhook_secret.get_secret_value.return_value = "secret123"
    settings.supabase_url = "https://test.supabase.co"
    settings.supabase_key.get_secret_value.return_value = "key123"
    settings.upstash_redis_url = "https://test.upstash.io"
    settings.upstash_redis_token.get_secret_value.return_value = "token123"
    settings.sentry_dsn = ""
    return settings


@pytest.fixture
def db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def redis() -> AsyncMock:
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=None)
    mock.delete = AsyncMock(return_value=1)
    mock.incr = AsyncMock(return_value=1)
    mock.expire = AsyncMock(return_value=True)
    return mock


@pytest.fixture
def http_client() -> MagicMock:
    return MagicMock()


class TestCreateBot:
    def test_creates_bot_instance(self, mock_settings: MagicMock) -> None:
        bot = create_bot(mock_settings)
        assert bot is not None


class TestCreateHttpClient:
    def test_creates_httpx_client(self) -> None:
        import httpx

        client = create_http_client()
        assert isinstance(client, httpx.AsyncClient)


class TestCreateDispatcher:
    def test_returns_dispatcher(
        self, db: MagicMock, redis: AsyncMock, http_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        dp = create_dispatcher(db, redis, http_client, mock_settings)
        assert isinstance(dp, Dispatcher)

    def test_has_fsm_storage(
        self, db: MagicMock, redis: AsyncMock, http_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        dp = create_dispatcher(db, redis, http_client, mock_settings)
        from cache.fsm_storage import UpstashFSMStorage

        assert isinstance(dp.storage, UpstashFSMStorage)

    def test_outer_middleware_registered(
        self, db: MagicMock, redis: AsyncMock, http_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        dp = create_dispatcher(db, redis, http_client, mock_settings)
        assert len(dp.update.outer_middleware) > 0

    def test_inner_middleware_registered_on_message(
        self, db: MagicMock, redis: AsyncMock, http_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        dp = create_dispatcher(db, redis, http_client, mock_settings)
        # 4 inner middleware: Auth, Throttling, FSMInactivity, Logging
        assert len(dp.message.middleware) == 4

    def test_inner_middleware_registered_on_callback_query(
        self, db: MagicMock, redis: AsyncMock, http_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        dp = create_dispatcher(db, redis, http_client, mock_settings)
        assert len(dp.callback_query.middleware) == 4

    def test_error_handler_registered(
        self, db: MagicMock, redis: AsyncMock, http_client: MagicMock, mock_settings: MagicMock
    ) -> None:
        dp = create_dispatcher(db, redis, http_client, mock_settings)
        assert len(dp.errors.handlers) > 0


class TestGlobalErrorHandler:
    async def test_handles_generic_exception(self) -> None:
        update = MagicMock(spec=Update)
        update.message = AsyncMock()
        update.callback_query = None
        update.pre_checkout_query = None

        event = MagicMock(spec=ErrorEvent)
        event.exception = RuntimeError("test error")
        event.update = update

        with patch("bot.main.sentry_sdk"):
            result = await _global_error_handler(event)

        assert result is True
        update.message.answer.assert_called_once_with("Произошла ошибка. Попробуйте позже.")

    async def test_handles_app_error_with_custom_message(self) -> None:
        from bot.exceptions import InsufficientBalanceError

        update = MagicMock(spec=Update)
        update.message = AsyncMock()
        update.callback_query = None
        update.pre_checkout_query = None

        event = MagicMock(spec=ErrorEvent)
        event.exception = InsufficientBalanceError()
        event.update = update

        with patch("bot.main.sentry_sdk"):
            await _global_error_handler(event)

        update.message.answer.assert_called_once_with("Недостаточно токенов")

    async def test_handles_callback_query_error(self) -> None:
        update = MagicMock(spec=Update)
        update.message = None
        update.callback_query = AsyncMock()
        update.pre_checkout_query = None

        event = MagicMock(spec=ErrorEvent)
        event.exception = RuntimeError("test")
        event.update = update

        with patch("bot.main.sentry_sdk"):
            await _global_error_handler(event)

        update.callback_query.answer.assert_called_once()

    async def test_handles_pre_checkout_query_error(self) -> None:
        update = MagicMock(spec=Update)
        update.message = None
        update.callback_query = None
        update.pre_checkout_query = AsyncMock()

        event = MagicMock(spec=ErrorEvent)
        event.exception = RuntimeError("payment error")
        event.update = update

        with patch("bot.main.sentry_sdk"):
            result = await _global_error_handler(event)

        assert result is True
        update.pre_checkout_query.answer.assert_called_once()
        call_kwargs = update.pre_checkout_query.answer.call_args[1]
        assert call_kwargs["ok"] is False
        assert len(call_kwargs["error_message"]) <= 255

    async def test_handles_no_update(self) -> None:
        event = MagicMock(spec=ErrorEvent)
        event.exception = RuntimeError("test")
        event.update = None

        with patch("bot.main.sentry_sdk"):
            result = await _global_error_handler(event)
        assert result is True

    async def test_captures_sentry_exception(self) -> None:
        event = MagicMock(spec=ErrorEvent)
        event.exception = RuntimeError("sentry test")
        event.update = None

        with patch("bot.main.sentry_sdk") as mock_sentry:
            await _global_error_handler(event)
            mock_sentry.capture_exception.assert_called_once_with(event.exception)


class TestRefundActiveGenerations:
    """Tests for _refund_active_generations — shutdown refund guard."""

    @pytest.fixture
    def bot(self) -> AsyncMock:
        mock = AsyncMock()
        mock.send_message = AsyncMock()
        return mock

    @pytest.fixture
    def mock_db(self) -> MagicMock:
        return MagicMock()

    @pytest.fixture
    def mock_redis(self) -> AsyncMock:
        mock = AsyncMock()
        mock.scan_keys = AsyncMock(return_value=[])
        mock.get = AsyncMock(return_value=None)
        mock.delete = AsyncMock(return_value=1)
        return mock

    async def test_no_active_generations_does_nothing(
        self, bot: AsyncMock, mock_db: MagicMock, mock_redis: AsyncMock
    ) -> None:
        mock_redis.scan_keys.return_value = []

        with patch("bot.main.get_settings") as gs:
            gs.return_value = MagicMock(admin_ids=[999])
            await _refund_active_generations(bot, mock_db, mock_redis)

        bot.send_message.assert_not_called()

    async def test_refunds_active_generation(self, bot: AsyncMock, mock_db: MagicMock, mock_redis: AsyncMock) -> None:
        mock_redis.scan_keys.return_value = ["generation:active:12345"]
        mock_redis.get.return_value = json.dumps({"tokens": 260, "ts": 1700000000})

        mock_token_svc = AsyncMock()
        with (
            patch("bot.main.get_settings") as gs,
            patch("services.tokens.TokenService", return_value=mock_token_svc) as ts_cls,
        ):
            gs.return_value = MagicMock(admin_ids=[999])
            await _refund_active_generations(bot, mock_db, mock_redis)

        ts_cls.assert_called_once()
        mock_token_svc.refund.assert_awaited_once_with(
            user_id=12345,
            amount=260,
            reason="refund",
            description="Возврат: генерация прервана обновлением сервера",
        )
        bot.send_message.assert_awaited_once()
        msg_text = bot.send_message.call_args[0][1]
        assert "260" in msg_text
        mock_redis.delete.assert_awaited_once_with("generation:active:12345")

    async def test_skips_refund_for_admin(self, bot: AsyncMock, mock_db: MagicMock, mock_redis: AsyncMock) -> None:
        mock_redis.scan_keys.return_value = ["generation:active:999"]
        mock_redis.get.return_value = json.dumps({"tokens": 260, "ts": 1700000000})

        mock_token_svc = AsyncMock()
        with (
            patch("bot.main.get_settings") as gs,
            patch("services.tokens.TokenService", return_value=mock_token_svc),
        ):
            gs.return_value = MagicMock(admin_ids=[999])
            await _refund_active_generations(bot, mock_db, mock_redis)

        mock_token_svc.refund.assert_not_awaited()
        # Still notifies admin
        bot.send_message.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()

    async def test_scan_failure_does_not_crash(self, bot: AsyncMock, mock_db: MagicMock, mock_redis: AsyncMock) -> None:
        mock_redis.scan_keys.side_effect = ConnectionError("Redis down")

        with patch("bot.main.get_settings") as gs:
            gs.return_value = MagicMock(admin_ids=[999])
            await _refund_active_generations(bot, mock_db, mock_redis)

        bot.send_message.assert_not_called()

    async def test_notify_failure_does_not_prevent_refund(
        self, bot: AsyncMock, mock_db: MagicMock, mock_redis: AsyncMock
    ) -> None:
        mock_redis.scan_keys.return_value = ["generation:active:12345"]
        mock_redis.get.return_value = json.dumps({"tokens": 100, "ts": 1700000000})
        bot.send_message.side_effect = Exception("Telegram down")

        mock_token_svc = AsyncMock()
        with (
            patch("bot.main.get_settings") as gs,
            patch("services.tokens.TokenService", return_value=mock_token_svc),
        ):
            gs.return_value = MagicMock(admin_ids=[999])
            await _refund_active_generations(bot, mock_db, mock_redis)

        mock_token_svc.refund.assert_awaited_once()
        mock_redis.delete.assert_awaited_once()
