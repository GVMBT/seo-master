"""Tests for routers/settings.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import User
from routers.settings import cb_notifications, cb_settings_main, cb_toggle_notify


class TestCbSettingsMain:
    @pytest.mark.asyncio
    async def test_edits_message_with_menu(self, mock_callback: MagicMock) -> None:
        await cb_settings_main(mock_callback)
        mock_callback.message.edit_text.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()


class TestCbNotifications:
    @pytest.mark.asyncio
    async def test_shows_notification_toggles(
        self, mock_callback: MagicMock, user: User
    ) -> None:
        await cb_notifications(mock_callback, user)
        mock_callback.message.edit_text.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()


class TestCbToggleNotify:
    @pytest.mark.asyncio
    async def test_toggles_publications(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "settings:notify:publications"
        updated_user = User(**{**user.model_dump(), "notify_publications": False})
        with patch("routers.settings.UsersRepository") as repo_cls:
            repo_cls.return_value.update = AsyncMock(return_value=updated_user)
            await cb_toggle_notify(mock_callback, user, mock_db)
            repo_cls.return_value.update.assert_awaited_once()
            mock_callback.message.edit_reply_markup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_toggles_balance(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "settings:notify:balance"
        updated_user = User(**{**user.model_dump(), "notify_balance": False})
        with patch("routers.settings.UsersRepository") as repo_cls:
            repo_cls.return_value.update = AsyncMock(return_value=updated_user)
            await cb_toggle_notify(mock_callback, user, mock_db)
            repo_cls.return_value.update.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unknown_type_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "settings:notify:unknown"
        await cb_toggle_notify(mock_callback, user, mock_db)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_update_failure_shows_alert(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "settings:notify:publications"
        with patch("routers.settings.UsersRepository") as repo_cls:
            repo_cls.return_value.update = AsyncMock(return_value=None)
            await cb_toggle_notify(mock_callback, user, mock_db)
            mock_callback.answer.assert_awaited_once()
            assert mock_callback.answer.call_args.kwargs.get("show_alert") is True

    @pytest.mark.asyncio
    async def test_answer_contains_status_text(
        self, mock_callback: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_callback.data = "settings:notify:news"
        user.notify_news = True  # will toggle to False
        updated_user = User(**{**user.model_dump(), "notify_news": False})
        with patch("routers.settings.UsersRepository") as repo_cls:
            repo_cls.return_value.update = AsyncMock(return_value=updated_user)
            await cb_toggle_notify(mock_callback, user, mock_db)
            answer_text = mock_callback.answer.call_args.args[0]
            assert "выключены" in answer_text
