"""Profile, notification toggles, referral program, legal docs, account deletion (UX_TOOLBOX section 14)."""

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from bot.assets import edit_screen
from bot.config import get_settings
from bot.helpers import safe_edit_text, safe_message
from bot.texts.emoji import E
from bot.texts.legal import PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL
from bot.texts.screens import Screen
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import User
from db.repositories.payments import PaymentsRepository
from db.repositories.users import UsersRepository
from keyboards.inline import (
    delete_account_cancelled_kb,
    delete_account_confirm_kb,
    notifications_kb,
    profile_kb,
    referral_kb,
)
from services.scheduler import SchedulerService
from services.tokens import TokenService
from services.users import UsersService

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# Profile main
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:profile")
async def nav_profile(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Profile screen with balance and stats."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    token_service = TokenService(db=db, admin_ids=settings.admin_ids)
    stats = await token_service.get_profile_stats(user)

    # Registration date
    reg_str = user.created_at.strftime("%d.%m.%Y") if user.created_at else "---"

    # Last completed payment
    pay_repo = PaymentsRepository(db)
    last_payments = await pay_repo.get_by_user(user.id, limit=1)
    last_completed = next((p for p in last_payments if p.status == "completed"), None)

    s = Screen(E.USER, "ПРОФИЛЬ")
    s.blank()
    s.line(f"{E.WALLET} Баланс: <b>{user.balance}</b> токенов")
    s.blank()
    s.field(E.FOLDER, "Проектов", stats["project_count"])
    s.field(E.HASHTAG, "Категорий", stats["category_count"])
    s.field(E.SCHEDULE, "Расписаний", stats["schedule_count"])
    s.field(E.TRANSFER, "Рефералов", stats["referral_count"])

    if stats["posts_per_week"] > 0:
        s.blank()
        s.line(
            f"{E.CHART} ~{stats['tokens_per_week']} ток/нед"
            f"  \u00b7  ~{stats['tokens_per_month']} ток/мес"
        )

    # Footer with registration and payment info
    s.separator()
    s.line(f"Регистрация: {reg_str}")
    if last_completed and last_completed.created_at:
        pay_date = last_completed.created_at.strftime("%d.%m.%Y")
        pay_amount = int(last_completed.amount_rub) if last_completed.amount_rub else last_completed.tokens_amount
        s.line(f"Последняя оплата: {pay_date} ({pay_amount} руб.)")

    text = s.build()

    await edit_screen(msg, "profile.png", text, reply_markup=profile_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "profile:notifications")
async def show_notifications(
    callback: CallbackQuery,
    user: User,
) -> None:
    """Show notification toggle screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    text = _build_notifications_text()

    await safe_edit_text(
        msg,
        text,
        reply_markup=notifications_kb(
            notify_publications=user.notify_publications,
            notify_balance=user.notify_balance,
            notify_news=user.notify_news,
        ),
    )
    await callback.answer()


def _build_notifications_text() -> str:
    """Build notification screen text."""
    return (
        Screen(E.BELL, "УВЕДОМЛЕНИЯ")
        .blank()
        .line("<i>Выберите типы уведомлений:</i>")
        .blank()
        .line("\u2713 Публикации \u2014 статус автопубликаций")
        .line("\u2713 Баланс \u2014 пополнения и низкий баланс")
        .line("\u2717 Новости \u2014 обновления бота")
        .hint("Нажмите для переключения")
        .build()
    )


@router.callback_query(F.data.regexp(r"^profile:notify:(publications|balance|news)$"))
async def toggle_notification(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Toggle a notification setting."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    field = callback.data.split(":")[-1]  # type: ignore[union-attr]

    # Determine current value for the field being toggled
    current_value = {"publications": user.notify_publications, "balance": user.notify_balance}.get(
        field, user.notify_news
    )

    users_svc = UsersService(db=db)
    updated_user = await users_svc.toggle_notification(user.id, field, current_value, redis)

    if updated_user is None:
        await callback.answer("Ошибка обновления. Попробуйте позже.", show_alert=True)
        return

    text = _build_notifications_text()

    await safe_edit_text(
        msg,
        text,
        reply_markup=notifications_kb(
            notify_publications=updated_user.notify_publications,
            notify_balance=updated_user.notify_balance,
            notify_news=updated_user.notify_news,
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Referral
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "profile:referral")
async def show_referral(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Referral program info screen with inline referral link."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    import html as html_mod

    settings = get_settings()
    token_service = TokenService(db=db, admin_ids=settings.admin_ids)
    users_repo = UsersRepository(db)
    referral_count = await users_repo.get_referral_count(user.id)
    referral_earned = await token_service.get_referral_bonus_total(user.id)

    bot_info = await callback.bot.me()  # type: ignore[union-attr]
    link = f"https://t.me/{bot_info.username}?start=referrer_{user.id}"

    s = Screen(E.TRANSFER, "РЕФЕРАЛЬНАЯ ПРОГРАММА")
    s.blank()
    s.line("Приглашайте друзей и получайте <b>10%</b> от каждой их покупки!")
    s.blank()
    s.line(f"Ваша ссылка:\n<code>{link}</code>")
    s.blank()
    s.line(f"{E.USER} Рефералов: <b>{referral_count}</b>")
    s.line(f"{E.WALLET} Заработано: <b>{referral_earned}</b> токенов")

    # Show referral list (up to 10)
    _DISPLAY_LIMIT = 10
    referrals = await users_repo.get_referrals(user.id, limit=_DISPLAY_LIMIT)
    if referrals:
        s.blank()
        s.line("<b>Ваши рефералы:</b>")
        for idx, ref in enumerate(referrals, 1):
            ref_name = html_mod.escape(ref.first_name or "Пользователь")
            ref_date = ref.created_at.strftime("%d.%m.%Y") if ref.created_at else "---"
            s.line(f"  {idx}. {ref_name} \u2014 {ref_date}")
        if referral_count > _DISPLAY_LIMIT:
            s.line(f"  ...и ещё {referral_count - _DISPLAY_LIMIT}")

    s.hint("Скопируйте ссылку и отправьте друзьям")
    text = s.build()

    await edit_screen(msg, "referral.png", text, reply_markup=referral_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Legal documents: /privacy, /terms
# ---------------------------------------------------------------------------


@router.message(Command("privacy"))
async def cmd_privacy(message: Message) -> None:
    """Send privacy policy link (152-FZ compliant)."""
    await message.answer(
        f'<a href="{PRIVACY_POLICY_URL}">Политика конфиденциальности</a>',
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(Command("terms"))
async def cmd_terms(message: Message) -> None:
    """Send terms of service / public offer link."""
    await message.answer(
        f'<a href="{TERMS_OF_SERVICE_URL}">Публичная оферта</a>',
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ---------------------------------------------------------------------------
# Account deletion (152-FZ compliance)
# ---------------------------------------------------------------------------


@router.message(Command("delete_account"))
async def cmd_delete_account(
    message: Message,
    user: User,
) -> None:
    """Show account deletion warning with confirmation buttons."""
    text = (
        Screen(E.WARNING, "УДАЛЕНИЕ АККАУНТА")
        .blank()
        .line("Будут безвозвратно удалены:")
        .line("  \u2022 Все проекты и категории")
        .line("  \u2022 Все подключения к платформам")
        .line("  \u2022 Все расписания автопубликации")
        .line("  \u2022 Активные превью статей")
        .blank()
        .line("Токены и история платежей будут анонимизированы.")
        .blank()
        .line("<b>Это действие необратимо.</b>")
        .build()
    )
    await message.answer(text, reply_markup=delete_account_confirm_kb())


@router.callback_query(F.data == "account:delete:confirm")
async def confirm_delete_account(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    scheduler_service: SchedulerService,
) -> None:
    """Execute account deletion after user confirmation."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    service = UsersService(db=db)

    log.info("delete_account_initiated", user_id=user.id)

    result = await service.delete_account(
        user_id=user.id,
        redis=redis,
        scheduler_service=scheduler_service,
        admin_ids=settings.admin_ids,
    )

    if result.success:
        await safe_edit_text(msg, "Ваш аккаунт и все данные удалены.\n\nВы можете начать заново с /start")
        log.info("delete_account_success", user_id=user.id)
    else:
        await safe_edit_text(msg, 
            "Произошла ошибка при удалении аккаунта. Обратитесь в поддержку.",
            reply_markup=delete_account_cancelled_kb(),
        )
        log.error(
            "delete_account_failed",
            user_id=user.id,
            errors=result.errors,
        )

    await callback.answer()


@router.callback_query(F.data == "account:delete:cancel")
async def cancel_delete_account(
    callback: CallbackQuery,
) -> None:
    """Cancel account deletion."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await safe_edit_text(msg, 
        "Удаление отменено.",
        reply_markup=delete_account_cancelled_kb(),
    )
    await callback.answer()
