"""Tests for routers/help.py — built-in help system (F46)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import Message

from routers.help import (
    _HELP_CATEGORY,
    _HELP_CONNECT,
    _HELP_MAIN,
    _HELP_PROJECT,
    _HELP_PUBLISH,
    cb_help_category,
    cb_help_connect,
    cb_help_main,
    cb_help_project,
    cb_help_publish,
)


@pytest.fixture
def mock_callback() -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    return cb


class TestCbHelpMain:
    async def test_shows_main_help(self, mock_callback: MagicMock) -> None:
        await cb_help_main(mock_callback)
        mock_callback.message.edit_text.assert_called_once()
        call_args = mock_callback.message.edit_text.call_args
        assert _HELP_MAIN in call_args[0][0]

    async def test_guard_no_message(self) -> None:
        cb = MagicMock()
        cb.answer = AsyncMock()
        cb.message = None
        await cb_help_main(cb)
        cb.answer.assert_called_once()


class TestCbHelpConnect:
    async def test_shows_connect_help(self, mock_callback: MagicMock) -> None:
        await cb_help_connect(mock_callback)
        call_args = mock_callback.message.edit_text.call_args
        assert _HELP_CONNECT in call_args[0][0]

    async def test_answers_callback(self, mock_callback: MagicMock) -> None:
        await cb_help_connect(mock_callback)
        mock_callback.answer.assert_called_once()


class TestCbHelpProject:
    async def test_shows_project_help(self, mock_callback: MagicMock) -> None:
        await cb_help_project(mock_callback)
        call_args = mock_callback.message.edit_text.call_args
        assert _HELP_PROJECT in call_args[0][0]


class TestCbHelpCategory:
    async def test_shows_category_help(self, mock_callback: MagicMock) -> None:
        await cb_help_category(mock_callback)
        call_args = mock_callback.message.edit_text.call_args
        assert _HELP_CATEGORY in call_args[0][0]


class TestCbHelpPublish:
    async def test_shows_publish_help(self, mock_callback: MagicMock) -> None:
        await cb_help_publish(mock_callback)
        call_args = mock_callback.message.edit_text.call_args
        assert _HELP_PUBLISH in call_args[0][0]


class TestHelpTextsContent:
    def test_connect_mentions_wordpress(self) -> None:
        assert "WordPress" in _HELP_CONNECT

    def test_connect_mentions_telegram(self) -> None:
        assert "Telegram" in _HELP_CONNECT

    def test_publish_mentions_write_article(self) -> None:
        assert "Написать статью" in _HELP_PUBLISH

    def test_category_mentions_keywords(self) -> None:
        assert "Ключевые фразы" in _HELP_CATEGORY
