"""Router: tariffs screen, package purchase, subscription management.

Thin layer — all business logic and text formatting in services/payments/.
"""

import structlog
from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, LabeledPrice
from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import User
from keyboards.inline import (
    package_list_kb,
    package_pay_kb,
    subscription_cancel_confirm_kb,
    subscription_manage_kb,
    subscription_pay_kb,
    tariffs_main_kb,
)
from routers._helpers import guard_callback_message
from services.payments.packages import PACKAGES, SUBSCRIPTIONS
from services.payments.stars import StarsPaymentService
from services.payments.yookassa import YooKassaPaymentService

log = structlog.get_logger()

router = Router(name="tariffs")


# ---------------------------------------------------------------------------
# Tariffs main screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "tariffs:main")
async def cb_tariffs_main(
    callback: CallbackQuery,
    user: User,
    stars_service: StarsPaymentService,
) -> None:
    """Show main tariffs screen."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    sub_info = await stars_service.get_active_subscription(user.id)
    text = stars_service.format_tariffs_text(user.balance)
    await msg.edit_text(text, reply_markup=tariffs_main_kb(has_subscription=sub_info is not None).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Package top-up flow
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "tariffs:topup")
async def cb_tariffs_topup(callback: CallbackQuery) -> None:
    """Show package list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text("<b>Выберите пакет:</b>", reply_markup=package_list_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^tariff:(\w+):select$"))
async def cb_package_select(
    callback: CallbackQuery,
    stars_service: StarsPaymentService,
) -> None:
    """Show payment method for selected package."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if name not in PACKAGES:
        await callback.answer("Пакет не найден.", show_alert=True)
        return
    text = stars_service.format_package_text(name)
    show_savings = PACKAGES[name].price_rub >= 15000
    await msg.edit_text(text, reply_markup=package_pay_kb(name, show_savings=show_savings).as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^tariff:(\w+):stars$"))
async def cb_pay_stars(
    callback: CallbackQuery,
    user: User,
    bot: Bot,
    stars_service: StarsPaymentService,
) -> None:
    """Send Stars invoice."""
    name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if name not in PACKAGES:
        await callback.answer("Пакет не найден.", show_alert=True)
        return
    p = stars_service.build_invoice_params(user.id, name)
    await bot.send_invoice(
        chat_id=callback.from_user.id,
        title=p["title"],
        description=p["description"],
        payload=p["payload"],
        currency=p["currency"],
        prices=[LabeledPrice(label=p["prices"][0]["label"], amount=p["prices"][0]["amount"])],
        provider_token=p["provider_token"],
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^tariff:(\w+):yk$"))
async def cb_pay_yookassa(
    callback: CallbackQuery,
    user: User,
    stars_service: StarsPaymentService,
    yookassa_service: YooKassaPaymentService,
) -> None:
    """Create YooKassa payment and show link."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if name not in PACKAGES:
        await callback.answer("Пакет не найден.", show_alert=True)
        return
    url = await yookassa_service.create_payment(user.id, name)
    if not url:
        await callback.answer("Ошибка создания платежа.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="Перейти к оплате", url=url)
    builder.button(text="Назад", callback_data=f"tariff:{name}:select")
    builder.adjust(1)
    await msg.edit_text(stars_service.format_payment_link_text(name), reply_markup=builder.as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Subscription flow
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sub:(\w+):select$"))
async def cb_subscription_select(
    callback: CallbackQuery,
    stars_service: StarsPaymentService,
) -> None:
    """Show payment method for subscription."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if name not in SUBSCRIPTIONS:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    text = stars_service.format_subscription_text(name)
    await msg.edit_text(text, reply_markup=subscription_pay_kb(name).as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^sub:(\w+):stars$"))
async def cb_subscribe_stars(
    callback: CallbackQuery,
    user: User,
    bot: Bot,
    stars_service: StarsPaymentService,
) -> None:
    """Create Stars subscription link."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if name not in SUBSCRIPTIONS:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    p = stars_service.build_subscription_params(user.id, name)
    link = await bot.create_invoice_link(
        title=p["title"],
        description=p["description"],
        payload=p["payload"],
        currency=p["currency"],
        prices=[LabeledPrice(label=p["prices"][0]["label"], amount=p["prices"][0]["amount"])],
        provider_token=p["provider_token"],
        subscription_period=p["subscription_period"],
    )
    builder = InlineKeyboardBuilder()
    builder.button(text="Оформить подписку ⭐", url=link)
    builder.button(text="Назад", callback_data=f"sub:{name}:select")
    builder.adjust(1)
    await msg.edit_text(stars_service.format_subscription_link_text(name), reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^sub:(\w+):yk$"))
async def cb_subscribe_yookassa(
    callback: CallbackQuery,
    user: User,
    stars_service: StarsPaymentService,
    yookassa_service: YooKassaPaymentService,
) -> None:
    """Create YooKassa subscription payment link."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    name = callback.data.split(":")[1]  # type: ignore[union-attr]
    if name not in SUBSCRIPTIONS:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    url = await yookassa_service.create_payment(user.id, name, is_subscription=True)
    if not url:
        await callback.answer("Ошибка создания платежа.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.button(text="Перейти к оплате", url=url)
    builder.button(text="Назад", callback_data=f"sub:{name}:select")
    builder.adjust(1)
    await msg.edit_text(
        stars_service.format_payment_link_text(name, is_subscription=True),
        reply_markup=builder.as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Subscription management
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "sub:manage")
async def cb_subscription_manage(
    callback: CallbackQuery,
    user: User,
    stars_service: StarsPaymentService,
) -> None:
    """Show active subscription details."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    sub_info = await stars_service.get_active_subscription(user.id)
    if not sub_info:
        await msg.edit_text("У вас нет активной подписки.", reply_markup=tariffs_main_kb().as_markup())
        await callback.answer()
        return
    text = stars_service.format_subscription_manage_text(sub_info)
    await msg.edit_text(text, reply_markup=subscription_manage_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data == "sub:cancel")
async def cb_subscription_cancel(
    callback: CallbackQuery,
    user: User,
    stars_service: StarsPaymentService,
) -> None:
    """Show cancel confirmation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    sub_info = await stars_service.get_active_subscription(user.id)
    if not sub_info:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    text = stars_service.format_cancel_confirm_text(sub_info)
    await msg.edit_text(text, reply_markup=subscription_cancel_confirm_kb().as_markup())
    await callback.answer()


@router.callback_query(F.data == "sub:cancel:confirm")
async def cb_subscription_cancel_confirm(
    callback: CallbackQuery,
    user: User,
    bot: Bot,
    stars_service: StarsPaymentService,
    yookassa_service: YooKassaPaymentService,
) -> None:
    """Cancel subscription: service updates DB, router calls provider API."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    result = await stars_service.cancel_subscription(user.id)
    if not result:
        await callback.answer("Подписка не найдена.", show_alert=True)
        return
    # Stars provider: call Bot API to stop auto-renewal
    if result["provider"] == "stars" and result["charge_id"]:
        try:
            await bot.edit_user_star_subscription(
                user_id=user.id,
                telegram_payment_charge_id=result["charge_id"],
                is_canceled=True,
            )
        except Exception:
            log.exception("stars_cancel_api_error", user_id=user.id)
    elif result["provider"] == "yookassa":
        await yookassa_service.cancel_subscription(user.id)
        # TODO Phase 9: cancel QStash renewal schedule for this subscription (G2)
    await msg.edit_text(
        "Подписка отменена. Она будет действовать до окончания текущего периода.",
        reply_markup=tariffs_main_kb().as_markup(),
    )
    await callback.answer("Подписка отменена.")
