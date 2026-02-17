"""Article Pipeline — Goal-Oriented Pipeline for article creation (F5).

FSM: ArticlePipelineFSM (25 states, FSM_SPEC.md §1).
UX: UX_PIPELINE.md §4 (steps 1-8, inline sub-flows).
Rules: .claude/rules/pipeline.md.

This file implements steps 1-3 (selection) of the pipeline.
Steps 4-8 (readiness, generation, preview, publish) will be added in F5.3-F5.4.
"""

from __future__ import annotations

import html
import json

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from cache.client import RedisClient
from cache.keys import PIPELINE_CHECKPOINT_TTL, CacheKeys
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.pipeline import (
    pipeline_categories_kb,
    pipeline_no_projects_kb,
    pipeline_no_wp_kb,
    pipeline_projects_kb,
    pipeline_wp_select_kb,
)

log = structlog.get_logger()
router = Router()


def _conn_repo(db: SupabaseClient) -> ConnectionsRepository:
    """Create ConnectionsRepository with CredentialManager."""
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    return ConnectionsRepository(db, cm)


# ---------------------------------------------------------------------------
# FSM (FSM_SPEC.md §1 — ArticlePipelineFSM, 25 states)
# ---------------------------------------------------------------------------


class ArticlePipelineFSM(StatesGroup):
    """Article pipeline FSM — 25 states covering 8 steps + inline sub-flows."""

    # Step 1: Project selection
    select_project = State()
    create_project_name = State()
    create_project_company = State()
    create_project_spec = State()
    create_project_url = State()

    # Step 2: WP connection check
    select_wp = State()
    connect_wp_url = State()
    connect_wp_login = State()
    connect_wp_password = State()

    # Step 3: Category selection
    select_category = State()
    create_category_name = State()

    # Step 4: Readiness check + inline sub-flows
    readiness_check = State()
    readiness_keywords_products = State()
    readiness_keywords_geo = State()
    readiness_keywords_qty = State()
    readiness_keywords_generating = State()
    readiness_description = State()
    readiness_prices = State()
    readiness_photos = State()

    # Step 5-8: Confirmation, generation, preview, result
    confirm_cost = State()
    generating = State()
    preview = State()
    publishing = State()
    result = State()
    regenerating = State()


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


async def _save_checkpoint(
    redis: RedisClient,
    user_id: int,
    *,
    current_step: str,
    project_id: int | None = None,
    project_name: str | None = None,
    connection_id: int | None = None,
    category_id: int | None = None,
    **extra: object,
) -> None:
    """Save pipeline checkpoint to Redis (UX_PIPELINE.md §10.3)."""
    data: dict[str, object] = {
        "pipeline_type": "article",
        "current_step": current_step,
        "project_id": project_id,
        "project_name": project_name,
        "connection_id": connection_id,
        "category_id": category_id,
    }
    # step_label for Dashboard resume display
    step_labels = {
        "select_project": "выбор проекта",
        "select_wp": "выбор сайта",
        "select_category": "выбор темы",
        "readiness_check": "подготовка",
        "confirm_cost": "подтверждение",
        "generating": "генерация",
        "preview": "превью",
        "publishing": "публикация",
        "result": "результат",
    }
    data["step_label"] = step_labels.get(current_step, current_step)
    data.update(extra)  # type: ignore[arg-type]
    await redis.set(
        CacheKeys.pipeline_state(user_id),
        json.dumps(data, ensure_ascii=False),
        ex=PIPELINE_CHECKPOINT_TTL,
    )


async def _clear_checkpoint(redis: RedisClient, user_id: int) -> None:
    """Remove pipeline checkpoint from Redis."""
    await redis.delete(CacheKeys.pipeline_state(user_id))


