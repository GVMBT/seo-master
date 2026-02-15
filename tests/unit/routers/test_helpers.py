"""Tests for routers/_helpers.py — shared callback guards."""

from unittest.mock import AsyncMock, MagicMock

from aiogram.types import Message

from routers._helpers import guard_callback_message


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

    async def test_returns_none_for_non_message_type(self) -> None:
        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock()  # Not spec=Message
        result = await guard_callback_message(callback)
        assert result is None
        callback.answer.assert_awaited_once()
