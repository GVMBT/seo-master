"""Telegram payment handlers: pre-checkout, successful payment, refund (API_CONTRACTS section 2.1-2.3)."""

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


# Refund handler MUST be registered BEFORE successful_payment handler.
# Both filters match on message attributes; refunded_payment is more specific.
@router.message(F.refunded_payment)
async def refunded_payment_handler(
    message: Message,
    user: User,
    db: SupabaseClient,
) -> None:
    """Process Stars refund — debit tokens from user (API_CONTRACTS §2.3).

    When Telegram processes a Stars refund, the bot receives a message
    with refunded_payment (RefundedPayment). We must debit the credited
    tokens to prevent financial loss. Balance may go negative.
    """
    refund = message.refunded_payment
    if refund is None:
        return

    settings = get_settings()
    stars_svc = StarsPaymentService(db=db, admin_ids=settings.admin_ids)

    result = await stars_svc.process_refund(
        user_id=message.from_user.id,  # type: ignore[union-attr]
        telegram_payment_charge_id=refund.telegram_payment_charge_id,
    )

    if result.get("already_refunded"):
        log.warning("refund_duplicate", charge_id=refund.telegram_payment_charge_id)
        return

    if result.get("error"):
        log.error(
            "refund_processing_error",
            charge_id=refund.telegram_payment_charge_id,
            error=result["error"],
        )
        return

    new_balance = result["new_balance"]
    tokens_debited = result["tokens_debited"]

    log.info(
        "stars_refund_handled",
        user_id=message.from_user.id,  # type: ignore[union-attr]
        tokens_debited=tokens_debited,
        new_balance=new_balance,
    )

    # Notify user about negative balance if applicable (API_CONTRACTS §2.3)
    if isinstance(new_balance, int) and new_balance < 0:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Пополнить", callback_data="nav:tokens")],
            ]
        )
        await message.answer(
            f"\u26a0\ufe0f Возврат Stars обработан.\n\n"
            f"\U0001f4b0 Списано: <b>{tokens_debited}</b> токенов\n"
            f"Ваш баланс отрицателен ({new_balance} токенов) из-за возврата средств.\n"
            f"Пополните баланс для продолжения работы.",
            reply_markup=kb,
        )


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
        log.error("payment_processing_error", error=result["error"])
        await message.answer("\u26a0\ufe0f Ошибка обработки платежа. Попробуйте позже.")
        return

    tokens = result["tokens_credited"]
    new_balance = result["new_balance"]

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Написать статью", callback_data="pipeline:article:start")],
            [
                InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard"),
                InlineKeyboardButton(text="Пополнить ещё", callback_data="nav:tokens"),
            ],
        ]
    )
    await message.answer(
        f"\U0001f389 Оплата прошла успешно!\n\n"
        f"\U0001f4b0 Начислено: <b>{tokens}</b> токенов\n"
        f"\U0001f4b0 Баланс: <b>{new_balance}</b> токенов",
        reply_markup=kb,
    )
