"""Router: Stars pre_checkout_query and successful_payment handlers.

Thin layer — all business logic in services/payments/stars.py.
Source of truth: API_CONTRACTS.md §2.1 (steps 3-4).
"""

import structlog
from aiogram import Bot, F, Router
from aiogram.types import Message, PreCheckoutQuery

from db.models import User
from services.payments.stars import StarsPaymentService

log = structlog.get_logger()

router = Router(name="payments")


# ---------------------------------------------------------------------------
# Pre-checkout validation (API_CONTRACTS.md §2.1 step 3)
# ---------------------------------------------------------------------------


@router.pre_checkout_query()
async def on_pre_checkout_query(
    query: PreCheckoutQuery,
    stars_service: StarsPaymentService,
) -> None:
    """Validate Stars pre-checkout: payload format, user ownership, package existence."""
    ok, error_msg = stars_service.validate_pre_checkout(query.from_user.id, query.invoice_payload)
    if ok:
        await query.answer(ok=True)
    else:
        log.warning(
            "pre_checkout_rejected",
            user_id=query.from_user.id,
            reason=error_msg,
        )
        await query.answer(ok=False, error_message=error_msg)


# ---------------------------------------------------------------------------
# Successful payment processing (API_CONTRACTS.md §2.1 step 4)
# ---------------------------------------------------------------------------


@router.message(F.successful_payment)
async def on_successful_payment(
    message: Message,
    user: User,
    bot: Bot,
    stars_service: StarsPaymentService,
) -> None:
    """Process successful Stars payment — credit tokens via service, notify user."""
    sp = message.successful_payment
    if sp is None:
        return

    result = await stars_service.process_successful_payment(
        user_id=user.id,
        payload=sp.invoice_payload,
        telegram_payment_charge_id=sp.telegram_payment_charge_id,
        provider_payment_charge_id=sp.provider_payment_charge_id,
        total_amount=sp.total_amount,
        is_recurring=sp.is_recurring or False,
        is_first_recurring=sp.is_first_recurring or False,
        subscription_expiration_date=sp.subscription_expiration_date,
    )

    if result.get("is_duplicate"):
        await message.answer("Платёж уже обработан.")
        return

    if result.get("error"):
        log.error("payment_processing_error", error=result["error"], user_id=user.id)
        await message.answer("Ошибка обработки платежа. Обратитесь в поддержку.")
        return

    tokens = result["tokens_credited"]
    balance = result["new_balance"]
    await message.answer(
        f"Оплата прошла успешно!\nНачислено: <b>{tokens}</b> токенов\nБаланс: <b>{balance}</b> токенов"
    )
