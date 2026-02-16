"""Tests for routers/admin/broadcast.py — admin broadcast messaging (F20)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from db.models import User
from routers.admin.broadcast import (
    _AUDIENCE_LABELS,
    BroadcastFSM,
    cb_broadcast_audience,
    cb_broadcast_confirm,
    cb_broadcast_start,
    fsm_broadcast_text,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def admin_user() -> User:
    return User(
        id=999,
        username="admin",
        first_name="Admin",
        role="admin",
        balance=99999,
        notify_publications=True,
        notify_balance=True,
        notify_news=True,
    )


@pytest.fixture
def regular_user() -> User:
    return User(
        id=123,
        username="user",
        first_name="User",
        role="user",
        balance=100,
        notify_publications=True,
        notify_balance=True,
        notify_news=True,
    )


@pytest.fixture
def mock_callback() -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    cb.message = MagicMock(spec=Message)
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.bot = MagicMock()
    cb.bot.send_message = AsyncMock()
    return cb


# ---------------------------------------------------------------------------
# cb_broadcast_start
# ---------------------------------------------------------------------------


class TestCbBroadcastStart:
    async def test_admin_sees_audience_selection(self, mock_callback: MagicMock, admin_user: User) -> None:
        await cb_broadcast_start(mock_callback, admin_user)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "аудиторию" in text.lower()

    async def test_non_admin_rejected(self, mock_callback: MagicMock, regular_user: User) -> None:
        await cb_broadcast_start(mock_callback, regular_user)

        mock_callback.answer.assert_called_with("Нет доступа.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_broadcast_audience
# ---------------------------------------------------------------------------


class TestCbBroadcastAudience:
    @patch("routers.admin.broadcast.UsersRepository")
    async def test_sets_fsm_text_state(
        self,
        mock_users_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "admin:bc:all"
        mock_users_cls.return_value.get_ids_by_audience = AsyncMock(return_value=[1, 2, 3])

        await cb_broadcast_audience(mock_callback, mock_state, admin_user, mock_db)

        mock_state.set_state.assert_called_with(BroadcastFSM.text)
        update_kwargs = mock_state.update_data.call_args[1]
        assert update_kwargs["audience"] == "all"
        assert update_kwargs["user_count"] == 3

    @patch("routers.admin.broadcast.UsersRepository")
    async def test_audience_active_7d(
        self,
        mock_users_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "admin:bc:active_7d"
        mock_users_cls.return_value.get_ids_by_audience = AsyncMock(return_value=[10, 20])

        await cb_broadcast_audience(mock_callback, mock_state, admin_user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "2 чел." in text

    async def test_non_admin_rejected(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        regular_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "admin:bc:all"

        await cb_broadcast_audience(mock_callback, mock_state, regular_user, mock_db)

        mock_callback.answer.assert_called_with("Нет доступа.", show_alert=True)


# ---------------------------------------------------------------------------
# fsm_broadcast_text
# ---------------------------------------------------------------------------


class TestFsmBroadcastText:
    async def test_valid_text_shows_preview(self, mock_state: AsyncMock, admin_user: User, mock_db: MagicMock) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "Привет! Это рассылка."
        mock_state.get_data = AsyncMock(return_value={"user_count": 10, "audience": "all"})

        await fsm_broadcast_text(msg, mock_state, admin_user, mock_db)

        mock_state.set_state.assert_called_with(BroadcastFSM.confirm)
        text = msg.answer.call_args[0][0]
        assert "Превью рассылки" in text

    async def test_empty_text_rejected(self, mock_state: AsyncMock, admin_user: User, mock_db: MagicMock) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "   "

        await fsm_broadcast_text(msg, mock_state, admin_user, mock_db)

        msg.answer.assert_called_with("Введите непустое сообщение.")

    async def test_too_long_text_rejected(self, mock_state: AsyncMock, admin_user: User, mock_db: MagicMock) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "x" * 5000

        await fsm_broadcast_text(msg, mock_state, admin_user, mock_db)

        text = msg.answer.call_args[0][0]
        assert "4000" in text

    async def test_non_admin_clears_state(self, mock_state: AsyncMock, regular_user: User, mock_db: MagicMock) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()
        msg.text = "test"

        await fsm_broadcast_text(msg, mock_state, regular_user, mock_db)

        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# cb_broadcast_confirm
# ---------------------------------------------------------------------------


class TestCbBroadcastConfirm:
    @patch("routers.admin.broadcast.UsersRepository")
    async def test_sends_broadcast(
        self,
        mock_users_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"broadcast_text": "Hello!", "audience": "all"})
        mock_users_cls.return_value.get_ids_by_audience = AsyncMock(return_value=[1, 2, 3])

        await cb_broadcast_confirm(mock_callback, mock_state, admin_user, mock_db)

        assert mock_callback.bot.send_message.call_count == 3
        mock_state.clear.assert_called_once()

    @patch("routers.admin.broadcast.UsersRepository")
    async def test_counts_failures(
        self,
        mock_users_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"broadcast_text": "Hello!", "audience": "all"})
        mock_users_cls.return_value.get_ids_by_audience = AsyncMock(return_value=[1, 2])
        mock_callback.bot.send_message = AsyncMock(side_effect=[None, Exception("blocked")])

        await cb_broadcast_confirm(mock_callback, mock_state, admin_user, mock_db)

        text = mock_callback.message.answer.call_args[0][0]
        assert "1" in text  # 1 sent
        assert "1" in text  # 1 failed

    async def test_no_text_clears(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"broadcast_text": "", "audience": "all"})

        await cb_broadcast_confirm(mock_callback, mock_state, admin_user, mock_db)

        mock_state.clear.assert_called_once()
        mock_callback.answer.assert_called_with("Нет текста для отправки.", show_alert=True)

    async def test_non_admin_rejected(
        self,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        regular_user: User,
        mock_db: MagicMock,
    ) -> None:
        await cb_broadcast_confirm(mock_callback, mock_state, regular_user, mock_db)

        mock_state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# _AUDIENCE_LABELS
# ---------------------------------------------------------------------------


class TestAudienceLabels:
    def test_all_audiences_have_labels(self) -> None:
        for key in ("all", "active_7d", "active_30d", "paid"):
            assert key in _AUDIENCE_LABELS
