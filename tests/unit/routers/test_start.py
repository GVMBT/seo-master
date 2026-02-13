"""Tests for routers/start.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import User
from routers.start import (
    btn_cancel,
    btn_help,
    btn_projects,
    btn_settings,
    btn_stub,
    cb_main_menu,
    cb_stub,
    cmd_cancel,
    cmd_help,
    cmd_start,
    cmd_start_deep_link,
    fsm_non_text_guard,
)


class TestCmdStart:
    @pytest.mark.asyncio
    async def test_new_user_sees_welcome_message(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User
    ) -> None:
        await cmd_start(mock_message, mock_state, user, is_new_user=True)
        mock_state.clear.assert_awaited_once()
        mock_message.answer.assert_awaited_once()
        text = mock_message.answer.call_args.args[0]
        assert "1500 токенов" in text
        assert "Добро пожаловать в SEO Master Bot!" in text

    @pytest.mark.asyncio
    async def test_returning_user_sees_balance(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User
    ) -> None:
        await cmd_start(mock_message, mock_state, user, is_new_user=False)
        mock_state.clear.assert_awaited_once()
        text = mock_message.answer.call_args.args[0]
        assert "С возвращением!" in text  # noqa: RUF001
        assert str(user.balance) in text

    @pytest.mark.asyncio
    async def test_admin_gets_admin_button(
        self, mock_message: MagicMock, mock_state: AsyncMock, admin_user: User
    ) -> None:
        await cmd_start(mock_message, mock_state, admin_user)
        kb = mock_message.answer.call_args.kwargs["reply_markup"]
        buttons = [btn.text for row in kb.keyboard for btn in row]
        assert "АДМИНКА" in buttons


class TestCmdStartDeepLink:
    @pytest.mark.asyncio
    async def test_referral_sets_referrer_id_when_referrer_exists(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        """Referrer must exist in DB (P4.2) before setting referrer_id."""
        user.referrer_id = None
        mock_message.text = "/start ref_555"
        referrer = User(id=555, balance=1500, role="user")
        with patch("routers.start.UsersRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=referrer)
            repo_cls.return_value.update = AsyncMock(return_value=user)
            await cmd_start_deep_link(
                mock_message, mock_state, user, mock_db, mock_redis, mock_http_client
            )
            repo_cls.return_value.get_by_id.assert_awaited_once_with(555)
            repo_cls.return_value.update.assert_awaited_once()
            update_arg = repo_cls.return_value.update.call_args.args[1]
            assert update_arg.referrer_id == 555

    @pytest.mark.asyncio
    async def test_referral_rejected_when_referrer_not_found(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        """Referrer that doesn't exist should not be set (P4.2)."""
        user.referrer_id = None
        mock_message.text = "/start ref_555"
        with patch("routers.start.UsersRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
            repo_cls.return_value.update = AsyncMock()
            await cmd_start_deep_link(
                mock_message, mock_state, user, mock_db, mock_redis, mock_http_client
            )
            repo_cls.return_value.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_self_referral(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        user.referrer_id = None
        mock_message.text = f"/start ref_{user.id}"
        with patch("routers.start.UsersRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=user)
            repo_cls.return_value.update = AsyncMock()
            await cmd_start_deep_link(
                mock_message, mock_state, user, mock_db, mock_redis, mock_http_client
            )
            repo_cls.return_value.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_existing_referrer_not_overwritten(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        user.referrer_id = 111  # already has referrer
        mock_message.text = "/start ref_555"
        referrer = User(id=555, balance=1500, role="user")
        with patch("routers.start.UsersRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=referrer)
            repo_cls.return_value.update = AsyncMock()
            await cmd_start_deep_link(
                mock_message, mock_state, user, mock_db, mock_redis, mock_http_client
            )
            repo_cls.return_value.update.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_new_user_with_deep_link_sees_welcome(
        self,
        mock_message: MagicMock,
        mock_state: AsyncMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
        mock_http_client: MagicMock,
    ) -> None:
        mock_message.text = "/start ref_555"
        referrer = User(id=555, balance=1500, role="user")
        with patch("routers.start.UsersRepository") as repo_cls:
            repo_cls.return_value.get_by_id = AsyncMock(return_value=referrer)
            repo_cls.return_value.update = AsyncMock(return_value=user)
            await cmd_start_deep_link(
                mock_message, mock_state, user, mock_db, mock_redis, mock_http_client,
                is_new_user=True,
            )
            text = mock_message.answer.call_args.args[0]
            assert "Добро пожаловать в SEO Master Bot!" in text


class TestCmdCancel:
    @pytest.mark.asyncio
    async def test_clears_state_and_shows_menu(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User
    ) -> None:
        await cmd_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_awaited_once()
        assert "отменено" in mock_message.answer.call_args.args[0].lower()


class TestBtnCancel:
    @pytest.mark.asyncio
    async def test_clears_when_in_fsm(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User
    ) -> None:
        mock_state.get_state.return_value = "SomeState:some_step"
        await btn_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_action_when_no_state(
        self, mock_message: MagicMock, mock_state: AsyncMock, user: User
    ) -> None:
        mock_state.get_state.return_value = None
        await btn_cancel(mock_message, mock_state, user)
        mock_state.clear.assert_not_awaited()


class TestCmdHelp:
    @pytest.mark.asyncio
    async def test_sends_help_text(self, mock_message: MagicMock) -> None:
        await cmd_help(mock_message)
        mock_message.answer.assert_awaited_once()
        assert "/start" in mock_message.answer.call_args.args[0]


class TestCbMainMenu:
    @pytest.mark.asyncio
    async def test_edits_message_and_clears_fsm(
        self, mock_callback: MagicMock, mock_state: AsyncMock, user: User
    ) -> None:
        await cb_main_menu(mock_callback, mock_state, user)
        mock_state.clear.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        # Restores reply keyboard
        mock_callback.message.answer.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()


class TestBtnProjects:
    @pytest.mark.asyncio
    async def test_shows_projects(
        self, mock_message: MagicMock, user: User, mock_db: MagicMock
    ) -> None:
        with patch("db.repositories.projects.ProjectsRepository") as repo_cls:
            repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            await btn_projects(mock_message, user, mock_db)
            mock_message.answer.assert_awaited_once()


class TestBtnSettings:
    @pytest.mark.asyncio
    async def test_shows_settings(self, mock_message: MagicMock) -> None:
        await btn_settings(mock_message)
        mock_message.answer.assert_awaited_once()


class TestBtnHelp:
    @pytest.mark.asyncio
    async def test_delegates_to_cmd_help(self, mock_message: MagicMock) -> None:
        await btn_help(mock_message)
        mock_message.answer.assert_awaited_once()


class TestBtnStub:
    @pytest.mark.asyncio
    async def test_shows_in_development(self, mock_message: MagicMock) -> None:
        await btn_stub(mock_message)
        assert "разработке" in mock_message.answer.call_args.args[0].lower()


class TestFsmNonTextGuard:
    @pytest.mark.asyncio
    async def test_rejects_non_text_during_fsm(
        self, mock_message: MagicMock
    ) -> None:
        """StateFilter("*") ensures this handler only fires when FSM is active.

        The handler itself simply sends the error message — state filtering is
        handled by aiogram's dispatcher (not tested here).
        """
        await fsm_non_text_guard(mock_message)
        mock_message.answer.assert_awaited_once()
        assert "текстовое" in mock_message.answer.call_args.args[0].lower()


class TestCbStub:
    @pytest.mark.asyncio
    async def test_shows_in_development(self, mock_callback: MagicMock) -> None:
        await cb_stub(mock_callback)
        mock_callback.answer.assert_awaited_once()
        assert mock_callback.answer.call_args.kwargs.get("show_alert") is True
