"""Tests for routers/publishing/pipeline/exit_protection.py.

Covers exit protection for Article Pipeline steps 4-7:
- Reply keyboard "Меню"/"Отмена" interception on protected states
- /cancel command interception on protected states
- Exit confirm — clear FSM, keep checkpoint
- Exit cancel — dismiss dialog, continue pipeline
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from routers.publishing.pipeline._common import ArticlePipelineFSM
from routers.publishing.pipeline.exit_protection import (
    exit_cancel,
    exit_confirm,
    exit_protection_cancel_cmd,
    exit_protection_reply,
)
from tests.unit.routers.conftest import make_user


# ---------------------------------------------------------------------------
# exit_protection_reply
# ---------------------------------------------------------------------------


async def test_exit_protection_reply_shows_confirm(mock_message: MagicMock) -> None:
    """Reply 'Меню' or 'Отмена' on protected state shows exit confirmation."""
    mock_message.text = "Меню"
    mock_message.answer = AsyncMock()

    await exit_protection_reply(mock_message)

    mock_message.answer.assert_called_once()
    text = mock_message.answer.call_args[0][0]
    assert "Прервать публикацию?" in text
    assert "24 часа" in text
    # Check that keyboard has exit_confirm and exit_cancel buttons
    kb = mock_message.answer.call_args[1]["reply_markup"]
    callbacks = [btn.callback_data for row in kb.inline_keyboard for btn in row]
    assert "pipeline:article:exit_confirm" in callbacks
    assert "pipeline:article:exit_cancel" in callbacks


async def test_exit_protection_reply_otmena(mock_message: MagicMock) -> None:
    """Reply 'Отмена' also triggers exit protection."""
    mock_message.text = "Отмена"
    mock_message.answer = AsyncMock()

    await exit_protection_reply(mock_message)

    mock_message.answer.assert_called_once()
    assert "Прервать публикацию?" in mock_message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# exit_protection_cancel_cmd
# ---------------------------------------------------------------------------


async def test_exit_protection_cancel_cmd(mock_message: MagicMock) -> None:
    """/cancel command on protected state shows exit confirmation."""
    mock_message.answer = AsyncMock()

    await exit_protection_cancel_cmd(mock_message)

    mock_message.answer.assert_called_once()
    assert "Прервать публикацию?" in mock_message.answer.call_args[0][0]


# ---------------------------------------------------------------------------
# exit_confirm
# ---------------------------------------------------------------------------


async def test_exit_confirm_clears_fsm_keeps_checkpoint(
    mock_callback: MagicMock,
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Exit confirm clears FSM but does NOT delete checkpoint."""
    user = make_user()

    await exit_confirm(mock_callback, mock_state, user, mock_redis)

    mock_state.clear.assert_called_once()
    # Checkpoint NOT deleted — user can resume from Dashboard
    mock_redis.delete.assert_not_called()
    mock_callback.message.edit_text.assert_called_once()
    assert "приостановлен" in mock_callback.message.edit_text.call_args[0][0]
    mock_callback.answer.assert_called_once()


async def test_exit_confirm_inaccessible_message(
    mock_state: MagicMock,
    mock_redis: MagicMock,
) -> None:
    """Exit confirm handles inaccessible message gracefully."""
    from aiogram.types import InaccessibleMessage

    user = make_user()
    callback = MagicMock()
    callback.message = MagicMock(spec=InaccessibleMessage)
    callback.answer = AsyncMock()

    await exit_confirm(callback, mock_state, user, mock_redis)

    mock_state.clear.assert_called_once()
    callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# exit_cancel
# ---------------------------------------------------------------------------


async def test_exit_cancel_deletes_dialog(mock_callback: MagicMock) -> None:
    """Exit cancel deletes the confirmation message."""
    mock_callback.message.delete = AsyncMock()

    await exit_cancel(mock_callback)

    mock_callback.message.delete.assert_called_once()
    mock_callback.answer.assert_called_once_with("Продолжаем!")


async def test_exit_cancel_handles_delete_failure(mock_callback: MagicMock) -> None:
    """Exit cancel handles delete failure gracefully."""
    from aiogram.exceptions import TelegramBadRequest

    mock_callback.message.delete = AsyncMock(
        side_effect=TelegramBadRequest(method=MagicMock(), message="message not found")
    )

    await exit_cancel(mock_callback)

    mock_callback.answer.assert_called_once_with("Продолжаем!")
