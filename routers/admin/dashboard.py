"""Router: admin dashboard (F20). Monitoring, API costs, user stats."""

from datetime import UTC, datetime

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import User
from db.repositories.payments import PaymentsRepository
from db.repositories.users import UsersRepository
from keyboards.category import admin_dashboard_kb
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="admin_dashboard")


# ---------------------------------------------------------------------------
# Admin guard
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Stats builder
# ---------------------------------------------------------------------------


async def _build_admin_stats(db: SupabaseClient) -> str:
    """Build admin dashboard text with user/revenue stats."""
    users_repo = UsersRepository(db)
    payments_repo = PaymentsRepository(db)

    total_users = await users_repo.count_all()
    active_7d = await users_repo.count_active(days=7)
    active_30d = await users_repo.count_active(days=30)
    revenue_7d = await payments_repo.sum_revenue(days=7)
    revenue_30d = await payments_repo.sum_revenue(days=30)

    return (
        "<b>Админ-панель</b>\n\n"
        f"Пользователей: {total_users}\n"
        f"Активных 7д: {active_7d}\n"
        f"Активных 30д: {active_30d}\n\n"
        f"Доход 7д: {revenue_7d} руб.\n"
        f"Доход 30д: {revenue_30d} руб."
    )


# ---------------------------------------------------------------------------
# Entry: reply button "АДМИНКА"
# ---------------------------------------------------------------------------


@router.message(F.text == "АДМИНКА")
async def btn_admin_main(message: Message, user: User, db: SupabaseClient) -> None:
    """Admin panel entry from reply keyboard."""
    if not _is_admin(user):
        await message.answer("Нет доступа.")
        return

    text = await _build_admin_stats(db)
    await message.answer(text, reply_markup=admin_dashboard_kb().as_markup())


# ---------------------------------------------------------------------------
# Callback entry: admin:main
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:main")
async def cb_admin_main(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Admin dashboard via callback."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    if not _is_admin(user):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    text = await _build_admin_stats(db)
    await msg.edit_text(text, reply_markup=admin_dashboard_kb().as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:monitoring")
async def cb_admin_monitoring(callback: CallbackQuery, user: User, db: SupabaseClient, redis: RedisClient) -> None:
    """System monitoring: Redis ping, DB status."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    if not _is_admin(user):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    lines = ["<b>Мониторинг</b>\n"]

    # Redis ping
    try:
        await redis.ping()
        lines.append("Redis: OK")
    except Exception:
        lines.append("Redis: ОШИБКА")

    # DB check
    try:
        count = await UsersRepository(db).count_all()
        lines.append(f"PostgreSQL: OK ({count} пользователей)")
    except Exception:
        lines.append("PostgreSQL: ОШИБКА")

    lines.append(f"\nВремя: {datetime.now(tz=UTC).strftime('%Y-%m-%d %H:%M UTC')}")

    await msg.edit_text("\n".join(lines), reply_markup=admin_dashboard_kb().as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# API costs
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:costs")
async def cb_admin_costs(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show API cost breakdown by operation type."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    if not _is_admin(user):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    repo = PaymentsRepository(db)
    expenses_7d = await repo.get_expenses_summary(days=7)
    expenses_30d = await repo.get_expenses_summary(days=30)

    lines = ["<b>Затраты API</b>\n"]

    lines.append("<b>За 7 дней:</b>")
    if expenses_7d:
        for op_type, total in sorted(expenses_7d.items()):
            lines.append(f"  {op_type}: {total} ток.")
    else:
        lines.append("  Нет данных")

    lines.append("\n<b>За 30 дней:</b>")
    if expenses_30d:
        for op_type, total in sorted(expenses_30d.items()):
            lines.append(f"  {op_type}: {total} ток.")
    else:
        lines.append("  Нет данных")

    await msg.edit_text("\n".join(lines), reply_markup=admin_dashboard_kb().as_markup())
    await callback.answer()
