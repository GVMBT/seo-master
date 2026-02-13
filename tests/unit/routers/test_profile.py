"""Tests for routers/profile.py — profile, history, referral."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import Message

from db.models import TokenExpense, User
from routers.profile import _format_expense, _format_profile, cb_history, cb_profile, cb_referral

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User",
        "balance": 1500,
        "role": "user",
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_expense(**overrides: Any) -> TokenExpense:
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 123456789,
        "amount": -200,
        "operation_type": "text_generation",
        "created_at": datetime(2026, 2, 1, 14, 30, tzinfo=UTC),
    }
    defaults.update(overrides)
    return TokenExpense(**defaults)


def _make_stats(**overrides: Any) -> dict[str, int]:
    defaults = {
        "project_count": 3,
        "category_count": 8,
        "schedule_count": 5,
        "referral_count": 2,
        "posts_per_week": 17,
        "tokens_per_week": 1400,
        "tokens_per_month": 5600,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# _format_expense
# ---------------------------------------------------------------------------


class TestFormatExpense:
    def test_negative_amount_no_plus(self) -> None:
        exp = _make_expense(amount=-200, operation_type="text_generation")
        result = _format_expense(exp)
        assert "-200" in result
        assert "Генерация текста" in result
        assert "01.02.2026 14:30" in result

    def test_positive_amount_has_plus(self) -> None:
        exp = _make_expense(amount=3500, operation_type="purchase")
        result = _format_expense(exp)
        assert "+3500" in result
        assert "Покупка токенов" in result

    def test_unknown_operation_shows_raw(self) -> None:
        exp = _make_expense(operation_type="some_new_type")
        result = _format_expense(exp)
        assert "some_new_type" in result

    def test_no_created_at_shows_dash(self) -> None:
        exp = _make_expense(created_at=None)
        result = _format_expense(exp)
        assert "—" in result


# ---------------------------------------------------------------------------
# _format_profile
# ---------------------------------------------------------------------------


class TestFormatProfile:
    def test_basic_profile(self) -> None:
        user = _make_user()
        stats = _make_stats(schedule_count=0)
        text = _format_profile(user, stats)
        assert "ID: 123456789" in text
        assert "Test User" in text
        assert "1500" in text
        assert "01.01.2026" in text
        assert "Проектов: 3" in text
        assert "Категорий: 8" in text
        # No forecast when schedule_count == 0
        assert "Прогноз" not in text

    def test_profile_with_schedules(self) -> None:
        user = _make_user(balance=2000)
        stats = _make_stats(
            schedule_count=5, posts_per_week=17,
            tokens_per_week=1400, tokens_per_month=5600,
        )
        text = _format_profile(user, stats)
        assert "Прогноз расходов:" in text
        assert "Постов в неделю: 17" in text
        assert "~1400" in text
        assert "~5600" in text

    def test_admin_role(self) -> None:
        user = _make_user(role="admin")
        stats = _make_stats(schedule_count=0)
        text = _format_profile(user, stats)
        assert "Администратор" in text

    def test_no_created_at(self) -> None:
        user = _make_user(created_at=None)
        stats = _make_stats(schedule_count=0)
        text = _format_profile(user, stats)
        assert "—" in text


# ---------------------------------------------------------------------------
# cb_profile
# ---------------------------------------------------------------------------


class TestCbProfile:
    async def test_shows_profile(self) -> None:
        user = _make_user()
        mock_db = MagicMock()

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()

        with patch("routers.profile._make_service") as mock_make_svc:
            svc = AsyncMock()
            svc.get_profile_stats.return_value = _make_stats(schedule_count=0)
            mock_make_svc.return_value = svc

            await cb_profile(callback, user, mock_db)

        callback.message.edit_text.assert_awaited_once()
        text_arg = callback.message.edit_text.call_args[0][0]
        assert "ID: 123456789" in text_arg
        callback.answer.assert_awaited_once()

    async def test_inaccessible_message(self) -> None:
        user = _make_user()
        mock_db = MagicMock()

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = None  # Not a Message instance

        await cb_profile(callback, user, mock_db)
        callback.answer.assert_awaited_once_with("Сообщение недоступно.", show_alert=True)


# ---------------------------------------------------------------------------
# cb_history
# ---------------------------------------------------------------------------


class TestCbHistory:
    async def test_shows_history(self) -> None:
        user = _make_user()
        mock_db = MagicMock()

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()

        with patch("routers.profile._make_service") as mock_make_svc:
            svc = AsyncMock()
            svc.get_history.return_value = [
                _make_expense(amount=-200, operation_type="text_generation"),
                _make_expense(amount=3500, operation_type="purchase"),
            ]
            mock_make_svc.return_value = svc

            await cb_history(callback, user, mock_db)

        text = callback.message.edit_text.call_args[0][0]
        assert "Последние операции:" in text
        assert "Генерация текста" in text
        assert "Покупка токенов" in text

    async def test_empty_history(self) -> None:
        user = _make_user()
        mock_db = MagicMock()

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()

        with patch("routers.profile._make_service") as mock_make_svc:
            svc = AsyncMock()
            svc.get_history.return_value = []
            mock_make_svc.return_value = svc

            await cb_history(callback, user, mock_db)

        text = callback.message.edit_text.call_args[0][0]
        assert "История расходов пуста" in text


# ---------------------------------------------------------------------------
# cb_referral
# ---------------------------------------------------------------------------


class TestCbReferral:
    async def test_shows_referral_info(self) -> None:
        user = _make_user()
        mock_db = MagicMock()

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()
        # Mock bot.me()
        bot_me = MagicMock()
        bot_me.username = "TestSEOBot"
        callback.bot = MagicMock()
        callback.bot.me = AsyncMock(return_value=bot_me)

        with patch("routers.profile._make_service") as mock_make_svc:
            svc = AsyncMock()
            svc.get_profile_stats.return_value = _make_stats(referral_count=3)
            svc.get_referral_bonus_total.return_value = 450
            mock_make_svc.return_value = svc

            await cb_referral(callback, user, mock_db)

        text = callback.message.edit_text.call_args[0][0]
        assert "ref_123456789" in text
        assert "TestSEOBot" in text
        assert "3 человек" in text
        assert "450" in text
        assert "10%" in text

    async def test_no_bot_username_fallback(self) -> None:
        user = _make_user()
        mock_db = MagicMock()

        callback = MagicMock()
        callback.answer = AsyncMock()
        callback.message = MagicMock(spec=Message)
        callback.message.edit_text = AsyncMock()
        callback.bot = None

        with patch("routers.profile._make_service") as mock_make_svc:
            svc = AsyncMock()
            svc.get_profile_stats.return_value = _make_stats(referral_count=0)
            svc.get_referral_bonus_total.return_value = 0
            mock_make_svc.return_value = svc

            await cb_referral(callback, user, mock_db)

        text = callback.message.edit_text.call_args[0][0]
        assert "SEOMasterBot" in text
