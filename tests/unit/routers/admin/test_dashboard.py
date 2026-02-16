"""Tests for routers/admin/dashboard.py — admin panel (F20)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message

from db.models import User
from routers.admin.dashboard import (
    _build_admin_stats,
    _is_admin,
    btn_admin_main,
    cb_admin_costs,
    cb_admin_main,
    cb_admin_monitoring,
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
    return cb


# ---------------------------------------------------------------------------
# _is_admin
# ---------------------------------------------------------------------------


class TestIsAdmin:
    def test_admin_role(self, admin_user: User) -> None:
        assert _is_admin(admin_user) is True

    def test_regular_role(self, regular_user: User) -> None:
        assert _is_admin(regular_user) is False


# ---------------------------------------------------------------------------
# _build_admin_stats
# ---------------------------------------------------------------------------


class TestBuildAdminStats:
    @patch("routers.admin.dashboard.PaymentsRepository")
    @patch("routers.admin.dashboard.UsersRepository")
    async def test_builds_stats_text(
        self, mock_users_cls: MagicMock, mock_pay_cls: MagicMock, mock_db: MagicMock
    ) -> None:
        mock_users_cls.return_value.count_all = AsyncMock(return_value=100)
        mock_users_cls.return_value.count_active = AsyncMock(return_value=42)
        mock_pay_cls.return_value.sum_revenue = AsyncMock(return_value=5000)

        text = await _build_admin_stats(mock_db)

        assert "100" in text
        assert "42" in text
        assert "5000" in text


# ---------------------------------------------------------------------------
# btn_admin_main
# ---------------------------------------------------------------------------


class TestBtnAdminMain:
    @patch("routers.admin.dashboard._build_admin_stats", new_callable=AsyncMock, return_value="Stats text")
    async def test_admin_sees_dashboard(self, mock_stats: AsyncMock, admin_user: User, mock_db: MagicMock) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()

        await btn_admin_main(msg, admin_user, mock_db)

        msg.answer.assert_called_once()
        assert "Stats text" in msg.answer.call_args[0][0]

    async def test_non_admin_rejected(self, regular_user: User, mock_db: MagicMock) -> None:
        msg = MagicMock()
        msg.answer = AsyncMock()

        await btn_admin_main(msg, regular_user, mock_db)

        msg.answer.assert_called_with("Нет доступа.")


# ---------------------------------------------------------------------------
# cb_admin_main
# ---------------------------------------------------------------------------


class TestCbAdminMain:
    @patch("routers.admin.dashboard._build_admin_stats", new_callable=AsyncMock, return_value="Stats")
    async def test_admin_callback(
        self, mock_stats: AsyncMock, mock_callback: MagicMock, admin_user: User, mock_db: MagicMock
    ) -> None:
        await cb_admin_main(mock_callback, admin_user, mock_db)

        mock_callback.message.edit_text.assert_called_once()

    async def test_non_admin_rejected(self, mock_callback: MagicMock, regular_user: User, mock_db: MagicMock) -> None:
        await cb_admin_main(mock_callback, regular_user, mock_db)

        mock_callback.answer.assert_called_with("Нет доступа.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_admin_monitoring
# ---------------------------------------------------------------------------


class TestCbAdminMonitoring:
    @patch("routers.admin.dashboard.UsersRepository")
    async def test_monitoring_ok(
        self,
        mock_users_cls: MagicMock,
        mock_callback: MagicMock,
        admin_user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_users_cls.return_value.count_all = AsyncMock(return_value=50)
        mock_redis.ping = AsyncMock()

        await cb_admin_monitoring(mock_callback, admin_user, mock_db, mock_redis)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Redis: OK" in text
        assert "PostgreSQL: OK" in text

    @patch("routers.admin.dashboard.UsersRepository")
    async def test_monitoring_redis_error(
        self,
        mock_users_cls: MagicMock,
        mock_callback: MagicMock,
        admin_user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        mock_users_cls.return_value.count_all = AsyncMock(return_value=50)
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Redis down"))

        await cb_admin_monitoring(mock_callback, admin_user, mock_db, mock_redis)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Redis: ОШИБКА" in text

    async def test_non_admin_rejected(
        self,
        mock_callback: MagicMock,
        regular_user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        await cb_admin_monitoring(mock_callback, regular_user, mock_db, mock_redis)

        mock_callback.answer.assert_called_with("Нет доступа.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_admin_costs
# ---------------------------------------------------------------------------


class TestCbAdminCosts:
    @patch("routers.admin.dashboard.PaymentsRepository")
    async def test_shows_costs(
        self,
        mock_pay_cls: MagicMock,
        mock_callback: MagicMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_pay_cls.return_value.get_expenses_summary = AsyncMock(return_value={"article": 500, "review": 100})

        await cb_admin_costs(mock_callback, admin_user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "article" in text
        assert "500" in text

    @patch("routers.admin.dashboard.PaymentsRepository")
    async def test_empty_costs(
        self,
        mock_pay_cls: MagicMock,
        mock_callback: MagicMock,
        admin_user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_pay_cls.return_value.get_expenses_summary = AsyncMock(return_value={})

        await cb_admin_costs(mock_callback, admin_user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Нет данных" in text
