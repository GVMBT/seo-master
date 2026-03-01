"""Tests for services/payments/stars.py — Stars payment service.

Covers: invoice building, pre-checkout validation, payment processing,
referral bonus, display formatting. No subscriptions in v2.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.payments.stars import StarsPaymentService, credit_referral_bonus


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def service(mock_db: MagicMock) -> StarsPaymentService:
    return StarsPaymentService(db=mock_db, admin_ids=[999])


# ---------------------------------------------------------------------------
# Invoice building
# ---------------------------------------------------------------------------


class TestBuildInvoiceParams:
    def test_returns_required_keys(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=123, package_name="start")
        assert "title" in params
        assert "description" in params
        assert "payload" in params
        assert params["currency"] == "XTR"
        assert params["provider_token"] == ""

    def test_payload_format(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=42, package_name="standard")
        assert params["payload"] == "purchase:standard:user_42"

    def test_stars_amount_matches_package(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=1, package_name="pro")
        assert params["prices"][0]["amount"] == 195

    def test_start_package_stars(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=1, package_name="start")
        assert params["prices"][0]["amount"] == 33

    def test_title_uses_label(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=1, package_name="standard")
        assert "Стандарт" in params["title"]


# ---------------------------------------------------------------------------
# Pre-checkout validation
# ---------------------------------------------------------------------------


class TestValidatePreCheckout:
    def test_valid_purchase(self, service: StarsPaymentService) -> None:
        ok, msg = service.validate_pre_checkout(42, "purchase:start:user_42")
        assert ok is True
        assert msg == ""

    def test_wrong_user_id(self, service: StarsPaymentService) -> None:
        ok, msg = service.validate_pre_checkout(42, "purchase:start:user_99")
        assert ok is False
        assert msg != ""

    def test_unknown_package(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "purchase:nonexistent:user_42")
        assert ok is False

    def test_invalid_format_too_few_parts(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "purchase:start")
        assert ok is False

    def test_unknown_action(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "gift:start:user_42")
        assert ok is False

    def test_sub_action_rejected(self, service: StarsPaymentService) -> None:
        """Subscriptions removed in v2 — sub: action should be rejected."""
        ok, _msg = service.validate_pre_checkout(42, "sub:pro:user_42")
        assert ok is False


# ---------------------------------------------------------------------------
# Successful payment processing
# ---------------------------------------------------------------------------


class TestProcessSuccessfulPayment:
    @pytest.fixture
    def service_with_mocks(self, mock_db: MagicMock) -> StarsPaymentService:
        svc = StarsPaymentService(db=mock_db, admin_ids=[999])
        svc._users = MagicMock()
        svc._users.credit_balance = AsyncMock(return_value=2500)
        svc._users.get_by_id = AsyncMock(return_value=MagicMock(referrer_id=None))
        svc._payments = MagicMock()
        svc._payments.get_by_telegram_charge_id = AsyncMock(return_value=None)
        svc._payments.create = AsyncMock(return_value=MagicMock(id=1))
        svc._payments.update = AsyncMock()
        svc._payments.create_expense = AsyncMock()
        return svc

    async def test_purchase_credits_tokens(self, service_with_mocks: StarsPaymentService) -> None:
        result = await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="purchase:start:user_42",
            telegram_payment_charge_id="charge_123",
            provider_payment_charge_id="provider_123",
            total_amount=33,
        )
        assert result["tokens_credited"] == 500
        assert result["new_balance"] == 2500
        assert result["is_duplicate"] is False
        service_with_mocks._users.credit_balance.assert_called_once_with(42, 500)

    async def test_purchase_creates_payment_record(self, service_with_mocks: StarsPaymentService) -> None:
        await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="purchase:standard:user_42",
            telegram_payment_charge_id="charge_456",
            provider_payment_charge_id="prov_456",
            total_amount=104,
        )
        service_with_mocks._payments.create.assert_called_once()
        service_with_mocks._payments.update.assert_called_once()
        service_with_mocks._payments.create_expense.assert_called_once()

    async def test_idempotency_duplicate_charge(self, service_with_mocks: StarsPaymentService) -> None:
        """Duplicate charge_id should not credit tokens (E10)."""
        service_with_mocks._payments.get_by_telegram_charge_id = AsyncMock(return_value=MagicMock(package_name="start"))
        result = await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="purchase:start:user_42",
            telegram_payment_charge_id="dup_charge",
            provider_payment_charge_id="prov",
            total_amount=33,
        )
        assert result["is_duplicate"] is True
        assert result["tokens_credited"] == 0
        service_with_mocks._users.credit_balance.assert_not_called()

    async def test_unknown_package_returns_error(self, service_with_mocks: StarsPaymentService) -> None:
        result = await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="purchase:nonexistent:user_42",
            telegram_payment_charge_id="charge_bad",
            provider_payment_charge_id="prov_bad",
            total_amount=100,
        )
        assert result["tokens_credited"] == 0
        assert "error" in result

    async def test_unknown_action_returns_error(self, service_with_mocks: StarsPaymentService) -> None:
        result = await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="gift:start:user_42",
            telegram_payment_charge_id="charge_gift",
            provider_payment_charge_id="prov_gift",
            total_amount=33,
        )
        assert result["tokens_credited"] == 0


# ---------------------------------------------------------------------------
# Referral bonus
# ---------------------------------------------------------------------------


class TestReferralBonus:
    async def test_referral_bonus_credited(self) -> None:
        """Referrer gets 10% of price_rub (F19)."""
        users = MagicMock()
        payments = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock(return_value=5000)

        payments.create_expense = AsyncMock()
        payments.update = AsyncMock()
        payments.sum_referral_bonuses = AsyncMock(return_value=0)

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1)

        # 10% of 1000 = 100
        users.credit_balance.assert_called_once_with(100, 100)
        payments.create_expense.assert_called_once()

    async def test_no_referrer_skips(self) -> None:
        users = MagicMock()
        payments = MagicMock()
        users.get_by_id = AsyncMock(return_value=MagicMock(referrer_id=None))

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1)
        payments.create_expense.assert_not_called()

    async def test_provider_label_appended(self) -> None:
        """Provider label should appear in description."""
        users = MagicMock()
        payments = MagicMock()

        buyer = MagicMock(referrer_id=100)
        referrer = MagicMock(id=100)
        users.get_by_id = AsyncMock(side_effect=lambda uid: buyer if uid == 42 else referrer)
        users.credit_balance = AsyncMock(return_value=5000)
        payments.create_expense = AsyncMock()
        payments.update = AsyncMock()
        payments.sum_referral_bonuses = AsyncMock(return_value=0)

        await credit_referral_bonus(users, payments, user_id=42, price_rub=1000, payment_id=1, provider_label="ЮKassa")
        expense_call = payments.create_expense.call_args[0][0]
        assert "ЮKassa" in expense_call.description


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_tariffs_text_contains_balance(self, service: StarsPaymentService) -> None:
        text = service.format_tariffs_text(1500)
        assert "1500" in text
        assert "Тарифы" in text

    def test_package_text_contains_tokens(self, service: StarsPaymentService) -> None:
        text = service.format_package_text("start")
        assert "500" in text

    def test_package_text_shows_discount(self, service: StarsPaymentService) -> None:
        text = service.format_package_text("standard")
        assert "20%" in text

    def test_payment_link_text_package(self, service: StarsPaymentService) -> None:
        text = service.format_payment_link_text("pro")
        assert "3000" in text
        assert "Про" in text


# ---------------------------------------------------------------------------
# Refund processing (C15, API_CONTRACTS §2.3)
# ---------------------------------------------------------------------------


class TestProcessRefund:
    """Tests for StarsPaymentService.process_refund (C15, CR-78b)."""

    @pytest.fixture
    def svc_with_mocks(self, mock_db: MagicMock) -> StarsPaymentService:
        svc = StarsPaymentService(db=mock_db, admin_ids=[999])
        svc._users = MagicMock()
        svc._users.force_debit_balance = AsyncMock(return_value=1000)
        svc._payments = MagicMock()
        svc._payments.get_by_telegram_charge_id = AsyncMock(
            return_value=MagicMock(
                id=1,
                tokens_amount=500,
                package_name="start",
                status="completed",
            )
        )
        svc._payments.mark_refunded = AsyncMock(return_value=True)
        svc._payments.create_expense = AsyncMock()
        return svc

    async def test_process_refund_debits_tokens(self, svc_with_mocks: StarsPaymentService) -> None:
        result = await svc_with_mocks.process_refund(
            user_id=42,
            telegram_payment_charge_id="charge_abc",
        )
        assert result["tokens_debited"] == 500
        assert result["new_balance"] == 1000
        svc_with_mocks._users.force_debit_balance.assert_called_once_with(42, 500)

    async def test_process_refund_uses_atomic_cas(self, svc_with_mocks: StarsPaymentService) -> None:
        """CR-78b: refund uses mark_refunded (atomic CAS) instead of plain update."""
        await svc_with_mocks.process_refund(user_id=42, telegram_payment_charge_id="charge_abc")
        svc_with_mocks._payments.mark_refunded.assert_called_once_with(1)

    async def test_process_refund_cas_failure_returns_already_refunded(
        self,
        svc_with_mocks: StarsPaymentService,
    ) -> None:
        """CR-78b: if CAS fails (concurrent refund), return already_refunded."""
        svc_with_mocks._payments.mark_refunded = AsyncMock(return_value=False)
        result = await svc_with_mocks.process_refund(user_id=42, telegram_payment_charge_id="charge_race")
        assert result.get("already_refunded") is True
        assert result["tokens_debited"] == 0
        svc_with_mocks._users.force_debit_balance.assert_not_called()

    async def test_process_refund_records_expense(self, svc_with_mocks: StarsPaymentService) -> None:
        await svc_with_mocks.process_refund(user_id=42, telegram_payment_charge_id="charge_abc")
        svc_with_mocks._payments.create_expense.assert_called_once()
        expense_arg = svc_with_mocks._payments.create_expense.call_args[0][0]
        assert expense_arg.amount == -500
        assert expense_arg.operation_type == "stars_refund"

    async def test_payment_not_found_returns_error(self, svc_with_mocks: StarsPaymentService) -> None:
        svc_with_mocks._payments.get_by_telegram_charge_id = AsyncMock(return_value=None)
        result = await svc_with_mocks.process_refund(user_id=42, telegram_payment_charge_id="missing")
        assert result["tokens_debited"] == 0
        assert "error" in result
        svc_with_mocks._users.force_debit_balance.assert_not_called()

    async def test_already_refunded_returns_flag(self, svc_with_mocks: StarsPaymentService) -> None:
        svc_with_mocks._payments.get_by_telegram_charge_id = AsyncMock(
            return_value=MagicMock(id=1, tokens_amount=500, package_name="start", status="refunded")
        )
        result = await svc_with_mocks.process_refund(user_id=42, telegram_payment_charge_id="dup")
        assert result.get("already_refunded") is True
        assert result["tokens_debited"] == 0
        svc_with_mocks._users.force_debit_balance.assert_not_called()

    async def test_negative_balance_allowed(self, svc_with_mocks: StarsPaymentService) -> None:
        """Per API_CONTRACTS §2.3: balance can go negative on refund."""
        svc_with_mocks._users.force_debit_balance = AsyncMock(return_value=-300)
        result = await svc_with_mocks.process_refund(user_id=42, telegram_payment_charge_id="charge_neg")
        assert result["new_balance"] == -300
        assert result["tokens_debited"] == 500
