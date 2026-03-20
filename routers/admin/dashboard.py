"""Admin panel: stats, API status, user management, broadcast (UX_TOOLBOX section 16)."""

import asyncio
import contextlib
import html

import httpx
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

from bot.assets import edit_screen
from bot.config import get_settings
from bot.exceptions import AppError
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import AdminServiceFactory
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import (
    admin_panel_kb,
    broadcast_audience_kb,
    broadcast_confirm_kb,
    user_actions_kb,
)
from services.admin import UserCard

log = structlog.get_logger()
router = Router()

_BROADCAST_PROGRESS_STEP = 25


class BroadcastFSM(StatesGroup):
    audience = State()
    text = State()
    confirm = State()


class UserLookupFSM(StatesGroup):
    waiting_input = State()


class BalanceAdjustFSM(StatesGroup):
    waiting_amount = State()


# ---------------------------------------------------------------------------
# Admin guard helper
# ---------------------------------------------------------------------------


def _is_admin(user: User) -> bool:
    """Check if user has admin role."""
    return user.role == "admin"


_BACK_TO_PANEL_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
    ]
)


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
    """Show admin panel with aggregated stats."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # Clear any active FSM (like broadcast or user lookup)
    await state.clear()

    admin_svc = admin_service_factory(db)
    stats = await admin_svc.get_panel_stats()

    text = (
        Screen(E.CROWN, S.ADMIN_TITLE)
        .blank()
        .line(f"Пользователей: {stats.total_users}")
        .line(f"Оплативших: {stats.paid_users}")
        .line(f"Проектов: {stats.total_projects}")
        .line(f"Публикаций (7д): {stats.publications_7d}")
        .line(f"Затраты API (30д): ${stats.revenue_30d:.2f}")
        .hint("Обновляется в реальном времени")
        .build()
    )

    await edit_screen(msg, "admin.png", text, reply_markup=admin_panel_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# API Status (replaces Monitoring)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:api_status")
async def admin_api_status(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    admin_service_factory: AdminServiceFactory,
) -> None:
    """Show all external service statuses with latency and credits."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    admin_svc = admin_service_factory(db)

    status = await admin_svc.get_api_status(
        redis=redis,
        http_client=http_client,
        openrouter_api_key=settings.openrouter_api_key.get_secret_value(),
        qstash_token=settings.qstash_token.get_secret_value(),
    )

    db_icon = E.CHECK if status.db_ok else E.CLOSE
    redis_icon = E.CHECK if status.redis_ok else E.CLOSE
    or_icon = E.CHECK if status.openrouter_ok else E.CLOSE
    qs_icon = E.CHECK if status.qstash_ok else E.CLOSE

    credits_str = f"${status.openrouter_credits:.2f}" if status.openrouter_credits is not None else "\u2014"

    text = (
        Screen(E.PULSE, S.MONITORING_TITLE)
        .section(E.AI_BRAIN, "AI")
        .line(f"{or_icon} OpenRouter (кредиты: {credits_str})")
        .line(f"{qs_icon} QStash")
        .section(E.DATABASE, "Инфраструктура")
        .line(f"{db_icon} База данных ({status.db_latency_ms}ms)")
        .line(f"{redis_icon} Redis ({status.redis_latency_ms}ms)")
        .separator()
        .field(E.SCHEDULE, "Активных расписаний", status.active_schedules)
        .hint("Нажмите для обновления статуса")
        .build()
    )

    await safe_edit_text(msg, text, reply_markup=_BACK_TO_PANEL_KB)
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
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
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

    text = (
        Screen(E.WALLET, S.API_COSTS_TITLE)
        .blank()
        .line(f"7 дней: ${cost_7d:.2f}")
        .line(f"30 дней: ${cost_30d:.2f}")
        .line(f"90 дней: ${cost_90d:.2f}")
        .hint("Суммы указаны в долларах США")
        .build()
    )

    await safe_edit_text(msg, text, reply_markup=_BACK_TO_PANEL_KB)
    await callback.answer()


# ---------------------------------------------------------------------------
# User lookup FSM
# ---------------------------------------------------------------------------


def _format_user_card(card: UserCard) -> str:
    """Format user card text for display with grouped sections."""
    name_parts = [p for p in (card.first_name, card.last_name) if p]
    name = html.escape(" ".join(name_parts)) or "\u2014"
    uname = f"@{html.escape(card.username)}" if card.username else "\u2014"
    activity = card.last_activity[:10] if card.last_activity else "\u2014"

    return (
        Screen(E.USER, f"ПОЛЬЗОВАТЕЛЬ #{card.user_id}")
        .blank()
        .line(f"Имя: {name}")
        .line(f"Username: {uname}")
        .blank()
        .field(E.WALLET, "Баланс", f"{card.balance} токенов")
        .line(f"Роль: {html.escape(card.role)}")
        .section(E.ANALYTICS, "Статистика")
        .line(f"  Проектов: {card.projects_count}")
        .line(f"  Публикаций: {card.publications_count}")
        .line(f"  Активность: {activity}")
        .build()
    )


