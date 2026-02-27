"""Category CRUD: list, create (FSM), card, delete with E24/E42 cleanup."""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import get_owned_category, get_owned_project, safe_message
from bot.service_factory import TokenServiceFactory
from db.client import SupabaseClient
from db.models import CategoryCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.schedules import SchedulesRepository
from keyboards.inline import (
    category_card_kb,
    category_created_kb,
    category_delete_confirm_kb,
    category_list_empty_kb,
    category_list_kb,
)
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()

# H17: maximum categories per project (anti-DoS)
MAX_CATEGORIES_PER_PROJECT = 50


# ---------------------------------------------------------------------------
# FSM definition (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class CategoryCreateFSM(StatesGroup):
    name = State()


# ---------------------------------------------------------------------------
# Category list
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:categories$"))
async def show_category_list(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show category list for a project (UX_TOOLBOX.md section 7.1)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await get_owned_project(db, project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    cats_repo = CategoriesRepository(db)
    categories = await cats_repo.get_by_project(project_id)

    if not categories:
        safe_name = html.escape(project.name)
        await msg.edit_text(
            f"<b>{safe_name}</b> — Категории\n\nВ проекте пока нет категорий.",
            reply_markup=category_list_empty_kb(project_id),
        )
    else:
        safe_name = html.escape(project.name)
        await msg.edit_text(
            f"<b>{safe_name}</b> — Категории ({len(categories)})",
            reply_markup=category_list_kb(categories, project_id),
        )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^page:categories:\d+:\d+$"))
async def paginate_categories(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Handle category list pagination."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[2])
    page = int(parts[3])

    project = await get_owned_project(db, project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    cats_repo = CategoriesRepository(db)
    categories = await cats_repo.get_by_project(project_id)

    safe_name = html.escape(project.name)
    await msg.edit_text(
        f"<b>{safe_name}</b> — Категории ({len(categories)})",
        reply_markup=category_list_kb(categories, project_id, page),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# CategoryCreateFSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:create$"))
async def start_category_create(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start category creation flow."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await get_owned_project(db, project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    # H17: enforce category limit per project
    cats_repo = CategoriesRepository(db)
    cat_count = await cats_repo.get_count_by_project(project_id)
    if cat_count >= MAX_CATEGORIES_PER_PROJECT:
        await callback.answer(
            f"Достигнут лимит категорий ({MAX_CATEGORIES_PER_PROJECT}) в проекте.",
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(CategoryCreateFSM.name)
    await state.update_data(last_update_time=time.time(), create_project_id=project_id)

    await msg.answer(
        "Введите название категории.\n\n<i>Пример: Кухни на заказ</i>",
    )
    await callback.answer()


@router.message(CategoryCreateFSM.name, F.text)
async def process_category_name(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Process category name (2-100 chars)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание отменено.")
        return

    if len(text) < 2 or len(text) > 100:
        await message.answer("Название: от 2 до 100 символов.")
        return

    data = await state.get_data()
    project_id = int(data["create_project_id"])
    await state.clear()

    # Ownership check
    project = await get_owned_project(db, project_id, user.id)
    if not project:
        await message.answer("Проект не найден.")
        return

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.create(CategoryCreate(project_id=project_id, name=text))

    safe_name = html.escape(category.name)
    await message.answer(
        f"Категория «{safe_name}» создана!\nДобавьте ключевые фразы для генерации контента.",
        reply_markup=category_created_kb(category.id, project_id),
    )
    log.info("category_created", category_id=category.id, project_id=project_id, user_id=user.id)


# ---------------------------------------------------------------------------
# Category card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:card$"))
async def show_category_card(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show category card (UX_TOOLBOX.md section 8)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    category = await get_owned_category(db, category_id, user.id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # Build card text
    safe_name = html.escape(category.name)
    lines = [f"<b>{safe_name}</b>\n"]

    # Keyword clusters
    keyword_count = len(category.keywords)
    if keyword_count > 0:
        cluster_count = sum(1 for k in category.keywords if k.get("cluster_name"))
        if cluster_count > 0:
            lines.append(f"Ключевые фразы: {cluster_count} кластеров")
        else:
            lines.append(f"Ключевые фразы: {keyword_count} фраз")
    else:
        lines.append("Ключевые фразы: не заданы")

    # Description
    lines.append(f"Описание: {'есть' if category.description else 'не задано'}")

    # Prices
    lines.append(f"Цены: {'есть' if category.prices else 'не заданы'}")

    # Image settings
    img_count = category.image_settings.get("count") if category.image_settings else None
    lines.append(f"Изображений: {img_count}/статью" if img_count is not None else "Изображения: по умолчанию")

    text = "\n".join(lines)
    await msg.edit_text(text, reply_markup=category_card_kb(category_id, category.project_id))
    await callback.answer()


# ---------------------------------------------------------------------------
# Category delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:delete$"))
async def confirm_category_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show category delete confirmation."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    category = await get_owned_category(db, category_id, user.id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # Show impact details
    sched_repo = SchedulesRepository(db)
    schedules = await sched_repo.get_by_category(category_id)
    active_count = sum(1 for s in schedules if s.enabled)

    safe_name = html.escape(category.name)
    impact_lines = [f"Удалить категорию «{safe_name}»?\n"]
    if active_count > 0:
        impact_lines.append(f"Будет отменено расписаний: {active_count}")
    impact_lines.append("Это действие нельзя отменить.")

    await msg.edit_text(
        "\n".join(impact_lines),
        reply_markup=category_delete_confirm_kb(category_id, category.project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^category:\d+:delete:confirm$"))
async def execute_category_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    scheduler_service: SchedulerService,
    token_service_factory: TokenServiceFactory,
) -> None:
    """Delete category with E24 + E42 cleanup."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    category = await get_owned_category(db, category_id, user.id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    project_id = category.project_id

    # E24: Cancel QStash schedules BEFORE CASCADE delete
    await scheduler_service.cancel_schedules_for_category(category_id)

    # E42: Refund active previews
    previews_repo = PreviewsRepository(db)
    active_previews = await previews_repo.get_active_drafts_by_category(category_id)
    if active_previews:
        token_service = token_service_factory(db)
        await token_service.refund_active_previews(
            active_previews,
            user.id,
            f"удаление категории #{category_id}",
        )

    # Delete category (CASCADE deletes schedules, overrides)
    cats_repo = CategoriesRepository(db)
    deleted = await cats_repo.delete(category_id)

    if deleted:
        safe_name = html.escape(category.name)
        # Reload remaining categories to show correct keyboard
        remaining = await cats_repo.get_by_project(project_id)
        kb = category_list_kb(remaining, project_id) if remaining else category_list_empty_kb(project_id)
        await msg.edit_text(
            f"Категория «{safe_name}» удалена.",
            reply_markup=kb,
        )
        log.info("category_deleted", category_id=category_id, user_id=user.id)
    else:
        await msg.edit_text("Ошибка удаления категории.")

    await callback.answer()
