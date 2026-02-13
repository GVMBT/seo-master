"""Tests for routers/_helpers.py — shared callback guards and ID parsing."""

from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message

from routers._helpers import guard_callback_message, parse_callback_id, require_callback_message


class TestRequireCallbackMessage:
    def test_returns_message_when_valid(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock(spec=Message)
        result = require_callback_message(callback)
        assert result is callback.message

    def test_returns_none_when_inaccessible(self) -> None:
        callback = MagicMock()
        callback.message = None
        result = require_callback_message(callback)
        assert result is None

    def test_returns_none_when_inaccessible_message(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock()  # Not spec=Message
        # isinstance check fails for non-Message objects
        result = require_callback_message(callback)
        assert result is None


class TestGuardCallbackMessage:
    async def test_returns_message_when_valid(self) -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock(spec=Message)
        result = await guard_callback_message(callback)
        assert result is callback.message
        callback.answer.assert_not_awaited()

    async def test_answers_and_returns_none_when_inaccessible(self) -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = None
        result = await guard_callback_message(callback)
        assert result is None
        callback.answer.assert_awaited_once_with("Сообщение недоступно.", show_alert=True)


class TestParseCallbackId:
    def test_default_index(self) -> None:
        callback = MagicMock()
        callback.data = "project:42:card"
        assert parse_callback_id(callback) == 42

    def test_custom_index(self) -> None:
        callback = MagicMock()
        callback.data = "page:categories:5:2"
        assert parse_callback_id(callback, index=2) == 5
        assert parse_callback_id(callback, index=3) == 2
