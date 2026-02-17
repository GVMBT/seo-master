"""Shared mock fixtures for router handler tests.

Provides mock_callback, mock_message, mock_state, mock_db, user, project, category.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Chat, Message
from aiogram.types import User as TgUser

from db.models import Category, PlatformConnection, Project, User

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "id": 123456,
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User",
        "balance": 1500,
        "language": "ru",
        "role": "user",
    }
    defaults.update(overrides)
    return User(**defaults)


def make_project(**overrides: Any) -> Project:
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 123456,
        "name": "Test Project",
        "company_name": "TestCo",
        "specialization": "SEO",
    }
    defaults.update(overrides)
    return Project(**defaults)


def make_category(**overrides: Any) -> Category:
    defaults: dict[str, Any] = {
        "id": 10,
        "project_id": 1,
        "name": "Test Category",
    }
    defaults.update(overrides)
    return Category(**defaults)


def make_connection(**overrides: Any) -> PlatformConnection:
    defaults: dict[str, Any] = {
        "id": 5,
        "project_id": 1,
        "platform_type": "wordpress",
        "identifier": "blog.example.com",
        "credentials": {"url": "https://blog.example.com", "login": "admin", "password": "pass"},
        "status": "active",
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user() -> User:
    return make_user()


@pytest.fixture
def project() -> Project:
    return make_project()


@pytest.fixture
def category() -> Category:
    return make_category()


@pytest.fixture
def connection() -> PlatformConnection:
    return make_connection()


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock SupabaseClient."""
    return MagicMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock RedisClient with async methods."""
    redis = MagicMock()
    redis.set = AsyncMock(return_value="OK")
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def mock_state() -> MagicMock:
    """Mock FSMContext."""
    state = MagicMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


@pytest.fixture
def mock_message() -> MagicMock:
    """Mock Message with async methods."""
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.edit_text = AsyncMock()
    msg.text = ""
    msg.from_user = MagicMock(spec=TgUser)
    msg.from_user.id = 123456
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = 123456
    return msg


@pytest.fixture
def mock_callback(mock_message: MagicMock) -> MagicMock:
    """Mock CallbackQuery with message and async methods."""
    callback = MagicMock()
    callback.message = mock_message
    callback.answer = AsyncMock()
    callback.data = ""
    callback.from_user = MagicMock(spec=TgUser)
    callback.from_user.id = 123456
    return callback
