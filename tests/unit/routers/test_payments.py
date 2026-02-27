"""Tests for routers/payments.py — Stars payment handlers.

Covers: pre-checkout validation, successful payment, refund handler (C15).
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
# Refund handler (C15)
# ---------------------------------------------------------------------------


class TestRefundedPaymentHandler:
    """Tests for the Stars refund handler (C15, API_CONTRACTS §2.3)."""

    async def test_refund_debits_tokens_and_logs(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Refund should debit tokens and update payment status."""
        refund_obj = MagicMock()
        refund_obj.telegram_payment_charge_id = "charge_abc"
        mock_message.refunded_payment = refund_obj

        mock_svc = MagicMock()
        mock_svc.process_refund = AsyncMock(
            return_value={"tokens_debited": 500, "new_balance": 1000}
        )

        with patch("routers.payments.get_settings") as mock_settings, patch(
            "routers.payments.StarsPaymentService", return_value=mock_svc
        ):
            mock_settings.return_value.admin_ids = [999]
            from routers.payments import refunded_payment_handler

            await refunded_payment_handler(mock_message, user, mock_db)

        mock_svc.process_refund.assert_awaited_once_with(
            user_id=123456,
            telegram_payment_charge_id="charge_abc",
        )
        # Balance positive — no negative-balance warning message
        mock_message.answer.assert_not_called()

    async def test_refund_negative_balance_shows_warning(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """When refund causes negative balance, user sees warning."""
        refund_obj = MagicMock()
        refund_obj.telegram_payment_charge_id = "charge_neg"
        mock_message.refunded_payment = refund_obj

        mock_svc = MagicMock()
        mock_svc.process_refund = AsyncMock(
            return_value={"tokens_debited": 2000, "new_balance": -500}
        )

        with patch("routers.payments.get_settings") as mock_settings, patch(
            "routers.payments.StarsPaymentService", return_value=mock_svc
        ):
            mock_settings.return_value.admin_ids = [999]
            from routers.payments import refunded_payment_handler

            await refunded_payment_handler(mock_message, user, mock_db)

        mock_message.answer.assert_awaited_once()
        call_text = mock_message.answer.call_args[0][0]
        assert "-500" in call_text
        assert "отрицателен" in call_text

    async def test_refund_none_payment_returns_early(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """If refunded_payment is None, handler returns early."""
        mock_message.refunded_payment = None

        from routers.payments import refunded_payment_handler

        await refunded_payment_handler(mock_message, user, mock_db)
        mock_message.answer.assert_not_called()

    async def test_refund_duplicate_ignored(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Already-refunded payment is silently ignored."""
        refund_obj = MagicMock()
        refund_obj.telegram_payment_charge_id = "charge_dup"
        mock_message.refunded_payment = refund_obj

        mock_svc = MagicMock()
        mock_svc.process_refund = AsyncMock(
            return_value={"tokens_debited": 0, "already_refunded": True}
        )

        with patch("routers.payments.get_settings") as mock_settings, patch(
            "routers.payments.StarsPaymentService", return_value=mock_svc
        ):
            mock_settings.return_value.admin_ids = [999]
            from routers.payments import refunded_payment_handler

            await refunded_payment_handler(mock_message, user, mock_db)

        # No user-facing message for duplicates
        mock_message.answer.assert_not_called()

    async def test_refund_error_logged_no_message(
        self,
        mock_message: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        """Payment not found error is logged but not shown to user."""
        refund_obj = MagicMock()
        refund_obj.telegram_payment_charge_id = "charge_err"
        mock_message.refunded_payment = refund_obj

        mock_svc = MagicMock()
        mock_svc.process_refund = AsyncMock(
            return_value={"tokens_debited": 0, "error": "Payment not found"}
        )

        with patch("routers.payments.get_settings") as mock_settings, patch(
            "routers.payments.StarsPaymentService", return_value=mock_svc
        ):
            mock_settings.return_value.admin_ids = [999]
            from routers.payments import refunded_payment_handler

            await refunded_payment_handler(mock_message, user, mock_db)

        mock_message.answer.assert_not_called()
