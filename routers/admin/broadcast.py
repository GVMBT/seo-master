"""Router: admin broadcast messaging (F20)."""

import asyncio
import html

import structlog
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import User
from db.repositories.users import UsersRepository
from keyboards.admin import admin_broadcast_audience_kb, admin_broadcast_confirm_kb, admin_dashboard_kb
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="admin_broadcast")


# ---------------------------------------------------------------------------
# FSM
# ---------------------------------------------------------------------------


class BroadcastFSM(StatesGroup):
    text = State()
    confirm = State()


# ---------------------------------------------------------------------------
# Admin guard
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# Start broadcast
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:broadcast")
async def cb_broadcast_start(callback: CallbackQuery, user: User) -> None:
    """Show audience selection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    if not _is_admin(user):
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await msg.edit_text(
        "Выберите аудиторию для рассылки:",
        reply_markup=admin_broadcast_audience_kb().as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Audience selection
# ---------------------------------------------------------------------------

_AUDIENCE_LABELS: dict[str, str] = {
    "all": "Все пользователи",
    "active_7d": "Активные за 7 дней",
    "active_30d": "Активные за 30 дней",
    "paid": "С покупками",
}


@router.callback_query(F.data.regexp(r"^admin:bc:(all|active_7d|active_30d|paid)$"))
async def cb_broadcast_audience(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Store audience type and prompt for message text."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    if not _is_admin(user):
        await callback.answer("Нет доступа.", show_alert=True)
        return

    audience = callback.data.split(":")[-1]  # type: ignore[union-attr]

    repo = UsersRepository(db)
    user_ids = await repo.get_ids_by_audience(audience)
    count = len(user_ids)

    # E26: auto-reset any active FSM before entering BroadcastFSM
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(BroadcastFSM.text)
    await state.update_data(audience=audience, user_count=count)

    label = _AUDIENCE_LABELS.get(audience, audience)
    await msg.edit_text(f"Аудитория: {label} ({count} чел.)\n\nВведите текст сообщения:")
    await callback.answer()


# ---------------------------------------------------------------------------
# Message text input
# ---------------------------------------------------------------------------


@router.message(BroadcastFSM.text, F.text)
async def fsm_broadcast_text(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Preview broadcast message and ask for confirmation."""
    if not _is_admin(user):
        await state.clear()
        return

    text = message.text.strip()  # type: ignore[union-attr]
    if not text:
        await message.answer("Введите непустое сообщение.")
        return

    if len(text) > 4000:
        await message.answer("Сообщение слишком длинное. Максимум 4000 символов.")
        return

    data = await state.get_data()
    count = data.get("user_count", 0)
    audience = data.get("audience", "all")

    await state.set_state(BroadcastFSM.confirm)
    await state.update_data(broadcast_text=text)

    preview = html.escape(text[:500])
    await message.answer(
        f"<b>Превью рассылки:</b>\n\n{preview}\n\nАудитория: {audience} ({count} чел.)\nОтправить?",
        reply_markup=admin_broadcast_confirm_kb(count).as_markup(),
    )


# ---------------------------------------------------------------------------
# Confirm & send
# ---------------------------------------------------------------------------


@router.callback_query(BroadcastFSM.confirm, F.data == "admin:bc:confirm")
async def cb_broadcast_confirm(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Send broadcast to all target users."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    if not _is_admin(user):
        await state.clear()
        await callback.answer("Нет доступа.", show_alert=True)
        return

    data = await state.get_data()
    broadcast_text = data.get("broadcast_text", "")
    audience = data.get("audience", "all")

    if not broadcast_text:
        await state.clear()
        await callback.answer("Нет текста для отправки.", show_alert=True)
        return

    repo = UsersRepository(db)
    user_ids = await repo.get_ids_by_audience(audience)

    await state.clear()
    await msg.edit_text(f"Рассылка запущена ({len(user_ids)} чел.)...")
    await callback.answer()

    bot: Bot = callback.bot  # type: ignore[assignment]
    sent = 0
    failed = 0

    # Split text into 4096-char chunks (Telegram API limit)
    _TG_MSG_LIMIT = 4096
    chunks = [broadcast_text[i : i + _TG_MSG_LIMIT] for i in range(0, len(broadcast_text), _TG_MSG_LIMIT)]

    for uid in user_ids:
        try:
            for chunk in chunks:
                await bot.send_message(uid, chunk)
            sent += 1
        except Exception:
            failed += 1
            log.debug("broadcast_send_failed", user_id=uid)
        # Rate limit: ~30 msg/sec (Telegram limit)
        await asyncio.sleep(0.035)

    await msg.answer(
        f"Рассылка завершена.\nОтправлено: {sent}\nОшибок: {failed}",
        reply_markup=admin_dashboard_kb().as_markup(),
    )