@router.callback_query(F.data == "admin:user_lookup")
async def user_lookup_start(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """Start user lookup flow: ask for user_id or @username."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(UserLookupFSM.waiting_input)
    text = (
        Screen(E.USER, S.ADMIN_USER_LOOKUP_TITLE)
        .blank()
        .line(S.ADMIN_USER_LOOKUP_PROMPT)
        .hint("Поиск по Telegram ID или @username")
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=_BACK_TO_PANEL_KB)
    await callback.answer()


@router.message(UserLookupFSM.waiting_input)
async def user_lookup_input(
    message: Message,
    user: User,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
    state: FSMContext,
) -> None:
    """Parse input and show user card with action buttons."""
    if not _is_admin(user):
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(S.ADMIN_USER_INPUT_PROMPT)
        return

    admin_svc = admin_service_factory(db)

    # Parse: digits = user_id, otherwise = username
    if raw.isdigit():
        card = await admin_svc.lookup_user(user_id=int(raw))
    else:
        card = await admin_svc.lookup_user(username=raw)

    await state.clear()

    if card is None:
        await message.answer(S.ADMIN_USER_NOT_FOUND, reply_markup=_BACK_TO_PANEL_KB)
        return

    text = _format_user_card(card)
    await message.answer(text, reply_markup=user_actions_kb(card.user_id, is_blocked=card.role == "blocked"))


# ---------------------------------------------------------------------------
# User actions: credit / debit
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^admin:user:(\d+):(credit|debit)$"))
async def user_balance_start(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """Start balance adjustment FSM: ask for amount."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = str(callback.data).split(":")
    target_id = int(parts[2])
    action = parts[3]  # "credit" or "debit"

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(BalanceAdjustFSM.waiting_amount)
    await state.update_data(balance_target_id=target_id, balance_action=action)

    label = S.ADMIN_BALANCE_CREDIT_LABEL if action == "credit" else S.ADMIN_BALANCE_DEBIT_LABEL
    await safe_edit_text(
        msg,
        S.ADMIN_BALANCE_INPUT.format(action=label),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data=f"admin:user:{target_id}:card")],
            ]
        ),
    )
    await callback.answer()


@router.message(BalanceAdjustFSM.waiting_amount)
async def user_balance_input(
    message: Message,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    admin_service_factory: AdminServiceFactory,
    state: FSMContext,
) -> None:
    """Process balance amount input."""
    if not _is_admin(user):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(S.ADMIN_BALANCE_INPUT_ERROR)
        return

    amount = int(raw)
    data = await state.get_data()
    target_id = data.get("balance_target_id")
    action = data.get("balance_action", "credit")
    await state.clear()

    if target_id is None:
        await message.answer(S.ADMIN_BALANCE_NO_TARGET, reply_markup=_BACK_TO_PANEL_KB)
        return

    admin_svc = admin_service_factory(db)

    try:
        result = await admin_svc.adjust_balance(
            target_id=target_id,
            amount=amount,
            is_credit=(action == "credit"),
            admin_id=user.id,
            redis=redis,
        )
    except Exception:
        log.exception("admin_balance_adjust_failed", target_id=target_id)
        await message.answer(S.ADMIN_BALANCE_ADJUST_ERROR, reply_markup=_BACK_TO_PANEL_KB)
        return

    verb = "Начислено" if action == "credit" else "Списано"
    await message.answer(
        S.ADMIN_BALANCE_DONE.format(verb=verb, amount=amount, balance=result.new_balance),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="К карточке", callback_data=f"admin:user:{target_id}:card")],
                [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
            ]
        ),
    )


