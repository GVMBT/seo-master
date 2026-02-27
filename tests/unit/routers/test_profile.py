"""Tests for routers/profile.py — account deletion handlers.

Covers: /delete_account command, confirm callback, cancel callback, inaccessible message.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import InaccessibleMessage

from db.models import User
from services.users import DeleteAccountResult

# ---------------------------------------------------------------------------
# Fixtures (reuse from conftest where possible)
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> User:  # type: ignore[no-untyped-def]
    defaults = {
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


# ---------------------------------------------------------------------------
# /delete_account command
# ---------------------------------------------------------------------------


class TestCmdDeleteAccount:
    @patch("routers.profile.delete_account_confirm_kb")
    async def test_shows_warning_message(
        self,
        mock_kb: MagicMock,
        mock_message: MagicMock,
    ) -> None:
        """Command shows warning text with confirmation keyboard."""
        from routers.profile import cmd_delete_account

        mock_kb.return_value = MagicMock()
        user = _make_user()

        await cmd_delete_account(mock_message, user)

        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args[0][0]
        assert "Удаление аккаунта" in text
        assert "необратимо" in text
        mock_kb.assert_called_once()


# ---------------------------------------------------------------------------
# account:delete:confirm
# ---------------------------------------------------------------------------


class TestConfirmDeleteAccount:
    @patch("routers.profile.get_settings")
    @patch("routers.profile.UsersService")
    async def test_successful_deletion(
        self,
        mock_svc_cls: MagicMock,
        mock_settings: MagicMock,
        mock_callback: MagicMock,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """On successful deletion, user sees success message."""
        from routers.profile import confirm_delete_account

        mock_settings.return_value.admin_ids = []

        result = DeleteAccountResult(success=True)
        mock_svc = MagicMock()
        mock_svc.delete_account = AsyncMock(return_value=result)
        mock_svc_cls.return_value = mock_svc

        user = _make_user()
        mock_scheduler = MagicMock()

        await confirm_delete_account(mock_callback, user, mock_db, mock_redis, mock_scheduler)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "удалены" in text
        assert "/start" in text
        mock_callback.answer.assert_awaited_once()

    @patch("routers.profile.get_settings")
    @patch("routers.profile.UsersService")
    async def test_failed_deletion(
        self,
        mock_svc_cls: MagicMock,
        mock_settings: MagicMock,
        mock_callback: MagicMock,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """On failed deletion, user sees error message."""
        from routers.profile import confirm_delete_account

        mock_settings.return_value.admin_ids = []

        result = DeleteAccountResult(success=False, errors=["delete_user_row"])
        mock_svc = MagicMock()
        mock_svc.delete_account = AsyncMock(return_value=result)
        mock_svc_cls.return_value = mock_svc

        user = _make_user()
        mock_scheduler = MagicMock()

        await confirm_delete_account(mock_callback, user, mock_db, mock_redis, mock_scheduler)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "ошибка" in text.lower()

    async def test_inaccessible_message_returns(
        self,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Handler returns early for inaccessible message."""
        from routers.profile import confirm_delete_account

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()

        user = _make_user()
        mock_scheduler = MagicMock()

        await confirm_delete_account(callback, user, mock_db, mock_redis, mock_scheduler)

        callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# account:delete:cancel
# ---------------------------------------------------------------------------


class TestCancelDeleteAccount:
    async def test_cancel_shows_message(
        self,
        mock_callback: MagicMock,
    ) -> None:
        """Cancel shows cancellation message."""
        from routers.profile import cancel_delete_account

        await cancel_delete_account(mock_callback)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "отменено" in text.lower()
        mock_callback.answer.assert_awaited_once()

    async def test_cancel_inaccessible_message(self) -> None:
        """Cancel returns early for inaccessible message."""
        from routers.profile import cancel_delete_account

        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()

        await cancel_delete_account(callback)

        callback.answer.assert_awaited_once()
