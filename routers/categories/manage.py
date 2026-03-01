"""Category CRUD: list, create (FSM), card, delete with E24/E42 cleanup."""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.assets import edit_screen
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import get_owned_project, safe_edit_text, safe_message
from bot.service_factory import CategoryServiceFactory, TokenServiceFactory
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import (
    category_card_kb,
    category_created_kb,
    category_delete_confirm_kb,
    category_list_empty_kb,
    category_list_kb,
    menu_kb,
)
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()


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
    category_service_factory: CategoryServiceFactory,
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

    cat_svc = category_service_factory(db)
    categories = await cat_svc.list_by_project(project_id, user.id)

    if not categories:
        safe_name = html.escape(project.name)
        await edit_screen(
            msg,
            "empty_categories.png",
            f"<b>{safe_name}</b> \u2014 Категории\n\n"
            "\U0001f4c2 Категорий пока нет.\n\n"
            "Категория = тема контента "
            "(например: \u00abSEO-оптимизация\u00bb или \u00abКулинарные рецепты\u00bb).",
            reply_markup=category_list_empty_kb(project_id),
        )
    else:
        safe_name = html.escape(project.name)
        await edit_screen(
            msg,
            "empty_categories.png",
            f"<b>{safe_name}</b> — Категории ({len(categories)})",
            reply_markup=category_list_kb(categories, project_id),
        )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^page:categories:\d+:\d+$"))
async def paginate_categories(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
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

    cat_svc = category_service_factory(db)
    categories = await cat_svc.list_by_project(project_id, user.id)
    if categories is None:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    safe_name = html.escape(project.name)
    await edit_screen(
        msg,
        "empty_categories.png",
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
    category_service_factory: CategoryServiceFactory,
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
    cat_svc = category_service_factory(db)
    has_room = await cat_svc.check_category_limit(project_id, user.id)
    if not has_room:
        from services.categories import MAX_CATEGORIES_PER_PROJECT

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
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Process category name (2-100 chars)."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Создание категории отменено.", reply_markup=menu_kb())
        return

    if len(text) < 2 or len(text) > 100:
        await message.answer("Название: от 2 до 100 символов.")
        return

    data = await state.get_data()
    project_id = int(data["create_project_id"])
    await state.clear()

    cat_svc = category_service_factory(db)
    category = await cat_svc.create_category(project_id, user.id, text)

    if not category:
        await message.answer("Проект не найден.", reply_markup=menu_kb())
        return

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
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Show category card (UX_TOOLBOX.md section 8)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(category_id, user.id)
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
            lines.append(f"\U0001f511 Ключевые фразы: \u2705 {cluster_count} кластеров")
        else:
            lines.append(f"\U0001f511 Ключевые фразы: \u2705 {keyword_count} фраз")
    else:
        lines.append("\U0001f511 Ключевые фразы: \u274c не заданы")

    # Description
    if category.description:
        lines.append("\U0001f4dd Описание: \u2705 есть")
    else:
        lines.append("\U0001f4dd Описание: \u274c не задано")

    # Prices
    if category.prices:
        lines.append("\U0001f4b0 Цены: \u2705 есть")
    else:
        lines.append("\U0001f4b0 Цены: \u274c не заданы")

    # Image settings
    img_count = category.image_settings.get("count") if category.image_settings else None
    if img_count is not None:
        lines.append(f"\U0001f5bc Медиа: \u2705 {img_count} файлов")
    else:
        lines.append("\U0001f5bc Медиа: \u274c нет файлов")

    text = "\n".join(lines)
    await safe_edit_text(msg, text, reply_markup=category_card_kb(category_id, category.project_id))
    await callback.answer()


# ---------------------------------------------------------------------------
# Category delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:delete$"))
async def confirm_category_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Show category delete confirmation."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    result = await cat_svc.get_delete_impact(category_id, user.id)
    if not result:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    category, active_count = result

    safe_name = html.escape(category.name)
    impact_lines = [f"Удалить категорию «{safe_name}»?\n"]
    if active_count > 0:
        impact_lines.append(f"Будет отменено расписаний: {active_count}")
    impact_lines.append("Это действие нельзя отменить.")

    await safe_edit_text(
        msg,
        "\n".join(impact_lines),
        reply_markup=category_delete_confirm_kb(category_id, category.project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^category:\d+:delete:confirm$"))
async def execute_category_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
    scheduler_service: SchedulerService,
    token_service_factory: TokenServiceFactory,
) -> None:
    """Delete category with E24 + E42 cleanup."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    token_svc = token_service_factory(db)

    deleted, category, remaining = await cat_svc.delete_category(category_id, user.id, scheduler_service, token_svc)

    if deleted and category:
        safe_name = html.escape(category.name)
        kb = (
            category_list_kb(remaining, category.project_id)
            if remaining
            else category_list_empty_kb(category.project_id)
        )
        await msg.edit_text(
            f"Категория «{safe_name}» удалена.",
            reply_markup=kb,
        )
    else:
        await msg.edit_text("\u26a0\ufe0f Не удалось удалить категорию. Попробуйте позже.", reply_markup=menu_kb())

    await callback.answer()
