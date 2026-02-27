"""Tests for bot/helpers.py — safe_message, get_owned_project, get_owned_category."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import InaccessibleMessage, Message

from bot.helpers import get_owned_category, get_owned_project, safe_message

# ---------------------------------------------------------------------------
# safe_message tests
# ---------------------------------------------------------------------------


class TestSafeMessage:
    def test_returns_message_when_accessible(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock(spec=Message)
        result = safe_message(callback)
        assert result is callback.message

    def test_returns_none_when_no_message(self) -> None:
        callback = MagicMock()
        callback.message = None
        result = safe_message(callback)
        assert result is None

    def test_returns_none_when_inaccessible(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        result = safe_message(callback)
        assert result is None


# ---------------------------------------------------------------------------
# get_owned_project tests
# ---------------------------------------------------------------------------


class TestGetOwnedProject:
    @pytest.fixture
    def mock_db(self) -> MagicMock:
        return MagicMock()

    async def test_returns_project_when_owned(self, mock_db: MagicMock) -> None:
        project = MagicMock()
        project.user_id = 42

        with patch("bot.helpers.ProjectsRepository") as MockRepo:
            repo_instance = MockRepo.return_value
            repo_instance.get_by_id = AsyncMock(return_value=project)

            result = await get_owned_project(mock_db, 1, 42)
            assert result is project
            repo_instance.get_by_id.assert_awaited_once_with(1)

    async def test_returns_none_when_not_found(self, mock_db: MagicMock) -> None:
        with patch("bot.helpers.ProjectsRepository") as MockRepo:
            repo_instance = MockRepo.return_value
            repo_instance.get_by_id = AsyncMock(return_value=None)

            result = await get_owned_project(mock_db, 1, 42)
            assert result is None

    async def test_returns_none_when_not_owned(self, mock_db: MagicMock) -> None:
        project = MagicMock()
        project.user_id = 99  # different user

        with patch("bot.helpers.ProjectsRepository") as MockRepo:
            repo_instance = MockRepo.return_value
            repo_instance.get_by_id = AsyncMock(return_value=project)

            result = await get_owned_project(mock_db, 1, 42)
            assert result is None


# ---------------------------------------------------------------------------
# get_owned_category tests
# ---------------------------------------------------------------------------


class TestGetOwnedCategory:
    @pytest.fixture
    def mock_db(self) -> MagicMock:
        return MagicMock()

    async def test_returns_category_when_owned(self, mock_db: MagicMock) -> None:
        category = MagicMock()
        category.project_id = 10
        project = MagicMock()
        project.user_id = 42

        with (
            patch("bot.helpers.CategoriesRepository") as MockCatsRepo,
            patch("bot.helpers.ProjectsRepository") as MockProjRepo,
        ):
            MockCatsRepo.return_value.get_by_id = AsyncMock(return_value=category)
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=project)

            result = await get_owned_category(mock_db, 5, 42)
            assert result is category

    async def test_returns_none_when_category_not_found(self, mock_db: MagicMock) -> None:
        with patch("bot.helpers.CategoriesRepository") as MockCatsRepo:
            MockCatsRepo.return_value.get_by_id = AsyncMock(return_value=None)

            result = await get_owned_category(mock_db, 5, 42)
            assert result is None

    async def test_returns_none_when_project_not_found(self, mock_db: MagicMock) -> None:
        category = MagicMock()
        category.project_id = 10

        with (
            patch("bot.helpers.CategoriesRepository") as MockCatsRepo,
            patch("bot.helpers.ProjectsRepository") as MockProjRepo,
        ):
            MockCatsRepo.return_value.get_by_id = AsyncMock(return_value=category)
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=None)

            result = await get_owned_category(mock_db, 5, 42)
            assert result is None

    async def test_returns_none_when_not_owned(self, mock_db: MagicMock) -> None:
        category = MagicMock()
        category.project_id = 10
        project = MagicMock()
        project.user_id = 99  # different user

        with (
            patch("bot.helpers.CategoriesRepository") as MockCatsRepo,
            patch("bot.helpers.ProjectsRepository") as MockProjRepo,
        ):
            MockCatsRepo.return_value.get_by_id = AsyncMock(return_value=category)
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=project)

            result = await get_owned_category(mock_db, 5, 42)
            assert result is None
