"""Tests for db/repositories/payments.py."""


import pytest

from db.models import Payment, PaymentCreate, PaymentUpdate, TokenExpense, TokenExpenseCreate
from db.repositories.payments import PaymentsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def payment_row() -> dict:
    return {
        "id": 1,
        "user_id": 123456789,
        "provider": "stars",
        "status": "completed",
        "telegram_payment_charge_id": "charge_123",
        "provider_payment_charge_id": "prov_123",
        "stars_amount": 100,
        "yookassa_payment_id": None,
        "yookassa_payment_method_id": None,
        "package_name": "starter",
        "tokens_amount": 5000,
        "amount_rub": "499.00",
        "is_subscription": False,
        "subscription_id": None,
        "subscription_status": None,
        "subscription_expires_at": None,
        "referral_bonus_credited": False,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def expense_row() -> dict:
    return {
        "id": 1,
        "user_id": 123456789,
        "amount": -320,
        "operation_type": "article",
        "description": "Article generation",
        "ai_model": "anthropic/claude-sonnet-4.5",
        "input_tokens": 1000,
        "output_tokens": 2000,
        "cost_usd": "0.015",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> PaymentsRepository:
    return PaymentsRepository(mock_db)  # type: ignore[arg-type]


class TestCreatePayment:
    async def test_create(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, payment_row: dict
    ) -> None:
        mock_db.set_response("payments", MockResponse(data=[payment_row]))
        data = PaymentCreate(
            user_id=123456789, provider="stars", tokens_amount=5000, package_name="starter"
        )
        payment = await repo.create(data)
        assert isinstance(payment, Payment)
        assert payment.tokens_amount == 5000


class TestUpdatePayment:
    async def test_partial_update(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, payment_row: dict
    ) -> None:
        updated = {**payment_row, "status": "completed"}
        mock_db.set_response("payments", MockResponse(data=[updated]))
        payment = await repo.update(1, PaymentUpdate(status="completed"))
        assert payment is not None
        assert payment.status == "completed"

    async def test_empty_update_returns_none(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient
    ) -> None:
        result = await repo.update(1, PaymentUpdate())
        assert result is None


class TestGetByUser:
    async def test_returns_list(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, payment_row: dict
    ) -> None:
        mock_db.set_response("payments", MockResponse(data=[payment_row]))
        payments = await repo.get_by_user(123456789)
        assert len(payments) == 1


class TestGetActiveSubscription:
    async def test_found(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, payment_row: dict
    ) -> None:
        sub_row = {**payment_row, "is_subscription": True, "subscription_status": "active"}
        mock_db.set_response("payments", MockResponse(data=[sub_row]))
        sub = await repo.get_active_subscription(123456789)
        assert sub is not None
        assert sub.is_subscription is True

    async def test_not_found(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("payments", MockResponse(data=[]))
        assert await repo.get_active_subscription(123456789) is None


class TestGetByTelegramChargeId:
    async def test_found(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, payment_row: dict
    ) -> None:
        mock_db.set_response("payments", MockResponse(data=payment_row))
        payment = await repo.get_by_telegram_charge_id("charge_123")
        assert payment is not None
        assert payment.telegram_payment_charge_id == "charge_123"

    async def test_not_found(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("payments", MockResponse(data=None))
        assert await repo.get_by_telegram_charge_id("nonexistent") is None


class TestGetByYookassaPaymentId:
    async def test_found(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, payment_row: dict
    ) -> None:
        row = {**payment_row, "yookassa_payment_id": "yoo_abc123"}
        mock_db.set_response("payments", MockResponse(data=row))
        payment = await repo.get_by_yookassa_payment_id("yoo_abc123")
        assert payment is not None

    async def test_not_found(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("payments", MockResponse(data=None))
        assert await repo.get_by_yookassa_payment_id("nonexistent") is None


class TestCreateExpense:
    async def test_create(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, expense_row: dict
    ) -> None:
        mock_db.set_response("token_expenses", MockResponse(data=[expense_row]))
        data = TokenExpenseCreate(
            user_id=123456789, amount=-320, operation_type="article"
        )
        expense = await repo.create_expense(data)
        assert isinstance(expense, TokenExpense)
        assert expense.amount == -320


class TestGetExpensesByUser:
    async def test_returns_list(
        self, repo: PaymentsRepository, mock_db: MockSupabaseClient, expense_row: dict
    ) -> None:
        mock_db.set_response("token_expenses", MockResponse(data=[expense_row]))
        expenses = await repo.get_expenses_by_user(123456789)
        assert len(expenses) == 1
        assert expenses[0].operation_type == "article"
