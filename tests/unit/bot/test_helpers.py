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

        with patch("bot.helpers.ProjectService") as MockSvc:
            MockSvc.return_value.get_owned_project = AsyncMock(return_value=project)

            result = await get_owned_project(mock_db, 1, 42)
            assert result is project
            MockSvc.return_value.get_owned_project.assert_awaited_once_with(1, 42)

    async def test_returns_none_when_not_found_or_not_owned(self, mock_db: MagicMock) -> None:
        """ProjectService returns None for missing or not-owned projects."""
        with patch("bot.helpers.ProjectService") as MockSvc:
            MockSvc.return_value.get_owned_project = AsyncMock(return_value=None)

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

        with patch("bot.helpers.CategoryService") as MockSvc:
            MockSvc.return_value.get_owned_category = AsyncMock(return_value=category)

            result = await get_owned_category(mock_db, 5, 42)
            assert result is category
            MockSvc.return_value.get_owned_category.assert_awaited_once_with(5, 42)

    async def test_returns_none_when_not_found_or_not_owned(self, mock_db: MagicMock) -> None:
        """CategoryService returns None for missing or not-owned categories."""
        with patch("bot.helpers.CategoryService") as MockSvc:
            MockSvc.return_value.get_owned_category = AsyncMock(return_value=None)

            result = await get_owned_category(mock_db, 5, 42)
            assert result is None
