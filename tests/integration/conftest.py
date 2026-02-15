"""Shared fixtures for integration tests.

Integration tests use Dispatcher.feed_update() to send real Updates
through the full middleware → filter → handler pipeline with mocked externals.
"""

from __future__ import annotations

import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    Update,
)
from aiogram.types import (
    User as TgUser,
)

from bot.middlewares import (
    AuthMiddleware,
    DBSessionMiddleware,
    FSMInactivityMiddleware,
    LoggingMiddleware,
    ThrottlingMiddleware,
)
from cache.fsm_storage import UpstashFSMStorage
from routers import setup_routers
from tests.unit.db.repositories.conftest import MockResponse, MockSupabaseClient

# Re-export for convenience in sub-conftest files
__all__ = [
    "MockRedisClient",
    "MockResponse",
    "MockSupabaseClient",
]

# ---- Sequence counter for unique update IDs ----
_update_seq = 0


def _next_update_id() -> int:
    global _update_seq
    _update_seq += 1
    return _update_seq


# ---------------------------------------------------------------------------
# In-memory Redis mock (deterministic, zero infra)
# ---------------------------------------------------------------------------

class MockRedisClient:
    """Async in-memory Redis that mimics cache.client.RedisClient interface.

    Supports: get, set (with ex/nx), delete, incr, decr, incrby, decrby,
    expire, exists, ttl, ping.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, float] = {}

    def _is_expired(self, key: str) -> bool:
        if key in self._ttls and time.monotonic() > self._ttls[key]:
            del self._store[key]
            del self._ttls[key]
            return True
        return False

    async def get(self, key: str) -> str | None:
        self._is_expired(key)
        return self._store.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ex: int | None = None,
        nx: bool = False,
    ) -> str | None:
        self._is_expired(key)
        if nx and key in self._store:
            return None
        self._store[key] = str(value)
        if ex is not None:
            self._ttls[key] = time.monotonic() + ex
        return "OK"

    async def delete(self, *keys: str) -> int:
        count = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                self._ttls.pop(k, None)
                count += 1
        return count

    async def incr(self, key: str) -> int:
        self._is_expired(key)
        val = int(self._store.get(key, "0")) + 1
        self._store[key] = str(val)
        return val

    async def decr(self, key: str) -> int:
        self._is_expired(key)
        val = int(self._store.get(key, "0")) - 1
        self._store[key] = str(val)
        return val

    async def incrby(self, key: str, amount: int) -> int:
        self._is_expired(key)
        val = int(self._store.get(key, "0")) + amount
        self._store[key] = str(val)
        return val

    async def decrby(self, key: str, amount: int) -> int:
        self._is_expired(key)
        val = int(self._store.get(key, "0")) - amount
        self._store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int) -> bool:
        if key in self._store:
            self._ttls[key] = time.monotonic() + seconds
            return True
        return False

    async def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self._store and not self._is_expired(k))

    async def ttl(self, key: str) -> int:
        if key not in self._store or self._is_expired(key):
            return -2
        if key not in self._ttls:
            return -1
        remaining = int(self._ttls[key] - time.monotonic())
        return max(remaining, 0)

    async def ping(self) -> bool:
        return True

    def clear(self) -> None:
        """Reset all stored data (call between tests)."""
        self._store.clear()
        self._ttls.clear()


# ---------------------------------------------------------------------------
# Default user data
# ---------------------------------------------------------------------------

DEFAULT_USER_ID = 123456789
DEFAULT_USER = {
    "id": DEFAULT_USER_ID,
    "username": "testuser",
    "first_name": "Test",
    "last_name": "User",
    "balance": 1500,
    "language": "ru",
    "role": "user",
    "referrer_id": None,
    "notify_publications": True,
    "notify_balance": True,
    "notify_news": True,
    "created_at": "2025-01-01T00:00:00Z",
    "last_activity": "2025-01-01T00:00:00Z",
}

ADMIN_ID = 999999999
ADMIN_USER = {
    **DEFAULT_USER,
    "id": ADMIN_ID,
    "username": "admin",
    "first_name": "Admin",
    "last_name": None,
    "role": "admin",
    "balance": 99999,
}


# ---------------------------------------------------------------------------
# Update factories (create real Aiogram Update objects)
# ---------------------------------------------------------------------------

def make_tg_user(
    user_id: int = DEFAULT_USER_ID,
    first_name: str = "Test",
    last_name: str | None = "User",
    username: str | None = "testuser",
) -> TgUser:
    """Create an Aiogram TgUser object."""
    return TgUser(
        id=user_id,
        is_bot=False,
        first_name=first_name,
        last_name=last_name,
        username=username,
    )


def make_chat(chat_id: int | None = None) -> Chat:
    """Create a private Chat for test messages."""
    return Chat(id=chat_id or DEFAULT_USER_ID, type="private")


def make_update_message(
    text: str,
    user_id: int = DEFAULT_USER_ID,
    chat_id: int | None = None,
    first_name: str = "Test",
    username: str | None = "testuser",
) -> Update:
    """Create an Update containing a text Message."""
    tg_user = make_tg_user(user_id=user_id, first_name=first_name, username=username)
    chat = make_chat(chat_id or user_id)
    msg = Message(
        message_id=_next_update_id(),
        date=int(time.time()),
        chat=chat,
        from_user=tg_user,
        text=text,
    )
    return Update(update_id=_next_update_id(), message=msg)


def make_update_callback(
    data: str,
    user_id: int = DEFAULT_USER_ID,
    message_text: str = "Previous message",
    first_name: str = "Test",
    username: str | None = "testuser",
) -> Update:
    """Create an Update containing a CallbackQuery with inline message."""
    tg_user = make_tg_user(user_id=user_id, first_name=first_name, username=username)
    chat = make_chat(user_id)
    msg = Message(
        message_id=_next_update_id(),
        date=int(time.time()),
        chat=chat,
        from_user=tg_user,
        text=message_text,
    )
    cb = CallbackQuery(
        id=str(_next_update_id()),
        chat_instance=str(user_id),
        from_user=tg_user,
        message=msg,
        data=data,
    )
    return Update(update_id=_next_update_id(), callback_query=cb)


def make_update_document(
    user_id: int = DEFAULT_USER_ID,
    file_name: str = "test.xlsx",
) -> Update:
    """Create an Update containing a document Message (for file upload FSMs)."""
    from aiogram.types import Document

    tg_user = make_tg_user(user_id=user_id)
    chat = make_chat(user_id)
    doc = Document(file_id="test_file_id_123", file_unique_id="unique_123", file_name=file_name)
    msg = Message(
        message_id=_next_update_id(),
        date=int(time.time()),
        chat=chat,
        from_user=tg_user,
        document=doc,
    )
    return Update(update_id=_next_update_id(), message=msg)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_redis() -> MockRedisClient:
    """In-memory Redis mock."""
    return MockRedisClient()


@pytest.fixture
def mock_db() -> MockSupabaseClient:
    """Reuse MockSupabaseClient from unit tests."""
    return MockSupabaseClient()


@pytest.fixture
def mock_bot() -> MagicMock:
    """Mock Bot with captured send_message / edit_message_text / answer_callback_query.

    Uses MagicMock(spec=Bot) so isinstance checks pass where needed.
    All Telegram API methods are AsyncMocks returning sensible defaults.
    """
    bot = MagicMock(spec=Bot)
    bot.id = 1234567890
    bot.token = "123:FAKE"

    # Core API methods
    bot.send_message = AsyncMock(return_value=MagicMock())
    bot.edit_message_text = AsyncMock(return_value=MagicMock())
    bot.edit_message_reply_markup = AsyncMock(return_value=MagicMock())
    bot.answer_callback_query = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)
    bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
    bot.set_webhook = AsyncMock(return_value=True)
    bot.session = MagicMock()
    bot.session.close = AsyncMock()

    return bot


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Mock httpx.AsyncClient."""
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    client.put = AsyncMock()
    client.delete = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def mock_settings() -> MagicMock:
    """Mock Settings with sensible defaults."""
    settings = MagicMock()
    settings.admin_id = ADMIN_ID
    settings.fsm_ttl_seconds = 86400
    settings.fsm_inactivity_timeout = 1800
    settings.telegram_bot_token = MagicMock()
    settings.telegram_bot_token.get_secret_value.return_value = "123:FAKE"
    settings.qstash_token = MagicMock()
    settings.qstash_token.get_secret_value.return_value = "qst_fake"
    settings.qstash_current_signing_key = MagicMock()
    settings.qstash_current_signing_key.get_secret_value.return_value = "sig_current_fake"
    settings.qstash_next_signing_key = MagicMock()
    settings.qstash_next_signing_key.get_secret_value.return_value = "sig_next_fake"
    settings.health_check_token = MagicMock()
    settings.health_check_token.get_secret_value.return_value = "health_token_secret"
    settings.railway_public_url = "https://test.railway.app"
    settings.openrouter_api_key = MagicMock()
    settings.openrouter_api_key.get_secret_value.return_value = "or_fake"
    settings.supabase_url = "https://fake.supabase.co"
    settings.supabase_key = MagicMock()
    settings.supabase_key.get_secret_value.return_value = "sb_fake"
    settings.railway_graceful_shutdown_timeout = 120
    return settings


