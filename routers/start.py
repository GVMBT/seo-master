"""Router: /start, /cancel, /help, main menu, reply button dispatch."""

import json
import re

import httpx
import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.users import UsersRepository
from keyboards.reply import main_menu
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="start")

# ---------------------------------------------------------------------------
# Welcome messages (USER_FLOWS_AND_UI_MAP.md §2, scenario 1)
# ---------------------------------------------------------------------------

_WELCOME_NEW = (
    "Добро пожаловать в SEO Master Bot!\n\n"
    "Вам начислено 1500 токенов (~5 статей на сайт).\n\n"
    "Начните с создания проекта — это займёт пару минут."
)

_WELCOME_RETURNING = "С возвращением! Баланс: {balance} токенов."

# ---------------------------------------------------------------------------
# /start (with optional deep link: ref_{id}, pinterest_auth_{nonce})
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r"^ref_(\d+)$")


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

    text = _WELCOME_NEW if is_new_user else _WELCOME_RETURNING.format(balance=user.balance)
    await message.answer(
        text,
        reply_markup=main_menu(is_admin=user.role == "admin"),
    )


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool = False,
) -> None:
    """Handle plain /start — clear FSM, show main menu."""
    await state.clear()
    text = _WELCOME_NEW if is_new_user else _WELCOME_RETURNING.format(balance=user.balance)
    await message.answer(
        text,
        reply_markup=main_menu(is_admin=user.role == "admin"),
    )


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
            "Подключение Pinterest отменено. Время авторизации истекло (E20).\n"
            "Попробуйте снова.",
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
                "Не удалось получить список досок Pinterest (E21).\n"
                "Попробуйте снова.",
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
        await message.answer(
            "Действие отменено.", reply_markup=main_menu(is_admin=user.role == "admin")
        )
    else:
        await message.answer(
            "Нет активного действия.", reply_markup=main_menu(is_admin=user.role == "admin")
        )


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show help text."""
    await message.answer(
        "SEO Master Bot — AI-генерация контента.\n\n"
        "Команды:\n"
        "/start — главное меню\n"
        "/cancel — отменить текущее действие\n"
        "/help — эта справка\n\n"
        "Используйте кнопки меню для навигации."
    )


# ---------------------------------------------------------------------------
# menu:main callback (inline button → main menu text)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, user: User) -> None:
    """Return to main menu via inline button. Clears FSM if active."""
    await state.clear()
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await msg.edit_text(
        f"Главное меню. Баланс: {user.balance} токенов.",
    )
    # Restore reply keyboard
    await msg.answer(
        "Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin")
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Reply button dispatch (bottom keyboard)
# ---------------------------------------------------------------------------


@router.message(F.text == "Проекты")
async def btn_projects(message: Message, user: User, db: SupabaseClient) -> None:
    """Reply button [Проекты] → project list."""
    from db.repositories.projects import ProjectsRepository
    from keyboards.inline import project_list_kb

    projects = await ProjectsRepository(db).get_by_user(user.id)
    if not projects:
        text = "У вас пока нет проектов. Создайте первый проект, чтобы начать."
    else:
        text = f"Ваши проекты ({len(projects)}):"
    await message.answer(text, reply_markup=project_list_kb(projects).as_markup())


@router.message(F.text == "Настройки")
async def btn_settings(message: Message) -> None:
    """Reply button [Настройки] → settings menu."""
    from keyboards.inline import settings_main_kb

    await message.answer("Настройки:", reply_markup=settings_main_kb().as_markup())


@router.message(F.text == "Помощь")
async def btn_help(message: Message) -> None:
    """Reply button [Помощь] → help text."""
    await cmd_help(message)


@router.message(F.text == "Профиль")
async def btn_profile(message: Message, user: User, db: SupabaseClient) -> None:
    """Reply button [Профиль] → profile screen."""
    from routers.profile import _show_profile

    await _show_profile(message, user, db, edit=False)


@router.message(F.text.in_({"Быстрая публикация", "Тарифы", "АДМИНКА"}))
async def btn_stub(message: Message) -> None:
    """Stub handlers for not-yet-implemented menu buttons."""
    await message.answer("В разработке.")


@router.callback_query(F.data.in_({"stats:all", "help:main", "tariffs:main"}))
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
