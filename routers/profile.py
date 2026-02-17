"""Profile, notification toggles, referral program (UX_TOOLBOX section 14)."""

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.config import get_settings
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.users import UsersRepository
from keyboards.inline import notifications_kb, profile_kb, referral_kb
from services.tokens import TokenService

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
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
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
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
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
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
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
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
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
