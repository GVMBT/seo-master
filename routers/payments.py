"""Telegram payment handlers: pre-checkout validation and successful payment (API_CONTRACTS section 2.1-2.2)."""

import structlog
from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, PreCheckoutQuery

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
    ok, error_msg = StarsPaymentService.validate_pre_checkout(
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
    )

    if result.get("is_duplicate"):
        log.warning("duplicate_payment", charge_id=payment.telegram_payment_charge_id)
        return

    if result.get("error"):
        await message.answer(f"Ошибка обработки платежа: {result['error']}")
        return

    tokens = result["tokens_credited"]
    new_balance = result["new_balance"]

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать статью", callback_data="pipeline:article:start")],
            [
                InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
                InlineKeyboardButton(text="Пополнить ещё", callback_data="nav:tokens"),
            ],
        ]
    )
    await message.answer(
        f"Оплата прошла успешно!\n\nНачислено: <b>{tokens}</b> токенов\nБаланс: <b>{new_balance}</b> токенов",
        reply_markup=kb,
    )
