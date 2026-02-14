"""Router: /start, /cancel, /help, main menu dashboard, reply button dispatch."""

import json
import re

import httpx
import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.users import UsersRepository
from keyboards.inline import dashboard_kb
from keyboards.reply import main_menu
from routers._helpers import guard_callback_message
from services.tokens import TokenService

log = structlog.get_logger()

router = Router(name="start")

# ---------------------------------------------------------------------------
# Help text (shared between /help command and help:main callback)
# ---------------------------------------------------------------------------

_HELP_TEXT = (
    "SEO Master Bot — AI-генерация контента.\n\n"
    "Команды:\n"
    "/start — главное меню\n"
    "/cancel — отменить текущее действие\n"
    "/help — эта справка\n\n"
    "Используйте кнопки меню для навигации."
)


# ---------------------------------------------------------------------------
# Dashboard text builder
# ---------------------------------------------------------------------------


async def _build_dashboard_text(user: User, db: SupabaseClient, is_new_user: bool = False) -> str:
    """Build main menu dashboard text with stats.

    Three variants:
    - New user: welcome + token grant
    - Returning without projects: balance + CTA
    - Returning with projects: balance + stats + forecast
    """
    if is_new_user:
        return (
            "Добро пожаловать в SEO Master Bot!\n\n"
            "Вам начислено 1500 токенов (~5 статей на сайт).\n"
            "Начните с создания проекта — это займёт 30 секунд."
        )

    service = TokenService(db, admin_id=get_settings().admin_id)
    stats = await service.get_profile_stats(user)

    if stats["project_count"] == 0:
        return f"Баланс: {user.balance} токенов\n\nУ вас пока нет проектов.\nСоздайте первый — это займёт 30 секунд."

    lines = [f"Баланс: {user.balance} токенов", ""]
    lines.append(f"Проектов: {stats['project_count']} | Категорий: {stats['category_count']}")
    if stats["schedule_count"] > 0:
        tokens_per_week = stats["tokens_per_week"]
        weeks_left = round(user.balance / tokens_per_week, 1) if tokens_per_week > 0 else 0
        lines.append(f"Расписаний: {stats['schedule_count']} | Постов/нед: {stats['posts_per_week']}")
        lines.append(f"Хватит на: ~{weeks_left} нед.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /start (with optional deep link: ref_{id}, pinterest_auth_{nonce})
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r"^ref_(\d+)$")


async def _send_dashboard(message: Message, user: User, db: SupabaseClient, is_new_user: bool = False) -> None:
    """Send dashboard: restore reply-KB + dashboard with inline navigation.

    Two messages because Telegram API doesn't allow mixing
    ReplyKeyboardMarkup and InlineKeyboardMarkup in one message.
    """
    # 1. Restore compact reply keyboard (Меню + Быстрая публикация)
    await message.answer(
        "Используйте кнопки ниже для быстрого доступа.",
        reply_markup=main_menu(is_admin=user.role == "admin"),
    )
    # 2. Dashboard with inline navigation
    text = await _build_dashboard_text(user, db, is_new_user=is_new_user)
    await message.answer(text, reply_markup=dashboard_kb().as_markup())


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    is_new_user: bool = False,
) -> None:
    """Handle /start with deep link payload (referral, Pinterest OAuth stub)."""
    await state.clear()

    payload = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""

    # Referral: /start ref_12345
    match = _REF_RE.match(payload)
    if match:
        referrer_id = int(match.group(1))
        repo = UsersRepository(db)
        # Validate referrer exists (P4.2), one-time, no self-referral
        referrer = await repo.get_by_id(referrer_id)
        if referrer and user.referrer_id is None and referrer_id != user.id:
            await repo.update(user.id, UserUpdate(referrer_id=referrer_id))

    # Pinterest OAuth: /start pinterest_auth_{nonce}
    if payload.startswith("pinterest_auth_"):
        await _handle_pinterest_auth(message, state, user, db, redis, http_client, payload)
        return

    await _send_dashboard(message, user, db, is_new_user=is_new_user)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    is_new_user: bool = False,
) -> None:
    """Handle plain /start — clear FSM, show dashboard."""
    await state.clear()
    await _send_dashboard(message, user, db, is_new_user=is_new_user)


# ---------------------------------------------------------------------------
# Pinterest OAuth deep link handler
# ---------------------------------------------------------------------------


