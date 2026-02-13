"""Shared fixtures for routers/platforms/ tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from db.models import PlatformConnection, Project, User


@pytest.fixture
def user() -> User:
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
def project(user: User) -> Project:
    return Project(
        id=1,
        user_id=user.id,
        name="Test Project",
        company_name="Test Co",
        specialization="Testing stuff",
    )


@pytest.fixture
def connection(project: Project) -> PlatformConnection:
    return PlatformConnection(
        id=10,
        project_id=project.id,
        platform_type="wordpress",
        identifier="example.com",
        status="active",
        credentials={"url": "https://example.com", "login": "admin", "app_password": "xxxx"},
    )


@pytest.fixture
def mock_callback() -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


@pytest.fixture
def mock_state() -> AsyncMock:
    state = AsyncMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.get_state = AsyncMock(return_value=None)
    return state


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()
