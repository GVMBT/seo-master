"""YooKassa payment service — create payments, process webhooks.

Source of truth: API_CONTRACTS.md §2.4-§2.5.
Uses httpx directly (not yookassa SDK) for async compatibility.
Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from ipaddress import ip_address, ip_network
from typing import Any

import httpx
import structlog

from db.client import SupabaseClient
from db.models import PaymentCreate, PaymentUpdate, TokenExpenseCreate
from db.repositories.payments import PaymentsRepository
from db.repositories.users import UsersRepository
from services.payments.packages import (
    PACKAGES,
    SUBSCRIPTIONS,
)
from services.payments.stars import credit_referral_bonus

log = structlog.get_logger()

# YooKassa API
_API_BASE = "https://api.yookassa.ru/v3"

# IP whitelist for webhook verification (API_CONTRACTS.md §2.4)
YOOKASSA_IP_WHITELIST = [
    "185.71.76.0/27",
    "185.71.77.0/27",
    "77.75.153.0/25",
    "77.75.156.11/32",
    "77.75.156.35/32",
    "77.75.154.128/25",
    "2a02:5180::/32",
]
_NETWORKS = [ip_network(n) for n in YOOKASSA_IP_WHITELIST]


def verify_ip(client_ip: str) -> bool:
    """Check if client IP is in YooKassa whitelist."""
    try:
        addr = ip_address(client_ip)
    except ValueError:
        return False
    return any(addr in net for net in _NETWORKS)


class YooKassaPaymentService:
    """YooKassa payment and subscription business logic.

    Uses YooKassa REST API v3 via shared httpx.AsyncClient.
    """

    def __init__(
        self,
        db: SupabaseClient,
        http_client: httpx.AsyncClient,
        shop_id: str,
        secret_key: str,
        return_url: str,
        admin_id: int,
    ) -> None:
        self._db = db
        self._http = http_client
        self._shop_id = shop_id
        self._secret_key = secret_key
        self._return_url = return_url
        self._users = UsersRepository(db)
        self._payments = PaymentsRepository(db)
        self._admin_id = admin_id

    # ------------------------------------------------------------------
    # Create payment (API_CONTRACTS.md §2.4)
    # ------------------------------------------------------------------

    async def create_payment(
        self,
        user_id: int,
        package_name: str,
        is_subscription: bool = False,
    ) -> str | None:
        """Create YooKassa payment and return confirmation URL.

        Returns None on API error.
        """
        if is_subscription:
            sub = SUBSCRIPTIONS.get(package_name)
            if not sub:
                return None
            amount = str(sub.price_rub)
            tokens = sub.tokens_per_month
            description = f"Подписка {package_name.capitalize()} — {tokens} токенов/мес"
        else:
            pkg = PACKAGES.get(package_name)
            if not pkg:
                return None
            amount = str(pkg.price_rub)
            tokens = pkg.tokens
            description = f"Пакет {package_name.capitalize()} — {tokens} токенов"

        body: dict[str, Any] = {
            "amount": {"value": f"{amount}.00", "currency": "RUB"},
            "confirmation": {
                "type": "redirect",
                "return_url": self._return_url,
            },
            "metadata": {
                "user_id": str(user_id),
                "package_name": package_name,
                "tokens_amount": str(tokens),
                "is_subscription": str(is_subscription).lower(),
            },
            "description": description,
        }
        if is_subscription:
            body["save_payment_method"] = True
            body["metadata"]["is_subscription"] = "true"

        try:
            resp = await self._http.post(
                f"{_API_BASE}/payments",
                json=body,
                auth=(self._shop_id, self._secret_key),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": str(uuid.uuid4()),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            url: str = data["confirmation"]["confirmation_url"]
            return url
        except httpx.HTTPError:
            log.exception("yookassa_create_payment_error", user_id=user_id, package=package_name)
            return None

    # ------------------------------------------------------------------
    # Webhook processing
    # ------------------------------------------------------------------

    async def process_webhook(self, event: str, obj: dict) -> None:
        """Route webhook event to appropriate handler."""
        if event == "payment.succeeded":
            await self._process_succeeded(obj)
        elif event == "payment.canceled":
            await self._process_canceled(obj)
        elif event == "refund.succeeded":
            await self._process_refund(obj)
        else:
            log.warning("yookassa_unknown_event", webhook_event=event)

    async def _process_succeeded(self, obj: dict) -> None:
        """Handle payment.succeeded — credit tokens, record payment."""
        yookassa_id = obj["id"]

        # Idempotency check
        existing = await self._payments.get_by_yookassa_payment_id(yookassa_id)
        if existing:
            log.warning("yookassa_duplicate_payment", yookassa_id=yookassa_id)
            return

        metadata = obj.get("metadata", {})
        user_id = int(metadata.get("user_id", 0))
        package_name = metadata.get("package_name", "")
        tokens_amount = int(metadata.get("tokens_amount", 0))
        is_subscription = metadata.get("is_subscription") == "true"
        is_renewal = metadata.get("is_renewal") == "true"

        if not user_id or not tokens_amount:
            log.error("yookassa_invalid_metadata", yookassa_id=yookassa_id, metadata=metadata)
            return

        # 1. Credit tokens
        new_balance = await self._users.credit_balance(user_id, tokens_amount)

        # 2. Create payment record
        amount_val = obj.get("amount", {}).get("value", "0")
        payment = await self._payments.create(PaymentCreate(
            user_id=user_id,
            provider="yookassa",
            tokens_amount=tokens_amount,
            package_name=package_name,
            amount_rub=Decimal(amount_val),
            is_subscription=is_subscription,
        ))

        update = PaymentUpdate(
            status="completed",
            yookassa_payment_id=yookassa_id,
        )

        # Save payment_method_id for recurring (API_CONTRACTS.md §2.5 step 2)
        pm = obj.get("payment_method", {})
        if pm.get("saved") and pm.get("id"):
            update.yookassa_payment_method_id = pm["id"]

        if is_subscription:
            update.subscription_status = "active"
            update.subscription_expires_at = datetime.now(UTC) + timedelta(days=30)

        await self._payments.update(payment.id, update)

        # 3. Record token expense
        label = "Продление подписки" if is_renewal else ("Подписка" if is_subscription else "Покупка")
        await self._payments.create_expense(TokenExpenseCreate(
            user_id=user_id,
            amount=tokens_amount,
            operation_type="purchase" if not is_subscription else "subscription",
            description=f"{label} {package_name.capitalize()} ({tokens_amount} токенов) — ЮKassa",
        ))

        # 4. Referral bonus
        await credit_referral_bonus(
            self._users, self._payments, user_id, int(Decimal(amount_val)), payment.id, "ЮKassa"
        )

        log.info(
            "yookassa_payment_succeeded",
            user_id=user_id,
            package=package_name,
            tokens=tokens_amount,
            new_balance=new_balance,
        )

    async def _process_canceled(self, obj: dict) -> None:
        """Handle payment.canceled — record failed payment.

        TODO G3: send user notification via Bot (needs Phase 9 notification mechanism).
        """
        yookassa_id = obj["id"]
        metadata = obj.get("metadata", {})
        user_id = int(metadata.get("user_id", 0))
        package_name = metadata.get("package_name", "")

        # Check if we created a pending payment for this
        existing = await self._payments.get_by_yookassa_payment_id(yookassa_id)
        if existing:
            await self._payments.update(existing.id, PaymentUpdate(status="failed"))
        elif user_id:
            # Create failed record for tracking (skip if user_id unknown)
            payment = await self._payments.create(PaymentCreate(
                user_id=user_id,
                provider="yookassa",
                tokens_amount=0,
                package_name=package_name,
            ))
            await self._payments.update(payment.id, PaymentUpdate(
                status="failed",
                yookassa_payment_id=yookassa_id,
            ))
        else:
            log.warning("yookassa_canceled_no_user_id", yookassa_id=yookassa_id)

        log.info("yookassa_payment_canceled", user_id=user_id, yookassa_id=yookassa_id)

    async def _process_refund(self, obj: dict) -> None:
        """Handle refund.succeeded — debit tokens, may go negative."""
        payment_id = obj.get("payment_id", "")
        if not payment_id:
            log.error("yookassa_refund_no_payment_id", obj=obj)
            return

        payment = await self._payments.get_by_yookassa_payment_id(payment_id)
        if not payment:
            log.error("yookassa_refund_payment_not_found", payment_id=payment_id)
            return

        # Debit tokens — allows negative balance (API_CONTRACTS.md §2.3)
        tokens_to_debit = payment.tokens_amount
        await self._users.force_debit_balance(payment.user_id, tokens_to_debit)

        await self._payments.update(payment.id, PaymentUpdate(status="refunded"))
        await self._payments.create_expense(TokenExpenseCreate(
            user_id=payment.user_id,
            amount=-tokens_to_debit,
            operation_type="refund",
            description=f"Возврат за {payment.package_name or 'платёж'} — ЮKassa",
        ))

        log.info("yookassa_refund_processed", user_id=payment.user_id, tokens=tokens_to_debit)

    # ------------------------------------------------------------------
    # Recurring payments (API_CONTRACTS.md §2.5 step 3)
    # ------------------------------------------------------------------

    async def renew_subscription(
        self,
        user_id: int,
        payment_method_id: str,
        package_name: str,
    ) -> bool:
        """Create auto-payment for subscription renewal.

        Called by QStash cron job. Result comes via webhook.
        Returns True if payment was created successfully.
        """
        sub = SUBSCRIPTIONS.get(package_name)
        if not sub:
            log.error("renew_unknown_subscription", package=package_name)
            return False

        body: dict[str, Any] = {
            "amount": {"value": f"{sub.price_rub}.00", "currency": "RUB"},
            "payment_method_id": payment_method_id,
            "metadata": {
                "user_id": str(user_id),
                "package_name": package_name,
                "tokens_amount": str(sub.tokens_per_month),
                "is_subscription": "true",
                "is_renewal": "true",
            },
            "description": f"Продление подписки {package_name.capitalize()}",
        }

        try:
            resp = await self._http.post(
                f"{_API_BASE}/payments",
                json=body,
                auth=(self._shop_id, self._secret_key),
                headers={
                    "Content-Type": "application/json",
                    "Idempotence-Key": f"renew_{user_id}_{package_name}_{datetime.now(UTC).date().isoformat()}",
                },
            )
            resp.raise_for_status()
            log.info("yookassa_renewal_created", user_id=user_id, package=package_name)
            return True
        except httpx.HTTPError:
            log.exception("yookassa_renewal_error", user_id=user_id, package=package_name)
            return False

    # ------------------------------------------------------------------
    # Subscription management
    # ------------------------------------------------------------------

    async def cancel_subscription(self, user_id: int) -> bool:
        """Cancel active YooKassa subscription.

        Does NOT call YooKassa API — just stops creating payments (§2.5 step 4).
        Subscription remains active until subscription_expires_at.
        """
        payment = await self._payments.get_active_subscription(user_id)
        if not payment or payment.provider != "yookassa":
            return False

        await self._payments.update(payment.id, PaymentUpdate(
            subscription_status="cancelled",
        ))
        log.info("yookassa_subscription_cancelled", user_id=user_id, payment_id=payment.id)
        return True

