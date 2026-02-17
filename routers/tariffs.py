"""Tariff selection and payment initiation (UX_TOOLBOX section 15)."""

import httpx
import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.config import get_settings
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import payment_method_kb, tariffs_kb, yookassa_link_kb
from services.payments.packages import PACKAGES
from services.payments.stars import StarsPaymentService
from services.payments.yookassa import YooKassaPaymentService

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# Tariffs list
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:tokens")
async def nav_tokens(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Show tariffs screen with balance and package buttons."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    settings = get_settings()
    stars_svc = StarsPaymentService(db=None, admin_ids=settings.admin_ids)  # type: ignore[arg-type]
    text = stars_svc.format_tariffs_text(user.balance)

    await callback.message.edit_text(text, reply_markup=tariffs_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Package selection & payment method
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^tariff:(start|standard|pro):buy$"))
async def select_package(
    callback: CallbackQuery,
) -> None:
    """Show package details with payment method choice."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    package_name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if package_name not in PACKAGES:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    settings = get_settings()
    stars_svc = StarsPaymentService(db=None, admin_ids=settings.admin_ids)  # type: ignore[arg-type]
    text = stars_svc.format_package_text(package_name)

    await callback.message.edit_text(text, reply_markup=payment_method_kb(package_name))
    await callback.answer()


# ---------------------------------------------------------------------------
# Stars payment
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^tariff:(start|standard|pro):stars$"))
async def pay_with_stars(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Send Stars invoice via Telegram."""
    package_name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if package_name not in PACKAGES:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    settings = get_settings()
    stars_svc = StarsPaymentService(db=None, admin_ids=settings.admin_ids)  # type: ignore[arg-type]
    params = stars_svc.build_invoice_params(user_id=user.id, package_name=package_name)

    await callback.message.answer_invoice(**params)  # type: ignore[union-attr]
    await callback.answer()


# ---------------------------------------------------------------------------
# YooKassa payment
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^tariff:(start|standard|pro):yookassa$"))
async def pay_with_yookassa(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Create YooKassa payment and show link."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    package_name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if package_name not in PACKAGES:
        await callback.answer("Пакет не найден", show_alert=True)
        return

    settings = get_settings()

    # Check that YooKassa is configured (optional env vars)
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key.get_secret_value():
        await callback.answer("ЮKassa не настроена. Используйте Telegram Stars.", show_alert=True)
        return

    bot_info = await callback.bot.me()  # type: ignore[union-attr]
    return_url = f"https://t.me/{bot_info.username}"

    yookassa_svc = YooKassaPaymentService(
        db=db,
        http_client=http_client,
        shop_id=settings.yookassa_shop_id,
        secret_key=settings.yookassa_secret_key.get_secret_value(),
        return_url=return_url,
        admin_ids=settings.admin_ids,
    )

    url = await yookassa_svc.create_payment(user_id=user.id, package_name=package_name)
    if url is None:
        await callback.answer("Ошибка создания платежа. Попробуйте позже.", show_alert=True)
        return

    stars_svc = StarsPaymentService(db=None, admin_ids=settings.admin_ids)  # type: ignore[arg-type]
    text = stars_svc.format_payment_link_text(package_name)

    await callback.message.edit_text(text, reply_markup=yookassa_link_kb(url, package_name))
    await callback.answer()