# ---------------------------------------------------------------------------
# Step 1: Entry point — pipeline:article:start
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:article:start")
async def pipeline_article_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Start article pipeline — show project selection (step 1).

    UX_PIPELINE.md §4.1:
    - 0 projects -> inline create
    - 1 project -> auto-select, skip to step 2
    - >1 projects -> show list with pagination
    """
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    # Clear any active FSM (E29)
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        log.info("pipeline.article.fsm_interrupted", user_id=user.id, interrupted=interrupted)

    repo = ProjectsRepository(db)
    projects = await repo.get_by_user(user.id)

    if not projects:
        # No projects — offer inline create
        await callback.message.edit_text(
            "Статья (1/5) — Проект\n\nДля начала создадим проект — это 30 секунд.",
            reply_markup=pipeline_no_projects_kb(),
        )
        await state.set_state(ArticlePipelineFSM.select_project)
        await _save_checkpoint(redis, user.id, current_step="select_project")
        await callback.answer()
        return

    if len(projects) == 1:
        # Auto-select the only project
        project = projects[0]
        await state.update_data(project_id=project.id, project_name=project.name)
        await _show_wp_step(callback, state, user, db, redis, project.id, project.name)
        await callback.answer()
        return

    # Multiple projects — show list
    await callback.message.edit_text(
        "Статья (1/5) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_projects_kb(projects),
    )
    await state.set_state(ArticlePipelineFSM.select_project)
    await _save_checkpoint(redis, user.id, current_step="select_project")
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.select_project,
    F.data.regexp(r"^pipeline:article:(\d+):select$"),
)
async def pipeline_select_project(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Handle project selection from list."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return
    project_id = int(callback.data.split(":")[2])  # pipeline:article:{id}:select

    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)

    if project is None or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    await state.update_data(project_id=project.id, project_name=project.name)
    await _show_wp_step(callback, state, user, db, redis, project.id, project.name)
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.select_project,
    F.data.regexp(r"^page:pipeline_projects:\d+$"),
)
async def pipeline_projects_page(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Handle project list pagination."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    page = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    repo = ProjectsRepository(db)
    projects = await repo.get_by_user(user.id)

    await callback.message.edit_text(
        "Статья (1/5) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_projects_kb(projects, page=page),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 2: WP connection check
# ---------------------------------------------------------------------------


async def _show_wp_step(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
) -> None:
    """Show WP connection selection (step 2).

    UX_PIPELINE.md §4.1:
    - 1 WP connection -> auto-select, skip to step 3
    - >1 WP connections -> show list
    - 0 WP connections -> offer connect or preview-only
    """
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return

    repo = _conn_repo(db)
    wp_connections = await repo.get_by_project_and_platform(project_id, "wordpress")

    if len(wp_connections) == 1:
        # Auto-select the only WP connection
        conn = wp_connections[0]
        await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
        await _show_category_step(callback, state, user, db, redis, project_id, project_name)
        return

    if len(wp_connections) > 1:
        # Multiple WP connections — show selection
        await callback.message.edit_text(
            "Статья (2/5) — Сайт\n\nНа какой сайт?",
            reply_markup=pipeline_wp_select_kb(wp_connections, project_id),
        )
        await state.set_state(ArticlePipelineFSM.select_wp)
        await _save_checkpoint(
            redis,
            user.id,
            current_step="select_wp",
            project_id=project_id,
            project_name=project_name,
        )
        return

    # No WP connections — offer connect or preview-only
    await callback.message.edit_text(
        "Статья (2/5) — Сайт\n\nДля публикации нужен WordPress-сайт. Подключим?",
        reply_markup=pipeline_no_wp_kb(),
    )
    await state.set_state(ArticlePipelineFSM.select_wp)
    await _save_checkpoint(
        redis,
        user.id,
        current_step="select_wp",
        project_id=project_id,
        project_name=project_name,
    )


@router.callback_query(
    ArticlePipelineFSM.select_wp,
    F.data.regexp(r"^pipeline:article:(\d+):wp:(\d+)$"),
)
async def pipeline_select_wp(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Handle WP connection selection from list."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[2])
    connection_id = int(parts[4])

    repo = _conn_repo(db)
    conn = await repo.get_by_id(connection_id)

    if conn is None or conn.project_id != project_id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    data = await state.get_data()
    project_name = data.get("project_name", "")

    await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
    await _show_category_step(callback, state, user, db, redis, project_id, project_name)
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.select_wp,
    F.data == "pipeline:article:preview_only",
)
async def pipeline_preview_only(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """User chose preview-only (no WP publication)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")

    await state.update_data(connection_id=None, wp_identifier=None, preview_only=True)
    if project_id:
        await _show_category_step(callback, state, user, db, redis, project_id, project_name)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 3: Category selection
# ---------------------------------------------------------------------------


