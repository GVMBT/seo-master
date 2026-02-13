"""Shared fixtures for router tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from db.models import Category, Project, User


@pytest.fixture
def user() -> User:
    """Default test user."""
    return User(
        id=123456789,
        username="testuser",
        first_name="Test",
        last_name="User",
        balance=1500,
        role="user",
        notify_publications=True,
        notify_balance=True,
        notify_news=True,
    )


@pytest.fixture
def admin_user() -> User:
    """Admin test user."""
    return User(
        id=999999999,
        username="admin",
        first_name="Admin",
        role="admin",
        balance=99999,
        notify_publications=True,
        notify_balance=True,
        notify_news=True,
    )


@pytest.fixture
def project(user: User) -> Project:
    """Default test project."""
    return Project(
        id=1,
        user_id=user.id,
        name="Test Project",
        company_name="Test Co",
        specialization="Testing stuff",
    )


@pytest.fixture
def category(project: Project) -> Category:
    """Default test category."""
    return Category(id=10, project_id=project.id, name="Test Category")


@pytest.fixture
def mock_message() -> MagicMock:
    """Mock Aiogram Message."""
    msg = MagicMock()
    msg.answer = AsyncMock()
    msg.text = ""
    return msg


@pytest.fixture
def mock_callback() -> MagicMock:
    """Mock Aiogram CallbackQuery with message that passes isinstance(Message) check."""
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


@pytest.fixture
def mock_state() -> AsyncMock:
    """Mock FSMContext."""
    state = AsyncMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.get_state = AsyncMock(return_value=None)
    return state


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock database client."""
    return MagicMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock RedisClient."""
    redis = MagicMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock()
    redis.delete = AsyncMock()
    return redis


@pytest.fixture
def mock_http_client() -> MagicMock:
    """Mock httpx.AsyncClient."""
    client = MagicMock()
    client.get = AsyncMock()
    client.post = AsyncMock()
    return client
