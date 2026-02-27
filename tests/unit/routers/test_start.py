"""Tests for routers/start.py — referral linking via UsersService (CR-77b).

Verifies that cmd_start delegates referral logic to UsersService
instead of calling UsersRepository directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Chat, Message
from aiogram.types import User as TgUser

from db.models import User


def _make_user(**overrides) -> User:  # type: ignore[no-untyped-def]
    defaults = {
        "id": 123456,
        "username": "testuser",
        "first_name": "Test",
        "last_name": None,
        "balance": 1500,
        "language": "ru",
        "role": "user",
    }
    defaults.update(overrides)
    return User(**defaults)


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.set = AsyncMock(return_value="OK")
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def mock_state() -> MagicMock:
    state = MagicMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


@pytest.fixture
def user() -> User:
    return _make_user()


@pytest.fixture
def mock_message() -> MagicMock:
    msg = MagicMock(spec=Message)
    msg.answer = AsyncMock()
    msg.from_user = MagicMock(spec=TgUser)
    msg.from_user.id = 123456
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = 123456
    return msg


# ---------------------------------------------------------------------------
# Referral via UsersService (CR-77b)
# ---------------------------------------------------------------------------


class TestReferralLinking:
    """Verify cmd_start uses UsersService.link_referrer() for referral."""

    async def test_new_user_referral_delegates_to_service(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """New user with referral deep link calls UsersService.link_referrer()."""
        mock_message.text = "/start referrer_999"

        mock_users_svc = MagicMock()
        mock_users_svc.link_referrer = AsyncMock(return_value=True)

        with (
            patch("routers.start.ensure_no_active_fsm", new=AsyncMock(return_value=None)),
            patch("routers.start.UsersService", return_value=mock_users_svc) as mock_svc_cls,
            patch("routers.start._build_dashboard", new=AsyncMock(return_value=("Dashboard", MagicMock()))),
            patch("routers.start.main_menu_kb", return_value=MagicMock()),
        ):
            from routers.start import cmd_start

            await cmd_start(
                mock_message,
                mock_state,
                user,
                is_new_user=True,
                is_admin=False,
                db=mock_db,
                redis=mock_redis,
            )

        mock_svc_cls.assert_called_once_with(mock_db)
        mock_users_svc.link_referrer.assert_awaited_once_with(user.id, 999, mock_redis)

    async def test_existing_user_referral_ignored(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Existing user (is_new_user=False) should not trigger referral linking."""
        mock_message.text = "/start referrer_999"

        with (
            patch("routers.start.ensure_no_active_fsm", new=AsyncMock(return_value=None)),
            patch("routers.start.UsersService") as mock_svc_cls,
            patch("routers.start._build_dashboard", new=AsyncMock(return_value=("Dashboard", MagicMock()))),
        ):
            from routers.start import cmd_start

            await cmd_start(
                mock_message,
                mock_state,
                user,
                is_new_user=False,
                is_admin=False,
                db=mock_db,
                redis=mock_redis,
            )

        mock_svc_cls.assert_not_called()

    async def test_invalid_referral_arg_ignored(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Invalid referral arg (non-numeric) should not call UsersService."""
        mock_message.text = "/start referrer_abc"

        with (
            patch("routers.start.ensure_no_active_fsm", new=AsyncMock(return_value=None)),
            patch("routers.start.UsersService") as mock_svc_cls,
            patch("routers.start._build_dashboard", new=AsyncMock(return_value=("Dashboard", MagicMock()))),
            patch("routers.start.main_menu_kb", return_value=MagicMock()),
        ):
            from routers.start import cmd_start

            await cmd_start(
                mock_message,
                mock_state,
                user,
                is_new_user=True,
                is_admin=False,
                db=mock_db,
                redis=mock_redis,
            )

        # _parse_referrer_id returns None for "abc", so UsersService is not called
        mock_svc_cls.assert_not_called()

    async def test_no_deep_link_no_referral(
        self,
        mock_message: MagicMock,
        mock_state: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_redis: MagicMock,
    ) -> None:
        """Plain /start without args does not trigger referral."""
        mock_message.text = "/start"

        with (
            patch("routers.start.ensure_no_active_fsm", new=AsyncMock(return_value=None)),
            patch("routers.start.UsersService") as mock_svc_cls,
            patch("routers.start._build_dashboard", new=AsyncMock(return_value=("Dashboard", MagicMock()))),
            patch("routers.start.main_menu_kb", return_value=MagicMock()),
        ):
            from routers.start import cmd_start

            await cmd_start(
                mock_message,
                mock_state,
                user,
                is_new_user=True,
                is_admin=False,
                db=mock_db,
                redis=mock_redis,
            )

        mock_svc_cls.assert_not_called()
