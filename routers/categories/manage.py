"""Router: category CRUD — list, card, create FSM, delete."""

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import Category, CategoryCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import category_card_kb, category_delete_confirm_kb, category_list_kb
from keyboards.reply import cancel_kb

router = Router(name="categories_manage")


# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class CategoryCreateFSM(StatesGroup):
    name = State()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_NAME_RE = re.compile(r"^[\w\s\-.,!?()\"'«»/&#@:;№]+$")


def _validate_category_name(value: str) -> str | None:
    """Validate category name. Returns error message or None."""
    if len(value) < 2 or len(value) > 100:
        return "Введите название от 2 до 100 символов."
    if not _NAME_RE.match(value):
        return "Название содержит недопустимые символы."
    return None


# ---------------------------------------------------------------------------
# Authorization helpers
# ---------------------------------------------------------------------------


async def _verify_project_owner(
    project_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery
) -> bool:
    """Check that user owns the project. Answers callback on failure."""
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Проект не найден.", show_alert=True)
        return False
    return True


async def _get_category_or_notify(
    category_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery
) -> tuple[Category, int] | None:
    """Fetch category and verify ownership via project. Returns (category, project_id) or None."""
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    return category, project.id


# ---------------------------------------------------------------------------
# Category list + pagination
# ---------------------------------------------------------------------------


def _format_category_card(category: Category) -> str:
    """Format category info text."""
    kw_count = len(category.keywords) if category.keywords else 0
    media_count = len(category.media) if category.media else 0
    reviews_count = len(category.reviews) if category.reviews else 0
    desc_status = "заполнено" if category.description else "не заполнено"
    prices_status = "загружен" if category.prices else "не загружен"
    return (
        f"<b>{category.name}</b>\n\n"
        f"Ключевые фразы: {kw_count}\n"
        f"Описание: {desc_status}\n"
        f"Медиа: {media_count} файлов\n"
        f"Прайс: {prices_status}\n"
        f"Отзывы: {reviews_count}"
    )


@router.callback_query(F.data.regexp(r"^project:(\d+):categories$"))
async def cb_category_list(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show paginated category list for a project."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _verify_project_owner(project_id, user.id, db, callback):
        return
    categories = await CategoriesRepository(db).get_by_project(project_id)
    if not categories:
        text = (
            "В проекте пока нет категорий.\n"
            "Категория = тема контента (напр. «Кухонная мебель»).\n"
            "Создайте первую, чтобы начать генерацию."
        )
    else:
        text = f"Категории ({len(categories)}):"
    await callback.message.edit_text(
        text, reply_markup=category_list_kb(categories, project_id).as_markup()
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^page:categories:(\d+):(\d+)$"))
async def cb_category_page(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Handle category list pagination."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[2])
    page = int(parts[3])
    if not await _verify_project_owner(project_id, user.id, db, callback):
        return
    categories = await CategoriesRepository(db).get_by_project(project_id)
    text = f"Категории ({len(categories)}):"
    await callback.message.edit_text(
        text, reply_markup=category_list_kb(categories, project_id, page=page).as_markup()
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Category card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):card$"))
async def cb_category_card(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show category card."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_category_or_notify(category_id, user.id, db, callback)
    if not result:
        return
    category, _ = result
    await callback.message.edit_text(
        _format_category_card(category),
        reply_markup=category_card_kb(category).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Stub handlers for later phases
# ---------------------------------------------------------------------------


@router.callback_query(
    F.data.regexp(r"^category:(\d+):(keywords|description|prices|reviews|media)$")
)
async def cb_category_feature_stub(callback: CallbackQuery) -> None:
    """Stub for not-yet-implemented category features."""
    await callback.answer("В разработке.", show_alert=True)


# ---------------------------------------------------------------------------
# Create category FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):cat:new$"))
async def cb_category_new(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """Start category creation FSM."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _verify_project_owner(project_id, user.id, db, callback):
        return

    # Auto-clear any active FSM (P4.11, FSM conflict resolution)
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(CategoryCreateFSM.name)
    await state.update_data(project_id=project_id)
    await callback.message.answer(
        "Введите название категории (2-100 символов):",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(CategoryCreateFSM.name, F.text)
async def fsm_category_name(message: Message, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """FSM: validate and create category."""
    error = _validate_category_name(message.text)  # type: ignore[arg-type]
    if error:
        await message.answer(error)
        return

    data = await state.get_data()
    project_id = data["project_id"]
    await state.clear()

    category = await CategoriesRepository(db).create(
        CategoryCreate(project_id=project_id, name=message.text)  # type: ignore[arg-type]
    )
    await message.answer(
        _format_category_card(category),
        reply_markup=category_card_kb(category).as_markup(),
    )


# ---------------------------------------------------------------------------
# Delete category (2-step confirmation)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):delete$"))
async def cb_category_delete(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show delete confirmation."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_category_or_notify(category_id, user.id, db, callback)
    if not result:
        return
    category, _ = result
    await callback.message.edit_text(
        f"Удалить категорию «{category.name}»? Все данные категории будут удалены.",
        reply_markup=category_delete_confirm_kb(category).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^category:(\d+):delete:confirm$"))
async def cb_category_delete_confirm(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Confirm deletion and show updated category list."""
    if not isinstance(callback.message, Message):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_category_or_notify(category_id, user.id, db, callback)
    if not result:
        return
    _, project_id = result

    # TODO Phase 9: cancel QStash schedules before CASCADE delete (E24)
    repo = CategoriesRepository(db)
    await repo.delete(category_id)

    categories = await repo.get_by_project(project_id)
    text = (
        f"Категория удалена. Категории ({len(categories)}):"
        if categories
        else "Категория удалена. Нет категорий."
    )
    await callback.message.edit_text(
        text, reply_markup=category_list_kb(categories, project_id).as_markup()
    )
    await callback.answer("Категория удалена.")
