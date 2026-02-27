"""Profile, notification toggles, referral program, legal docs, account deletion (UX_TOOLBOX section 14)."""

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.helpers import safe_message
from bot.texts.legal import (
    PRIVACY_POLICY_CHUNKS,
    TERMS_OF_SERVICE_CHUNKS,
)
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import User, UserUpdate
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

    text = (
        f"<b>Профиль</b>\n\n"
        f"Баланс: <b>{user.balance}</b> токенов\n\n"
        f"Проектов: {stats['project_count']}\n"
        f"Категорий: {stats['category_count']}\n"
        f"Расписаний: {stats['schedule_count']}\n"
        f"Рефералов: {stats['referral_count']}\n\n"
    )

    if stats["posts_per_week"] > 0:
        text += (
            f"Прогноз расхода:\n~{stats['tokens_per_week']} токенов/неделю\n~{stats['tokens_per_month']} токенов/месяц"
        )

    await callback.message.edit_text(text, reply_markup=profile_kb())
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

    text = "<b>Уведомления</b>\n\nНажмите для переключения:"

    await callback.message.edit_text(
        text,
        reply_markup=notifications_kb(
            notify_publications=user.notify_publications,
            notify_balance=user.notify_balance,
            notify_news=user.notify_news,
        ),
    )
    await callback.answer()


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

    # Build update with toggled value for the specific notification field
    if field == "publications":
        update = UserUpdate(notify_publications=not user.notify_publications)
    elif field == "balance":
        update = UserUpdate(notify_balance=not user.notify_balance)
    else:  # "news"
        update = UserUpdate(notify_news=not user.notify_news)

    repo = UsersRepository(db)
    await repo.update(user.id, update)

    # Invalidate user cache so next navigation shows fresh data (best-effort)
    try:
        await redis.delete(CacheKeys.user_cache(user.id))
    except Exception:
        log.warning("user_cache_invalidate_failed", user_id=user.id)

    # Refresh user object for keyboard
    updated_user = await repo.get_by_id(user.id)
    if updated_user is None:
        await callback.answer("Ошибка обновления", show_alert=True)
        return

    text = "<b>Уведомления</b>\n\nНажмите для переключения:"

    await callback.message.edit_text(
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

    settings = get_settings()
    token_service = TokenService(db=db, admin_ids=settings.admin_ids)
    referral_count = await UsersRepository(db).get_referral_count(user.id)
    referral_earned = await token_service.get_referral_bonus_total(user.id)

    bot_info = await callback.bot.me()  # type: ignore[union-attr]
    link = f"https://t.me/{bot_info.username}?start=referrer_{user.id}"

    text = (
        f"<b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и получайте <b>10%</b> от каждой их покупки!\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Рефералов: <b>{referral_count}</b>\n"
        f"Заработано: <b>{referral_earned}</b> токенов"
    )

    await callback.message.edit_text(text, reply_markup=referral_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Legal documents: /privacy, /terms
# ---------------------------------------------------------------------------


async def _send_legal_chunks(message: Message, chunks: list[str]) -> None:
    """Send a multi-part legal document as sequential messages."""
    for chunk in chunks:
        await message.answer(chunk)


@router.message(Command("privacy"))
async def cmd_privacy(message: Message) -> None:
    """Send privacy policy text (152-FZ compliant)."""
    await _send_legal_chunks(message, PRIVACY_POLICY_CHUNKS)


@router.message(Command("terms"))
async def cmd_terms(message: Message) -> None:
    """Send terms of service / public offer text."""
    await _send_legal_chunks(message, TERMS_OF_SERVICE_CHUNKS)


@router.callback_query(F.data == "profile:privacy")
async def cb_privacy(callback: CallbackQuery) -> None:
    """Privacy policy via inline button in profile."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    # Send as new messages (legal text is too long for editMessageText)
    await _send_legal_chunks(callback.message, PRIVACY_POLICY_CHUNKS)
    await callback.answer()


@router.callback_query(F.data == "profile:terms")
async def cb_terms(callback: CallbackQuery) -> None:
    """Terms of service via inline button in profile."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    await _send_legal_chunks(callback.message, TERMS_OF_SERVICE_CHUNKS)
    await callback.answer()


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
        "<b>Удаление аккаунта</b>\n\n"
        "Будут безвозвратно удалены:\n"
        "- Все проекты и категории\n"
        "- Все подключения к платформам\n"
        "- Все расписания автопубликации\n"
        "- Активные превью статей\n\n"
        "Токены и история платежей будут анонимизированы.\n\n"
        "<b>Это действие необратимо.</b>"
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
        await callback.message.edit_text(
            "Ваш аккаунт и все данные удалены.\n\n"
            "Вы можете начать заново с /start"
        )
        log.info("delete_account_success", user_id=user.id)
    else:
        await callback.message.edit_text(
            "Произошла ошибка при удалении аккаунта. "
            "Обратитесь в поддержку.",
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

    await callback.message.edit_text(
        "Удаление аккаунта отменено.",
        reply_markup=delete_account_cancelled_kb(),
    )
    await callback.answer()
