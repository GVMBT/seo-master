"""Tests for services/payments/yookassa.py — YooKassa payment service.

Covers: IP whitelist, payment creation, webhook processing,
referral bonus, refund handling. No subscriptions in v2.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from services.payments.yookassa import YooKassaPaymentService, verify_ip

# ---------------------------------------------------------------------------
# IP whitelist
# ---------------------------------------------------------------------------


class TestVerifyIp:
    def test_valid_ip_in_whitelist(self) -> None:
        # 185.71.76.0/27 includes .1-.30
        assert verify_ip("185.71.76.1") is True

    def test_valid_ip_77_range(self) -> None:
        assert verify_ip("77.75.153.1") is True

    def test_ip_outside_whitelist(self) -> None:
        assert verify_ip("8.8.8.8") is False

    def test_invalid_ip_string(self) -> None:
        assert verify_ip("not-an-ip") is False

    def test_empty_ip(self) -> None:
        assert verify_ip("") is False

    def test_exact_network_address(self) -> None:
        assert verify_ip("185.71.76.0") is True

    def test_broadcast_address_outside(self) -> None:
        # 185.71.76.0/27 -> .0-.31
        assert verify_ip("185.71.76.32") is False


# ---------------------------------------------------------------------------
# Service fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_http() -> MagicMock:
    client = MagicMock()
    client.post = AsyncMock()
    return client


@pytest.fixture
def service(mock_db: MagicMock, mock_http: MagicMock) -> YooKassaPaymentService:
    return YooKassaPaymentService(
        db=mock_db,
        http_client=mock_http,
        shop_id="test_shop",
        secret_key="test_secret",
        return_url="https://example.com/return",
        admin_ids=[999],
    )


# ---------------------------------------------------------------------------
# Payment creation
# ---------------------------------------------------------------------------


class TestCreatePayment:
    async def test_creates_package_payment(self, service: YooKassaPaymentService, mock_http: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "confirmation": {"confirmation_url": "https://pay.yookassa.ru/123"},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        url = await service.create_payment(user_id=42, package_name="start")
        assert url == "https://pay.yookassa.ru/123"
        mock_http.post.assert_called_once()

    async def test_payment_body_has_correct_amount(self, service: YooKassaPaymentService, mock_http: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "confirmation": {"confirmation_url": "https://pay.yookassa.ru/456"},
        }
        mock_resp.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)

        await service.create_payment(user_id=42, package_name="standard")

        call_kwargs = mock_http.post.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json")
        assert body["amount"]["value"] == "1600.00"
        assert body["metadata"]["tokens_amount"] == "2000"

    async def test_returns_none_on_unknown_package(self, service: YooKassaPaymentService) -> None:
        url = await service.create_payment(user_id=42, package_name="nonexistent")
        assert url is None

    async def test_returns_none_on_http_error(self, service: YooKassaPaymentService, mock_http: MagicMock) -> None:
        mock_http.post = AsyncMock(side_effect=httpx.HTTPError("Connection error"))
        url = await service.create_payment(user_id=42, package_name="start")
        assert url is None


# ---------------------------------------------------------------------------
# Webhook processing
# ---------------------------------------------------------------------------


class TestProcessWebhook:
    @pytest.fixture
    def service_with_mocks(self, mock_db: MagicMock, mock_http: MagicMock) -> YooKassaPaymentService:
        svc = YooKassaPaymentService(
            db=mock_db,
            http_client=mock_http,
            shop_id="shop",
            secret_key="secret",
            return_url="https://example.com",
            admin_ids=[999],
        )
        svc._users = MagicMock()
        svc._users.credit_balance = AsyncMock(return_value=5000)
        svc._users.get_by_id = AsyncMock(return_value=MagicMock(referrer_id=None))
        svc._payments = MagicMock()
        svc._payments.get_by_yookassa_payment_id = AsyncMock(return_value=None)
        svc._payments.get_by_telegram_charge_id = AsyncMock(return_value=None)
        svc._payments.create = AsyncMock(return_value=MagicMock(id=1))
        svc._payments.update = AsyncMock()
        svc._payments.create_expense = AsyncMock()
        return svc

    async def test_payment_succeeded(self, service_with_mocks: YooKassaPaymentService) -> None:
        obj = {
            "id": "yk_pay_123",
            "metadata": {
                "user_id": "42",
                "package_name": "start",
                "tokens_amount": "500",
            },
            "amount": {"value": "500.00", "currency": "RUB"},
            "payment_method": {"saved": False},
        }
        await service_with_mocks.process_webhook("payment.succeeded", obj)
        service_with_mocks._users.credit_balance.assert_called_once_with(42, 500)
        service_with_mocks._payments.create.assert_called_once()

    async def test_payment_succeeded_idempotent(self, service_with_mocks: YooKassaPaymentService) -> None:
        """Duplicate yookassa_id should be skipped."""
        service_with_mocks._payments.get_by_yookassa_payment_id = AsyncMock(return_value=MagicMock(id=1))
        obj = {
            "id": "yk_dup",
            "metadata": {"user_id": "42", "package_name": "start", "tokens_amount": "500"},
            "amount": {"value": "500.00"},
        }
        await service_with_mocks.process_webhook("payment.succeeded", obj)
        service_with_mocks._users.credit_balance.assert_not_called()

    async def test_payment_canceled_returns_notification(self, service_with_mocks: YooKassaPaymentService) -> None:
        obj = {
            "id": "yk_cancel_1",
            "metadata": {"user_id": "42", "package_name": "start"},
        }
        result = await service_with_mocks.process_webhook("payment.canceled", obj)
        service_with_mocks._payments.create.assert_called_once()
        assert result is not None
        assert result["user_id"] == 42
        assert "Платёж отклонён" in result["text"]

    async def test_payment_canceled_no_user_returns_none(self, service_with_mocks: YooKassaPaymentService) -> None:
        obj = {
            "id": "yk_cancel_anon",
            "metadata": {},
        }
        result = await service_with_mocks.process_webhook("payment.canceled", obj)
        assert result is None

    async def test_refund_succeeded(self, service_with_mocks: YooKassaPaymentService) -> None:
        payment = MagicMock(id=5, user_id=42, tokens_amount=500, package_name="start", status="completed")
        service_with_mocks._payments.get_by_yookassa_payment_id = AsyncMock(return_value=payment)
        service_with_mocks._users.force_debit_balance = AsyncMock(return_value=-500)

        obj = {"payment_id": "yk_pay_123"}
        await service_with_mocks.process_webhook("refund.succeeded", obj)
        service_with_mocks._users.force_debit_balance.assert_called_once_with(42, 500)

    async def test_unknown_event_ignored(self, service_with_mocks: YooKassaPaymentService) -> None:
        """Unknown events should be logged but not raise."""
        await service_with_mocks.process_webhook("unknown.event", {})
        service_with_mocks._users.credit_balance.assert_not_called()
