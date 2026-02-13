"""Tests for services/payments/stars.py — Stars payment service.

Covers: invoice building, pre-checkout validation, payment processing,
subscription management, referral bonus, display formatting.
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
    return StarsPaymentService(db=mock_db, admin_id=999)


# ---------------------------------------------------------------------------
# Invoice building
# ---------------------------------------------------------------------------


class TestBuildInvoiceParams:
    def test_returns_required_keys(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=123, package_name="mini")
        assert "title" in params
        assert "description" in params
        assert "payload" in params
        assert params["currency"] == "XTR"
        assert params["provider_token"] == ""

    def test_payload_format(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=42, package_name="starter")
        assert params["payload"] == "purchase:starter:user_42"

    def test_stars_amount_matches_package(self, service: StarsPaymentService) -> None:
        params = service.build_invoice_params(user_id=1, package_name="pro")
        assert params["prices"][0]["amount"] == 390


class TestBuildSubscriptionParams:
    def test_returns_subscription_period(self, service: StarsPaymentService) -> None:
        params = service.build_subscription_params(user_id=1, sub_name="pro")
        assert params["subscription_period"] == 2_592_000

    def test_payload_format(self, service: StarsPaymentService) -> None:
        params = service.build_subscription_params(user_id=55, sub_name="business")
        assert params["payload"] == "sub:business:user_55"

    def test_stars_amount(self, service: StarsPaymentService) -> None:
        params = service.build_subscription_params(user_id=1, sub_name="enterprise")
        assert params["prices"][0]["amount"] == 2600


# ---------------------------------------------------------------------------
# Pre-checkout validation
# ---------------------------------------------------------------------------


class TestValidatePreCheckout:
    def test_valid_purchase(self, service: StarsPaymentService) -> None:
        ok, msg = service.validate_pre_checkout(42, "purchase:mini:user_42")
        assert ok is True
        assert msg == ""

    def test_valid_subscription(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "sub:pro:user_42")
        assert ok is True

    def test_wrong_user_id(self, service: StarsPaymentService) -> None:
        ok, msg = service.validate_pre_checkout(42, "purchase:mini:user_99")
        assert ok is False
        assert "идентификации" in msg.lower() or msg != ""

    def test_unknown_package(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "purchase:nonexistent:user_42")
        assert ok is False

    def test_unknown_subscription(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "sub:nonexistent:user_42")
        assert ok is False

    def test_invalid_format_too_few_parts(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "purchase:mini")
        assert ok is False

    def test_unknown_action(self, service: StarsPaymentService) -> None:
        ok, _msg = service.validate_pre_checkout(42, "gift:mini:user_42")
        assert ok is False


# ---------------------------------------------------------------------------
# Successful payment processing
# ---------------------------------------------------------------------------


class TestProcessSuccessfulPayment:
    @pytest.fixture
    def service_with_mocks(self, mock_db: MagicMock) -> StarsPaymentService:
        svc = StarsPaymentService(db=mock_db, admin_id=999)
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
            payload="purchase:mini:user_42",
            telegram_payment_charge_id="charge_123",
            provider_payment_charge_id="provider_123",
            total_amount=65,
        )
        assert result["tokens_credited"] == 1000
        assert result["new_balance"] == 2500
        assert result["is_duplicate"] is False
        service_with_mocks._users.credit_balance.assert_called_once_with(42, 1000)

    async def test_purchase_creates_payment_record(self, service_with_mocks: StarsPaymentService) -> None:
        await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="purchase:starter:user_42",
            telegram_payment_charge_id="charge_456",
            provider_payment_charge_id="prov_456",
            total_amount=195,
        )
        service_with_mocks._payments.create.assert_called_once()
        service_with_mocks._payments.update.assert_called_once()
        service_with_mocks._payments.create_expense.assert_called_once()

    async def test_idempotency_duplicate_charge(self, service_with_mocks: StarsPaymentService) -> None:
        """Duplicate charge_id should not credit tokens (E10)."""
        service_with_mocks._payments.get_by_telegram_charge_id = AsyncMock(
            return_value=MagicMock(package_name="mini")
        )
        result = await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="purchase:mini:user_42",
            telegram_payment_charge_id="dup_charge",
            provider_payment_charge_id="prov",
            total_amount=65,
        )
        assert result["is_duplicate"] is True
        assert result["tokens_credited"] == 0
        service_with_mocks._users.credit_balance.assert_not_called()

    async def test_subscription_payment(self, service_with_mocks: StarsPaymentService) -> None:
        result = await service_with_mocks.process_successful_payment(
            user_id=42,
            payload="sub:pro:user_42",
            telegram_payment_charge_id="sub_charge_1",
            provider_payment_charge_id="prov_sub_1",
            total_amount=390,
            is_recurring=False,
            is_first_recurring=True,
        )
        assert result["tokens_credited"] == 7200
        assert result["is_subscription"] is True

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
            payload="gift:mini:user_42",
            telegram_payment_charge_id="charge_gift",
            provider_payment_charge_id="prov_gift",
            total_amount=65,
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

        await credit_referral_bonus(
            users, payments, user_id=42, price_rub=1000, payment_id=1, provider_label="ЮKassa"
        )
        expense_call = payments.create_expense.call_args[0][0]
        assert "ЮKassa" in expense_call.description


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------


class TestGetActiveSubscription:
    async def test_returns_sub_info(self, mock_db: MagicMock) -> None:
        svc = StarsPaymentService(db=mock_db, admin_id=999)
        svc._payments = MagicMock()
        svc._payments.get_active_subscription = AsyncMock(
            return_value=MagicMock(
                package_name="pro",
                tokens_amount=7200,
                provider="stars",
                subscription_status="active",
                subscription_expires_at=None,
                telegram_payment_charge_id="charge_sub",
                id=10,
            )
        )
        result = await svc.get_active_subscription(42)
        assert result is not None
        assert result["package_name"] == "pro"
        assert result["provider"] == "stars"

    async def test_returns_none_when_no_sub(self, mock_db: MagicMock) -> None:
        svc = StarsPaymentService(db=mock_db, admin_id=999)
        svc._payments = MagicMock()
        svc._payments.get_active_subscription = AsyncMock(return_value=None)
        result = await svc.get_active_subscription(42)
        assert result is None


class TestCancelSubscription:
    async def test_cancel_returns_provider_info(self, mock_db: MagicMock) -> None:
        svc = StarsPaymentService(db=mock_db, admin_id=999)
        svc._payments = MagicMock()
        svc._payments.get_active_subscription = AsyncMock(
            return_value=MagicMock(
                id=10,
                provider="stars",
                telegram_payment_charge_id="charge_cancel",
            )
        )
        svc._payments.update = AsyncMock()

        result = await svc.cancel_subscription(42)
        assert result is not None
        assert result["provider"] == "stars"
        assert result["charge_id"] == "charge_cancel"

    async def test_cancel_no_sub_returns_none(self, mock_db: MagicMock) -> None:
        svc = StarsPaymentService(db=mock_db, admin_id=999)
        svc._payments = MagicMock()
        svc._payments.get_active_subscription = AsyncMock(return_value=None)
        result = await svc.cancel_subscription(42)
        assert result is None


# ---------------------------------------------------------------------------
# Display formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_tariffs_text_contains_balance(self, service: StarsPaymentService) -> None:
        text = service.format_tariffs_text(1500)
        assert "1500" in text
        assert "Тарифы" in text

    def test_package_text_contains_tokens(self, service: StarsPaymentService) -> None:
        text = service.format_package_text("mini")
        assert "1000" in text

    def test_subscription_text_contains_price(self, service: StarsPaymentService) -> None:
        text = service.format_subscription_text("pro")
        assert "6000" in text

    def test_subscription_manage_text(self, service: StarsPaymentService) -> None:
        text = service.format_subscription_manage_text({
            "package_name": "pro",
            "tokens_per_month": 7200,
            "price_rub": 6000,
            "provider": "stars",
            "status": "active",
            "expires_at": None,
            "charge_id": "ch",
            "payment_id": 1,
        })
        assert "Stars" in text

    def test_cancel_confirm_text(self, service: StarsPaymentService) -> None:
        text = service.format_cancel_confirm_text({
            "expires_at": None,
            "provider": "stars",
        })
        assert "Отменить" in text

    def test_payment_link_text_package(self, service: StarsPaymentService) -> None:
        text = service.format_payment_link_text("mini")
        assert "1000" in text

    def test_payment_link_text_subscription(self, service: StarsPaymentService) -> None:
        text = service.format_payment_link_text("pro", is_subscription=True)
        assert "6000" in text

    def test_subscription_link_text(self, service: StarsPaymentService) -> None:
        text = service.format_subscription_link_text("pro")
        assert "390" in text
