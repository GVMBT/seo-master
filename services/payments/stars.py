"""Telegram Stars payment service — invoice creation, payment processing.

Source of truth: API_CONTRACTS.md §2.1-§2.3, PRD.md §5.4.
Zero dependencies on Telegram/Aiogram — returns data dicts for router to use.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import structlog

from db.client import SupabaseClient
from db.models import PaymentCreate, PaymentUpdate, TokenExpenseCreate
from db.repositories.payments import PaymentsRepository
from db.repositories.users import UsersRepository
from services.payments.packages import (
    PACKAGES,
    REFERRAL_BONUS_PERCENT,
    SUBSCRIPTIONS,
)

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Shared referral bonus logic (F19, §31) — used by Stars and YooKassa
# ---------------------------------------------------------------------------


async def credit_referral_bonus(
    users: UsersRepository,
    payments: PaymentsRepository,
    user_id: int,
    price_rub: int,
    payment_id: int,
    provider_label: str = "",
) -> None:
    """Credit referral bonus to referrer if exists (F19).

    Bonus = REFERRAL_BONUS_PERCENT% of price_rub.
    Credited on EVERY successful_payment including subscription renewals (§31).
    """
    user = await users.get_by_id(user_id)
    if not user or not user.referrer_id:
        return

    bonus = price_rub * REFERRAL_BONUS_PERCENT // 100
    if bonus <= 0:
        return

    referrer = await users.get_by_id(user.referrer_id)
    if not referrer:
        return

    await users.credit_balance(user.referrer_id, bonus)
    desc = f"Реферальный бонус от пользователя {user_id}"
    if provider_label:
        desc += f" ({provider_label})"
    await payments.create_expense(
        TokenExpenseCreate(
            user_id=user.referrer_id,
            amount=bonus,
            operation_type="referral",
            description=desc,
        )
    )
    await payments.update(payment_id, PaymentUpdate(referral_bonus_credited=True))
    log.info("referral_bonus_credited", referrer_id=user.referrer_id, buyer_id=user_id, bonus=bonus)


class StarsPaymentService:
    """Handles Stars purchase and subscription business logic.

    Router calls bot.send_invoice / bot.create_invoice_link with params
    returned by this service. Processing callbacks also go through here.
    """

    def __init__(self, db: SupabaseClient, admin_ids: list[int]) -> None:
        self._db = db
        self._users = UsersRepository(db)
        self._payments = PaymentsRepository(db)
        self._admin_ids = admin_ids

    # ------------------------------------------------------------------
    # Invoice parameter builders (router passes these to Bot API)
    # ------------------------------------------------------------------

    def build_invoice_params(self, user_id: int, package_name: str) -> dict:
        """Build parameters for bot.send_invoice (one-time purchase).

        Returns dict with: title, description, payload, currency, prices.
        """
        pkg = PACKAGES[package_name]
        bonus_text = f" + {pkg.bonus} бонусных" if pkg.bonus else ""
        return {
            "title": f"Пакет {pkg.name.capitalize()} — {pkg.tokens} токенов",
            "description": f"{pkg.tokens - pkg.bonus}{bonus_text} токенов",
            "payload": f"purchase:{package_name}:user_{user_id}",
            "currency": "XTR",
            "prices": [{"label": pkg.name.capitalize(), "amount": pkg.stars}],
            "provider_token": "",
        }

    def build_subscription_params(self, user_id: int, sub_name: str) -> dict:
        """Build parameters for bot.create_invoice_link (subscription).

        Returns dict with: title, description, payload, currency, prices,
        subscription_period.
        """
        sub = SUBSCRIPTIONS[sub_name]
        return {
            "title": f"Подписка {sub.name.capitalize()} — {sub.tokens_per_month} токенов/мес",
            "description": "Автопродление каждые 30 дней",
            "payload": f"sub:{sub_name}:user_{user_id}",
            "currency": "XTR",
            "prices": [{"label": sub.name.capitalize(), "amount": sub.stars}],
            "provider_token": "",
            "subscription_period": sub.period_seconds,
        }

    # ------------------------------------------------------------------
    # Pre-checkout validation (API_CONTRACTS.md §2.1 step 3)
    # ------------------------------------------------------------------

    def validate_pre_checkout(self, user_id: int, payload: str) -> tuple[bool, str]:
        """Validate pre_checkout_query payload.

        Returns (ok, error_message). error_message is empty when ok=True.
        """
        parts = payload.split(":")
        if len(parts) != 3:
            return False, "Некорректный формат платежа."

        action, name, user_part = parts

        # Verify user_id matches
        expected_user = f"user_{user_id}"
        if user_part != expected_user:
            log.warning("pre_checkout_user_mismatch", payload=payload, user_id=user_id)
            return False, "Ошибка идентификации пользователя."

        if action == "purchase":
            if name not in PACKAGES:
                return False, "Пакет не найден."
        elif action == "sub":
            if name not in SUBSCRIPTIONS:
                return False, "Подписка не найдена."
        else:
            return False, "Неизвестный тип платежа."

        return True, ""

    # ------------------------------------------------------------------
    # Successful payment processing (API_CONTRACTS.md §2.1 step 4)
    # ------------------------------------------------------------------

    async def process_successful_payment(
        self,
        user_id: int,
        payload: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str,
        total_amount: int,
        is_recurring: bool = False,
        is_first_recurring: bool = False,
        subscription_expiration_date: int | None = None,
    ) -> dict:
        """Process successful Stars payment — credit tokens, record payment.

        Returns dict with: tokens_credited, new_balance, package_name, is_subscription.
        """
        # Idempotency: check duplicate by charge_id (API_CONTRACTS.md §2.3)
        existing = await self._payments.get_by_telegram_charge_id(telegram_payment_charge_id)
        if existing:
            log.warning("duplicate_payment", charge_id=telegram_payment_charge_id)
            return {
                "tokens_credited": 0,
                "new_balance": 0,
                "package_name": existing.package_name,
                "is_duplicate": True,
            }

        parts = payload.split(":")
        action, name = parts[0], parts[1]

        if action == "purchase":
            return await self._process_purchase(
                user_id,
                name,
                telegram_payment_charge_id,
                provider_payment_charge_id,
                total_amount,
            )
        elif action == "sub":
            return await self._process_subscription(
                user_id,
                name,
                telegram_payment_charge_id,
                provider_payment_charge_id,
                total_amount,
                is_recurring,
                is_first_recurring,
                subscription_expiration_date,
            )
        else:
            log.error("unknown_payment_action", action=action, payload=payload)
            return {"tokens_credited": 0, "error": "Unknown action"}

    async def _process_purchase(
        self,
        user_id: int,
        package_name: str,
        charge_id: str,
        provider_charge_id: str,
        stars_amount: int,
    ) -> dict:
        """Process one-time purchase."""
        pkg = PACKAGES.get(package_name)
        if not pkg:
            log.error("unknown_package", package_name=package_name)
            return {"tokens_credited": 0, "error": f"Unknown package: {package_name}"}

        # 1. Credit tokens (atomic RPC)
        new_balance = await self._users.credit_balance(user_id, pkg.tokens)

        # 2. Create payment record
        payment = await self._payments.create(
            PaymentCreate(
                user_id=user_id,
                provider="stars",
                tokens_amount=pkg.tokens,
                package_name=package_name,
                amount_rub=Decimal(str(pkg.price_rub)),
                stars_amount=stars_amount,
            )
        )
        await self._payments.update(
            payment.id,
            PaymentUpdate(
                status="completed",
                telegram_payment_charge_id=charge_id,
                provider_payment_charge_id=provider_charge_id,
            ),
        )

        # 3. Record token expense
        await self._payments.create_expense(
            TokenExpenseCreate(
                user_id=user_id,
                amount=pkg.tokens,
                operation_type="purchase",
                description=f"Пакет {package_name.capitalize()} ({pkg.tokens} токенов)",
            )
        )

        # 4. Referral bonus (F19: 10% of price_rub to referrer)
        await credit_referral_bonus(self._users, self._payments, user_id, pkg.price_rub, payment.id)

        log.info(
            "stars_purchase_completed",
            user_id=user_id,
            package=package_name,
            tokens=pkg.tokens,
            stars=stars_amount,
        )

        return {
            "tokens_credited": pkg.tokens,
            "new_balance": new_balance,
            "package_name": package_name,
            "is_duplicate": False,
        }

    async def _process_subscription(
        self,
        user_id: int,
        sub_name: str,
        charge_id: str,
        provider_charge_id: str,
        stars_amount: int,
        is_recurring: bool,
        is_first_recurring: bool,
        subscription_expiration_date: int | None = None,
    ) -> dict:
        """Process subscription payment (first or renewal)."""
        sub = SUBSCRIPTIONS.get(sub_name)
        if not sub:
            log.error("unknown_subscription", sub_name=sub_name)
            return {"tokens_credited": 0, "error": f"Unknown subscription: {sub_name}"}

        # 1. Credit tokens
        new_balance = await self._users.credit_balance(user_id, sub.tokens_per_month)

        # 2. Create payment record
        payment = await self._payments.create(
            PaymentCreate(
                user_id=user_id,
                provider="stars",
                tokens_amount=sub.tokens_per_month,
                package_name=sub_name,
                amount_rub=Decimal(str(sub.price_rub)),
                stars_amount=stars_amount,
                is_subscription=True,
            )
        )
        update = PaymentUpdate(
            status="completed",
            telegram_payment_charge_id=charge_id,
            provider_payment_charge_id=provider_charge_id,
            subscription_status="active",
        )
        # G1: save subscription_expiration_date from Telegram Stars (API_CONTRACTS.md §2.2)
        if subscription_expiration_date:
            update.subscription_expires_at = datetime.fromtimestamp(subscription_expiration_date, tz=UTC)
        await self._payments.update(payment.id, update)

        # 3. Record token expense
        label = "Продление подписки" if is_recurring and not is_first_recurring else "Подписка"
        await self._payments.create_expense(
            TokenExpenseCreate(
                user_id=user_id,
                amount=sub.tokens_per_month,
                operation_type="subscription",
                description=f"{label} {sub_name.capitalize()} ({sub.tokens_per_month} токенов)",
            )
        )

        # 4. Referral bonus on every successful_payment including renewals (§31)
        await credit_referral_bonus(self._users, self._payments, user_id, sub.price_rub, payment.id)

        log.info(
            "stars_subscription_completed",
            user_id=user_id,
            subscription=sub_name,
            tokens=sub.tokens_per_month,
            is_recurring=is_recurring,
            is_first=is_first_recurring,
        )

        return {
            "tokens_credited": sub.tokens_per_month,
            "new_balance": new_balance,
            "package_name": sub_name,
            "is_subscription": True,
            "is_duplicate": False,
        }

    # ------------------------------------------------------------------
    # Subscription management (API_CONTRACTS.md §2.2)
    # ------------------------------------------------------------------

    async def get_active_subscription(self, user_id: int) -> dict | None:
        """Get active subscription info for display.

        Returns None if no active subscription.
        """
        payment = await self._payments.get_active_subscription(user_id)
        if not payment:
            return None

        sub = SUBSCRIPTIONS.get(payment.package_name or "")
        return {
            "package_name": payment.package_name,
            "tokens_per_month": sub.tokens_per_month if sub else payment.tokens_amount,
            "price_rub": sub.price_rub if sub else 0,
            "stars": sub.stars if sub else 0,
            "provider": payment.provider,
            "status": payment.subscription_status,
            "expires_at": payment.subscription_expires_at,
            "charge_id": payment.telegram_payment_charge_id,
            "payment_id": payment.id,
        }

    async def cancel_subscription(self, user_id: int) -> dict | None:
        """Cancel subscription: update DB status, return info for Telegram API call.

        Returns dict with provider, charge_id (needed for Stars Bot API call)
        or None if no active subscription found.
        """
        payment = await self._payments.get_active_subscription(user_id)
        if not payment:
            return None
        await self._payments.update(payment.id, PaymentUpdate(subscription_status="cancelled"))
        log.info("subscription_cancelled", user_id=user_id, provider=payment.provider)
        return {
            "provider": payment.provider,
            "charge_id": payment.telegram_payment_charge_id,
        }

    # ------------------------------------------------------------------
    # Display helpers (return formatted strings for router)
    # ------------------------------------------------------------------

    def format_tariffs_text(self, balance: int) -> str:
        """Format main tariffs screen text."""
        return (
            f"<b>Тарифы</b>\n\n"
            f"Ваш баланс: <b>{balance}</b> токенов\n\n"
            f"<b>Справочник стоимости:</b>\n"
            f"Статья на сайт (2000 слов + 4 картинки): ~320 токенов\n"
            f"Пост в соцсети (текст + картинка): ~40 токенов\n"
            f"Подбор 100 ключевых фраз: 100 токенов\n"
            f"Технический аудит сайта: 50 токенов"
        )

    def format_package_text(self, package_name: str) -> str:
        """Format package info for payment method selection."""
        pkg = PACKAGES[package_name]
        bonus_text = f" + {pkg.bonus} бонусных" if pkg.bonus else ""
        return (
            f"<b>Пакет {pkg.name.capitalize()}</b>\n\n"
            f"Токенов: {pkg.tokens}{bonus_text}\n"
            f"Цена: {pkg.price_rub} руб.\n\n"
            f"Выберите способ оплаты:"
        )

    def format_subscription_text(self, sub_name: str) -> str:
        """Format subscription info for payment method selection."""
        sub = SUBSCRIPTIONS[sub_name]
        return (
            f"<b>Подписка {sub.name.capitalize()}</b>\n\n"
            f"Токенов в месяц: {sub.tokens_per_month}\n"
            f"Цена: {sub.price_rub} руб/мес\n"
            f"Автопродление каждые 30 дней.\n\n"
            f"Выберите способ оплаты:"
        )

    def format_subscription_manage_text(self, sub_info: dict) -> str:
        """Format active subscription details for management screen."""
        expires = sub_info["expires_at"]
        expires_str = expires.strftime("%d.%m.%Y") if expires else "не определена"
        provider_str = "Stars" if sub_info["provider"] == "stars" else "ЮKassa"
        status_str = "Активна" if sub_info["status"] == "active" else (sub_info["status"] or "")
        return (
            f"<b>Моя подписка</b>\n\n"
            f"Тариф: {(sub_info['package_name'] or '').capitalize()}\n"
            f"Токенов в месяц: {sub_info['tokens_per_month']}\n"
            f"Способ оплаты: {provider_str}\n"
            f"Статус: {status_str}\n"
            f"Действует до: {expires_str}\n"
        )

    def format_cancel_confirm_text(self, sub_info: dict) -> str:
        """Format cancel confirmation text."""
        expires = sub_info["expires_at"]
        expires_str = expires.strftime("%d.%m.%Y") if expires else "дата неизвестна"
        return (
            f"Подписка будет действовать до {expires_str}.\nПосле этого автопродление отключится.\n\nОтменить подписку?"
        )

    def format_payment_link_text(self, package_name: str, is_subscription: bool = False) -> str:
        """Format text for YooKassa payment link screen."""
        if is_subscription:
            sub = SUBSCRIPTIONS[package_name]
            return (
                f"Подписка <b>{sub.name.capitalize()}</b> — {sub.price_rub} руб/мес\n\n"
                f"Нажмите для перехода на страницу оплаты.\n"
                f"Карта будет сохранена для автопродления."
            )
        pkg = PACKAGES[package_name]
        return (
            f"Оплата пакета <b>{pkg.name.capitalize()}</b> — {pkg.price_rub} руб.\n\n"
            f"Нажмите кнопку для перехода на страницу оплаты."
        )

    def format_subscription_link_text(self, sub_name: str) -> str:
        """Format text for Stars subscription link screen."""
        sub = SUBSCRIPTIONS[sub_name]
        return (
            f"Подписка <b>{sub.name.capitalize()}</b>\n"
            f"{sub.tokens_per_month} токенов/мес — {sub.stars} Stars/мес\n\n"
            f"Нажмите кнопку для оформления:"
        )
