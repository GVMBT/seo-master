"""Admin panel: stats, monitoring, API costs, broadcast (UX_TOOLBOX section 16)."""

import asyncio

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_message
from bot.service_factory import AdminServiceFactory
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import admin_panel_kb, broadcast_audience_kb, broadcast_confirm_kb

log = structlog.get_logger()
router = Router()


class BroadcastFSM(StatesGroup):
    audience = State()
    text = State()
    confirm = State()


# ---------------------------------------------------------------------------
# Admin guard helper
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    """Check if user has admin role."""
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:panel")
async def admin_panel(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
    state: FSMContext,
) -> None:
    """Show admin panel with stats."""
    if not _is_admin(user):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # Clear any active FSM (like broadcast)
    await state.clear()

    admin_svc = admin_service_factory(db)
    total_users = await admin_svc.get_user_count()

    text = f"<b>\U0001f6e1 Админ-панель</b>\n\nПользователей: {total_users}\n"

    await msg.edit_text(text, reply_markup=admin_panel_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Monitoring
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:monitoring")
async def admin_monitoring(
    callback: CallbackQuery, user: User, db: SupabaseClient, admin_service_factory: AdminServiceFactory
) -> None:
    """Show service health status."""
    if not _is_admin(user):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # Quick health check: try DB query
    admin_svc = admin_service_factory(db)
    db_ok = await admin_svc.check_db_health()
    db_status = "\u2705" if db_ok else "\u274c"

    text = f"<b>Мониторинг</b>\n\nБаза данных: {db_status}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u2b05\ufe0f К панели", callback_data="admin:panel")],
        ]
    )
    await msg.edit_text(text, reply_markup=kb)
    await callback.answer()


# ---------------------------------------------------------------------------
# API costs
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:api_costs")
async def admin_api_costs(
    callback: CallbackQuery, user: User, db: SupabaseClient, admin_service_factory: AdminServiceFactory
) -> None:
    """Show API cost summary for 7/30/90 days."""
    if not _is_admin(user):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    admin_svc = admin_service_factory(db)
    cost_7d, cost_30d, cost_90d = await asyncio.gather(
        admin_svc.get_api_costs(7),
        admin_svc.get_api_costs(30),
        admin_svc.get_api_costs(90),
    )

    text = f"<b>Затраты API</b>\n\n7 дней: ${cost_7d:.2f}\n30 дней: ${cost_30d:.2f}\n90 дней: ${cost_90d:.2f}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u2b05\ufe0f К панели", callback_data="admin:panel")],
        ]
    )
    await msg.edit_text(text, reply_markup=kb)
    await callback.answer()


# ---------------------------------------------------------------------------
# Broadcast FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """Start broadcast FSM."""
    if not _is_admin(user):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(BroadcastFSM.audience)
    await msg.edit_text(
        "<b>Рассылка</b>\n\nВыберите аудиторию:",
        reply_markup=broadcast_audience_kb(),
    )
    await callback.answer()


_AUDIENCE_LABELS: dict[str, str] = {
    "all": "Все пользователи",
    "active_7d": "Активные 7 дней",
    "active_30d": "Активные 30 дней",
    "paid": "Оплатившие",
}


@router.callback_query(
    BroadcastFSM.audience,
    F.data.regexp(r"^broadcast:audience:(all|active_7d|active_30d|paid)$"),
)
async def broadcast_audience(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
    state: FSMContext,
) -> None:
    """Select audience, show count, ask for text."""
    if not _is_admin(user):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    audience_key = str(callback.data).split(":")[-1]

    # Count audience using service
    admin_svc = admin_service_factory(db)
    user_ids = await admin_svc.get_audience_ids(audience_key)
    count = len(user_ids)

    await state.update_data(broadcast_audience=audience_key, broadcast_count=count)
    await state.set_state(BroadcastFSM.text)

    await msg.edit_text(
        f"<b>Рассылка</b>\n\n"
        f"Аудитория: {_AUDIENCE_LABELS.get(audience_key, audience_key)}\n"
        f"Получателей: ~{count}\n\n"
        f"Отправьте текст сообщения:"
    )
    await callback.answer()


@router.message(BroadcastFSM.text)
async def broadcast_text(message: Message, user: User, state: FSMContext) -> None:
    """Receive broadcast text, show preview."""
    if not _is_admin(user):
        return
    if not message.text:
        await message.answer("Отправьте текст сообщения (не файл/стикер).")
        return

    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastFSM.confirm)

    data = await state.get_data()

    await message.answer(
        f"<b>Предпросмотр рассылки</b>\n\n"
        f"Получателей: ~{data['broadcast_count']}\n\n"
        f"<b>Текст рассылки:</b>\n{message.text}\n\n"
        f"Отправить?",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(BroadcastFSM.confirm, F.data == "broadcast:send")
async def broadcast_confirm(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
    state: FSMContext,
) -> None:
    """Execute broadcast with rate limiting."""
    if not _is_admin(user):
        await callback.answer("Доступ запрещён", show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    audience_key = data.get("broadcast_audience", "all")

    await state.clear()

    admin_svc = admin_service_factory(db)
    user_ids = await admin_svc.get_audience_ids(audience_key)

    await msg.edit_text(f"Рассылка запущена... (0/{len(user_ids)})")

    sent = 0
    failed = 0
    bot = callback.bot

    for uid in user_ids:
        try:
            if bot is not None:
                await bot.send_message(uid, text)
            sent += 1
        except Exception:
            log.warning("broadcast_send_failed", user_id=uid)
            failed += 1
        await asyncio.sleep(0.05)  # 50ms rate limit

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u2b05\ufe0f К панели", callback_data="admin:panel")],
        ]
    )
    await msg.edit_text(
        f"<b>Рассылка завершена</b>\n\nОтправлено: {sent}\nОшибок: {failed}",
        reply_markup=kb,
    )
    await callback.answer()
