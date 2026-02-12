"""Router: /start, /cancel, /help, main menu, reply button dispatch."""

import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.users import UsersRepository
from keyboards.reply import main_menu

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

    # Pinterest OAuth: /start pinterest_auth_{nonce} — Phase 9 stub
    # if payload.startswith("pinterest_auth_"): ...

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
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    await callback.message.edit_text(
        f"Главное меню. Баланс: {user.balance} токенов.",
    )
    # Restore reply keyboard
    await callback.message.answer(
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


@router.message(F.text.in_({"Быстрая публикация", "Профиль", "Тарифы", "АДМИНКА"}))
async def btn_stub(message: Message) -> None:
    """Stub handlers for not-yet-implemented menu buttons."""
    await message.answer("В разработке.")


@router.callback_query(F.data.in_({"stats:all", "help:main"}))
async def cb_stub(callback: CallbackQuery) -> None:
    """Stub for not-yet-implemented inline button features."""
    await callback.answer("В разработке.", show_alert=True)


# ---------------------------------------------------------------------------
# Non-text FSM guard: photo/video/sticker during active FSM → error message
# ---------------------------------------------------------------------------


@router.message(~F.text, StateFilter("*"))
async def fsm_non_text_guard(message: Message) -> None:
    """Reject non-text messages during any active FSM flow.

    StateFilter("*") matches any non-None state, so this handler only fires
    when the user is in an FSM flow and sends non-text content.
    """
    await message.answer("Пожалуйста, отправьте текстовое сообщение.")
