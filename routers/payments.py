"""Telegram payment handlers: pre-checkout validation and successful payment (API_CONTRACTS section 2.1-2.2)."""

import structlog
from aiogram import F, Router
from aiogram.types import Message, PreCheckoutQuery

from bot.config import get_settings
from db.client import SupabaseClient
from db.models import User
from services.payments.stars import StarsPaymentService

log = structlog.get_logger()
router = Router()


@router.pre_checkout_query()
async def pre_checkout_handler(
    query: PreCheckoutQuery,
    user: User,
) -> None:
    """Validate pre-checkout query (E10 duplicate protection)."""
    settings = get_settings()
    stars_svc = StarsPaymentService(db=None, admin_ids=settings.admin_ids)  # type: ignore[arg-type]

    ok, error_msg = stars_svc.validate_pre_checkout(
        user_id=query.from_user.id,
        payload=query.invoice_payload,
    )

    if ok:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message=error_msg)


@router.message(F.successful_payment)
async def successful_payment_handler(
    message: Message,
    user: User,
    db: SupabaseClient,
) -> None:
    """Process successful Stars payment."""
    payment = message.successful_payment
    if payment is None:
        return

    settings = get_settings()
    stars_svc = StarsPaymentService(db=db, admin_ids=settings.admin_ids)

    result = await stars_svc.process_successful_payment(
        user_id=message.from_user.id,  # type: ignore[union-attr]
        payload=payment.invoice_payload,
        telegram_payment_charge_id=payment.telegram_payment_charge_id,
        provider_payment_charge_id=payment.provider_payment_charge_id or "",
        total_amount=payment.total_amount,
        is_recurring=getattr(payment, "is_recurring", False),
        is_first_recurring=getattr(payment, "is_first_recurring", False),
    )

    if result.get("is_duplicate"):
        log.warning("duplicate_payment", charge_id=payment.telegram_payment_charge_id)
        return

    if result.get("error"):
        await message.answer(f"Ошибка обработки платежа: {result['error']}")
        return

    tokens = result["tokens_credited"]
    new_balance = result["new_balance"]

    await message.answer(
        f"Оплата прошла успешно!\n\n"
        f"Начислено: <b>{tokens}</b> токенов\n"
        f"Баланс: <b>{new_balance}</b> токенов"
    )