async def _show_category_step(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
) -> None:
    """Show category selection (step 3).

    UX_PIPELINE.md §4.1:
    - 0 categories -> inline create (text input)
    - 1 category -> auto-select, skip to step 4
    - >1 categories -> show list with pagination
    """
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return

    repo = CategoriesRepository(db)
    categories = await repo.get_by_project(project_id)

    if not categories:
        # No categories — prompt for inline creation
        await callback.message.edit_text(
            "Статья (3/5) — Тема\n\nО чём будет статья? Назовите тему.",
        )
        await state.set_state(ArticlePipelineFSM.create_category_name)
        await _save_checkpoint(
            redis,
            user.id,
            current_step="select_category",
            project_id=project_id,
            project_name=project_name,
        )
        return

    if len(categories) == 1:
        # Auto-select the only category
        cat = categories[0]
        await state.update_data(category_id=cat.id, category_name=cat.name)
        await _show_readiness_stub(callback, state, user, db, redis, project_id, project_name, cat.id, cat.name)
        return

    # Multiple categories — show list
    await callback.message.edit_text(
        "Статья (3/5) — Тема\n\nКакая тема?",
        reply_markup=pipeline_categories_kb(categories, project_id),
    )
    await state.set_state(ArticlePipelineFSM.select_category)
    await _save_checkpoint(
        redis,
        user.id,
        current_step="select_category",
        project_id=project_id,
        project_name=project_name,
    )


@router.callback_query(
    ArticlePipelineFSM.select_category,
    F.data.regexp(r"^pipeline:article:\d+:cat:(\d+)$"),
)
async def pipeline_select_category(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Handle category selection from list."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[4])

    repo = CategoriesRepository(db)
    category = await repo.get_by_id(category_id)

    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    data = await state.get_data()
    project_id = data.get("project_id", 0)
    project_name = data.get("project_name", "")

    # Ownership check: category belongs to the selected project
    if category.project_id != project_id:
        await callback.answer("Категория не принадлежит проекту.", show_alert=True)
        return

    await state.update_data(category_id=category.id, category_name=category.name)
    await _show_readiness_stub(callback, state, user, db, redis, project_id, project_name, category.id, category.name)
    await callback.answer()


@router.message(ArticlePipelineFSM.create_category_name)
async def pipeline_create_category_name(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Inline category creation — user typed a category name.

    UX_PIPELINE.md §4.1 step 3: 0 categories -> text input.
    """
    name = (message.text or "").strip()
    if not name or len(name) > 100:
        await message.answer("Введите название темы (до 100 символов).")
        return

    data = await state.get_data()
    project_id = data.get("project_id", 0)
    project_name = data.get("project_name", "")

    repo = CategoriesRepository(db)
    from db.models import CategoryCreate

    category = await repo.create(
        CategoryCreate(
            project_id=project_id,
            name=name,
        )
    )
    if category is None:
        await message.answer("Не удалось создать категорию. Попробуйте снова.")
        return

    await state.update_data(category_id=category.id, category_name=category.name)
    await message.answer(f"Тема «{html.escape(category.name)}» создана.")

    # Proceed to readiness (step 4)
    # For text messages we can't edit — send new message
    await _show_readiness_stub_msg(
        message,
        state,
        user,
        db,
        redis,
        project_id,
        project_name,
        category.id,
        category.name,
    )


# ---------------------------------------------------------------------------
# Step 4 stub: Readiness (will be implemented in F5.3)
# ---------------------------------------------------------------------------


async def _show_readiness_stub(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
    category_id: int,
    category_name: str,
) -> None:
    """Stub for readiness check (step 4). Will be replaced in F5.3."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return

    await callback.message.edit_text(
        f"Статья (4/5) — Подготовка\n\n"
        f"Проект: {html.escape(project_name)}\n"
        f"Тема: {html.escape(category_name)}\n\n"
        f"Readiness check — будет реализован в F5.3.",
    )
    await state.set_state(ArticlePipelineFSM.readiness_check)
    await _save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
    )


async def _show_readiness_stub_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
    category_id: int,
    category_name: str,
) -> None:
    """Stub readiness for message (non-edit) context."""
    await message.answer(
        f"Статья (4/5) — Подготовка\n\n"
        f"Проект: {html.escape(project_name)}\n"
        f"Тема: {html.escape(category_name)}\n\n"
        f"Readiness check — будет реализован в F5.3.",
    )
    await state.set_state(ArticlePipelineFSM.readiness_check)
    await _save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
    )


# ---------------------------------------------------------------------------
# Cancel handler
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:article:cancel")
async def pipeline_article_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
) -> None:
    """Cancel article pipeline, clear FSM and checkpoint."""
    await state.clear()
    await _clear_checkpoint(redis, user.id)
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        await callback.message.edit_text("Pipeline отменён.")
    await callback.answer()