@pytest.fixture
def mock_services() -> dict[str, MagicMock]:
    """All workflow_data services as mocks."""
    return {
        "ai_orchestrator": MagicMock(),
        "prompt_engine": MagicMock(),
        "rate_limiter": MagicMock(),
        "image_storage": MagicMock(),
        "stars_service": MagicMock(),
        "yookassa_service": MagicMock(),
        "firecrawl_client": MagicMock(),
        "serper_client": MagicMock(),
        "pagespeed_client": MagicMock(),
        "dataforseo_client": MagicMock(),
        "scheduler_service": MagicMock(),
    }


def _setup_db_for_auth(mock_db: MockSupabaseClient, user_data: dict[str, Any] | None = None) -> None:
    """Pre-configure DB mock for AuthMiddleware to find a user.

    AuthMiddleware hits users table to get_or_create user. This sets up
    the response so it returns the given user (or DEFAULT_USER).
    """
    data = user_data or DEFAULT_USER
    mock_db.set_response("users", MockResponse(data=data))


@pytest.fixture
def dispatcher(
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
    mock_http_client: MagicMock,
    mock_settings: MagicMock,
    mock_services: dict[str, MagicMock],
) -> Dispatcher:
    """Real Dispatcher with UpstashFSMStorage + full middleware chain + all routers.

    Mirrors bot/main.py create_dispatcher() but with mocked dependencies.
    """
    storage = UpstashFSMStorage(mock_redis, state_ttl=86400)
    dp = Dispatcher(storage=storage)

    # Outer middleware: inject DB, Redis, httpx
    dp.update.outer_middleware(DBSessionMiddleware(mock_db, mock_redis, mock_http_client))

    # Inner middleware on all event types (same as bot/main.py)
    for observer in (dp.message, dp.callback_query, dp.pre_checkout_query):
        observer.middleware(AuthMiddleware(ADMIN_ID))
        observer.middleware(ThrottlingMiddleware(mock_redis))
        observer.middleware(FSMInactivityMiddleware(1800))
        observer.middleware(LoggingMiddleware())

    # Include all real routers
    dp.include_router(setup_routers())

    # Inject service mocks into workflow_data (same as bot/main.py)
    for name, svc in mock_services.items():
        dp.workflow_data[name] = svc

    return dp


@pytest.fixture
def setup_user(mock_db: MockSupabaseClient, mock_redis: MockRedisClient) -> Any:
    """Helper to set up a user for AuthMiddleware.

    Returns a callable: setup_user(user_data=None) that configures
    both DB response and optionally pre-caches in Redis.
    """

    def _setup(
        user_data: dict[str, Any] | None = None,
        cache_in_redis: bool = True,
    ) -> dict[str, Any]:
        data = user_data or DEFAULT_USER
        _setup_db_for_auth(mock_db, data)

        if cache_in_redis:
            # Pre-cache user in Redis to skip DB call (faster tests)
            cache_key = f"user:{data['id']}"
            # Synchronously put into mock_redis store
            mock_redis._store[cache_key] = json.dumps(data, ensure_ascii=False, default=str)

        return data

    return _setup