async def _handle_pinterest_auth(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    payload: str,
) -> None:
    """Handle /start pinterest_auth_{nonce} — retrieve tokens from Redis, fetch boards.

    Flow: OAuth callback (api/auth.py) stores tokens in Redis → deep link back to bot →
    this handler retrieves tokens → fetches boards → transitions to select_board FSM.
    """
    from routers.platforms.connections import ConnectPinterestFSM

    nonce = payload.removeprefix("pinterest_auth_")
    if not nonce:
        await message.answer(
            "Ошибка авторизации Pinterest. Попробуйте снова.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    # Get tokens from Redis (stored by api/auth.py callback)
    redis_key = f"pinterest_auth:{nonce}"
    raw_tokens = await redis.get(redis_key)
    if not raw_tokens:
        log.warning("pinterest_auth_tokens_not_found", nonce=nonce, user_id=user.id)
        await state.clear()
        await message.answer(
            "Подключение Pinterest отменено. Время авторизации истекло (E20).\nПопробуйте снова.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    tokens: dict = json.loads(raw_tokens)
    # Clean up Redis key (one-time use)
    await redis.delete(redis_key)

    # Fetch boards from Pinterest API
    access_token = tokens.get("access_token", "")
    try:
        resp = await http_client.get(
            "https://api.pinterest.com/v5/boards",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"page_size": "25"},
        )
        if resp.status_code != 200:
            log.warning("pinterest_boards_fetch_failed", status=resp.status_code, user_id=user.id)
            await state.clear()
            await message.answer(
                "Не удалось получить список досок Pinterest (E21).\nПопробуйте снова.",
                reply_markup=main_menu(is_admin=user.role == "admin"),
            )
            return

        boards_data = resp.json().get("items", [])
    except Exception as exc:
        log.warning("pinterest_boards_request_failed", error=str(exc), user_id=user.id)
        await state.clear()
        await message.answer(
            "Не удалось связаться с Pinterest API. Попробуйте позже.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    if not boards_data:
        await state.clear()
        await message.answer(
            "У вас нет досок в Pinterest. Создайте хотя бы одну доску и попробуйте снова.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    # Check FSM state — should be ConnectPinterestFSM.oauth_callback
    current_state = await state.get_state()
    fsm_data = await state.get_data()

    # Verify nonce matches (user might have started a new OAuth flow)
    if current_state != ConnectPinterestFSM.oauth_callback or fsm_data.get("nonce") != nonce:
        log.warning("pinterest_auth_fsm_mismatch", nonce=nonce, current_state=current_state)
        await state.clear()
        await message.answer(
            "Сессия подключения Pinterest не найдена. Начните подключение заново.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    # Store tokens and boards in FSM, transition to board selection
    boards = [{"id": b["id"], "name": b.get("name", f"Board {b['id']}")} for b in boards_data]
    await state.update_data(pinterest_tokens=tokens, pinterest_boards=boards)
    await state.set_state(ConnectPinterestFSM.select_board)

    builder = InlineKeyboardBuilder()
    for b in boards:
        text = b["name"]
        if len(text) > 60:
            text = text[:57] + "..."
        builder.button(text=text, callback_data=f"pin_board:{b['id']}")
    builder.adjust(1)

    await message.answer(
        "Шаг 2/2. Выберите доску для публикации:",
        reply_markup=builder.as_markup(),
    )


# ---------------------------------------------------------------------------
# /cancel — global, any FSM state
# ---------------------------------------------------------------------------


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext, user: User) -> None:
    """Cancel any active FSM and return to main menu."""
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=main_menu(is_admin=user.role == "admin"))


@router.message(F.text == "Отмена", StateFilter("*"))
async def btn_cancel(message: Message, state: FSMContext, user: User) -> None:
    """Reply keyboard [Отмена] button — same as /cancel."""
    current = await state.get_state()
    if current is not None:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu(is_admin=user.role == "admin"))
    else:
        await message.answer("Нет активного действия.", reply_markup=main_menu(is_admin=user.role == "admin"))


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show help text via /help command."""
    await message.answer(_HELP_TEXT)


# ---------------------------------------------------------------------------
# menu:main callback (inline button → dashboard)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Return to main menu via inline button. Edits message to dashboard.

    Reply keyboard is already set — no need to send a second message.
    """
    await state.clear()
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    text = await _build_dashboard_text(user, db)
    await msg.edit_text(text, reply_markup=dashboard_kb().as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Inline help callback (dashboard → Помощь)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "help:main")
async def cb_help(callback: CallbackQuery) -> None:
    """Show help text via inline button with back-to-menu navigation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    back_kb = InlineKeyboardBuilder()
    back_kb.button(text="Главное меню", callback_data="menu:main")
    back_kb.adjust(1)
    await msg.edit_text(_HELP_TEXT, reply_markup=back_kb.as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Reply button dispatch (bottom keyboard: Меню + Быстрая публикация)
# ---------------------------------------------------------------------------


@router.message(F.text == "Меню")
async def btn_menu(message: Message, user: User, db: SupabaseClient) -> None:
    """Reply button [Меню] → dashboard with inline navigation."""
    text = await _build_dashboard_text(user, db)
    await message.answer(text, reply_markup=dashboard_kb().as_markup())


@router.message(F.text == "Быстрая публикация")
async def btn_quick_publish(message: Message, user: User, db: SupabaseClient) -> None:
    """Reply button [Быстрая публикация] → delegate to quick publish flow."""
    from routers.publishing.quick import send_quick_publish_menu

    await send_quick_publish_menu(message, user, db)


@router.message(F.text == "АДМИНКА")
async def btn_admin_stub(message: Message) -> None:
    """Stub for admin panel button."""
    await message.answer("В разработке.")


@router.callback_query(F.data == "stats:all")
async def cb_stub(callback: CallbackQuery) -> None:
    """Stub for not-yet-implemented inline button features."""
    await callback.answer("В разработке.", show_alert=True)


# ---------------------------------------------------------------------------
# Non-text FSM guard: photo/video/sticker during active FSM → error message
# ---------------------------------------------------------------------------


@router.message(~F.text & ~F.document, StateFilter("*"))
async def fsm_non_text_guard(message: Message) -> None:
    """Reject non-text messages during any active FSM flow.

    StateFilter("*") matches any non-None state, so this handler only fires
    when the user is in an FSM flow and sends non-text content.
    """
    await message.answer("Пожалуйста, отправьте текстовое сообщение.")