# ---------------------------------------------------------------------------
# User actions: block / unblock
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^admin:user:(\d+):(block|unblock)$"))
async def user_block_toggle(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    admin_service_factory: AdminServiceFactory,
) -> None:
    """Block or unblock a user."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = str(callback.data).split(":")
    target_id = int(parts[2])
    action = parts[3]

    # Self-block protection
    if target_id == user.id:
        await callback.answer(S.ADMIN_BLOCK_SELF, show_alert=True)
        return

    settings = get_settings()
    admin_ids = settings.admin_ids
    admin_svc = admin_service_factory(db)

    new_role = "blocked" if action == "block" else "user"

    try:
        await admin_svc.change_user_role(target_id, new_role, admin_ids, redis)
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception:
        log.exception("admin_block_unblock_failed", target_id=target_id)
        await callback.answer(S.ADMIN_ROLE_CHANGE_ERROR, show_alert=True)
        return

    verb = "заблокирован" if action == "block" else "разблокирован"
    await callback.answer(f"Пользователь {verb}")

    # Reload card
    card = await admin_svc.lookup_user(user_id=target_id)
    if card:
        text = _format_user_card(card)
        await safe_edit_text(msg, text, reply_markup=user_actions_kb(card.user_id, is_blocked=card.role == "blocked"))


# ---------------------------------------------------------------------------
# User actions: activity (recent publications)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^admin:user:(\d+):activity$"))
async def user_activity(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
) -> None:
    """Show recent publications for a user."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    target_id = int(str(callback.data).split(":")[2])
    admin_svc = admin_service_factory(db)
    pubs = await admin_svc.get_recent_publications(target_id, limit=5)

    if not pubs:
        text = (
            Screen(E.ANALYTICS, f"{S.ADMIN_USER_ACTIVITY_TITLE} #{target_id}")
            .blank()
            .line(S.ADMIN_NO_PUBLICATIONS)
            .build()
        )
    else:
        s = Screen(E.ANALYTICS, f"{S.ADMIN_USER_ACTIVITY_TITLE} #{target_id}")
        s.blank()
        for p in pubs:
            date = str(p.created_at)[:10] if p.created_at else "\u2014"
            kw = p.keyword or "\u2014"
            s.line(f"{date} | {p.status} | {kw}")
        text = s.build()

    await safe_edit_text(
        msg,
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="К карточке", callback_data=f"admin:user:{target_id}:card")],
                [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
            ]
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# User card reload (from action buttons)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^admin:user:(\d+):card$"))
async def user_card_reload(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
) -> None:
    """Reload and show user card (also serves as cancel target for FSMs)."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.clear()
    target_id = int(str(callback.data).split(":")[2])
    admin_svc = admin_service_factory(db)
    card = await admin_svc.lookup_user(user_id=target_id)

    if card is None:
        await safe_edit_text(msg, S.ADMIN_USER_NOT_FOUND, reply_markup=_BACK_TO_PANEL_KB)
        await callback.answer()
        return

    text = _format_user_card(card)
    await safe_edit_text(msg, text, reply_markup=user_actions_kb(card.user_id, is_blocked=card.role == "blocked"))
    await callback.answer()


# ---------------------------------------------------------------------------
# Broadcast FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:broadcast")
async def broadcast_start(callback: CallbackQuery, user: User, state: FSMContext) -> None:
    """Start broadcast FSM."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(BroadcastFSM.audience)
    text = (
        Screen(E.MEGAPHONE, S.BROADCAST_TITLE)
        .blank()
        .line(f"<i>{S.BROADCAST_AUDIENCE_PROMPT}</i>")
        .hint("Сообщение получат все пользователи выбранного сегмента")
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=broadcast_audience_kb())
    await callback.answer()


_AUDIENCE_LABELS: dict[str, str] = S.AUDIENCE_LABELS


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
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
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

    label = _AUDIENCE_LABELS.get(audience_key, audience_key)
    text = (
        Screen(E.MEGAPHONE, S.BROADCAST_TITLE)
        .blank()
        .line(S.BROADCAST_AUDIENCE_TEXT.format(label=label, count=count))
        .blank()
        .line(S.BROADCAST_TEXT_PROMPT)
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=_BACK_TO_PANEL_KB)
    await callback.answer()


@router.message(BroadcastFSM.text)
async def broadcast_text(message: Message, user: User, state: FSMContext) -> None:
    """Receive broadcast text, show preview."""
    if not _is_admin(user):
        return
    if not message.text:
        await message.answer(S.BROADCAST_TEXT_EXPECT)
        return

    await state.update_data(broadcast_text=message.text)
    await state.set_state(BroadcastFSM.confirm)

    data = await state.get_data()

    preview_text = (
        Screen(E.MEGAPHONE, S.BROADCAST_PREVIEW_TITLE)
        .blank()
        .line(f"Получателей: ~{data['broadcast_count']}")
        .blank()
        .line(f"<b>Текст рассылки:</b>\n{message.text}")
        .hint(S.BROADCAST_PREVIEW_PROMPT)
        .build()
    )
    await message.answer(preview_text, reply_markup=broadcast_confirm_kb())


@router.callback_query(BroadcastFSM.confirm, F.data == "broadcast:send")
async def broadcast_confirm(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    admin_service_factory: AdminServiceFactory,
    state: FSMContext,
) -> None:
    """Execute broadcast with rate limiting and progress updates."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
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
    total = len(user_ids)

    await safe_edit_text(msg, S.BROADCAST_PROGRESS_INIT.format(total=total))

    sent = 0
    failed = 0
    bot = callback.bot

    for i, uid in enumerate(user_ids, start=1):
        try:
            if bot is not None:
                await bot.send_message(uid, text)
            sent += 1
        except Exception:
            log.warning("broadcast_send_failed", user_id=uid)
            failed += 1
        await asyncio.sleep(0.05)  # 50ms rate limit

        # Progress update every N users (Telegram edit rate limit is acceptable to suppress)
        if i % _BROADCAST_PROGRESS_STEP == 0 and i < total:
            with contextlib.suppress(Exception):
                await safe_edit_text(msg, S.BROADCAST_PROGRESS.format(sent=i, total=total, ok=sent, failed=failed))

    done_text = (
        Screen(E.CHECK, S.BROADCAST_DONE)
        .blank()
        .line(S.BROADCAST_DONE_TEXT.format(sent=sent, failed=failed))
        .build()
    )
    await safe_edit_text(msg, done_text, reply_markup=_BACK_TO_PANEL_KB)
    await callback.answer()
