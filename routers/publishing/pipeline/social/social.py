"""Social Pipeline — steps 1 and 3: project/category selection (F6.1).

FSM: SocialPipelineFSM (28 states, FSM_SPEC.md §2.2).
UX: UX_PIPELINE.md §5 (steps 1-7, inline sub-flows).
Rules: .claude/rules/pipeline.md.

Step 1: Project selection (reuses same logic as article pipeline).
Step 2: Connection selection (F6.2 — see connection.py).
Step 3: Category selection (reuses same logic as article pipeline).
"""

from __future__ import annotations

import html
import time

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_message
from bot.service_factory import CategoryServiceFactory, ProjectServiceFactory
from bot.validators import URL_RE
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import ProjectCreate, User
from keyboards.inline import cancel_kb, menu_kb
from keyboards.pipeline import (
    pipeline_categories_kb,
    pipeline_no_projects_kb,
    pipeline_projects_kb,
)
from routers.publishing.pipeline._common import (
    SocialPipelineFSM,
    clear_checkpoint,
    save_checkpoint,
)
from routers.publishing.pipeline.social.connection import (
    _show_connection_step,
    _show_connection_step_msg,
)
from routers.publishing.pipeline.social.readiness import (
    show_social_readiness_check,
    show_social_readiness_check_msg,
)
from services.categories import CategoryService

log = structlog.get_logger()
router = Router()

# Total step count for social pipeline (displayed in step headers)
_TOTAL_STEPS = 5


# ---------------------------------------------------------------------------
# Step 1: Entry point — pipeline:social:start
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:social:start")
async def pipeline_social_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start social pipeline — show project selection (step 1).

    UX_PIPELINE.md §5.1:
    - 0 projects -> inline create
    - 1 project -> auto-select, skip to step 2
    - >1 projects -> show list with pagination
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # Clear any active FSM (E29)
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        log.info("pipeline.social.fsm_interrupted", user_id=user.id, interrupted=interrupted)

    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    if not projects:
        await msg.edit_text(
            f"Пост (1/{_TOTAL_STEPS}) — Проект\n\nДля начала создадим проект — это 30 секунд.",
            reply_markup=pipeline_no_projects_kb(pipeline_type="social"),
        )
        await state.set_state(SocialPipelineFSM.select_project)
        await save_checkpoint(redis, user.id, current_step="select_project", pipeline_type="social")
        await callback.answer()
        return

    if len(projects) == 1:
        project = projects[0]
        await state.update_data(project_id=project.id, project_name=project.name)
        await _show_connection_step(
            callback,
            state,
            user,
            db,
            redis,
            project.id,
            project.name,
            http_client=http_client,
        )
        await callback.answer()
        return

    await msg.edit_text(
        f"Пост (1/{_TOTAL_STEPS}) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_projects_kb(projects, pipeline_type="social"),
    )
    await state.set_state(SocialPipelineFSM.select_project)
    await save_checkpoint(redis, user.id, current_step="select_project", pipeline_type="social")
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.select_project,
    F.data.regexp(r"^pipeline:social:(\d+):select$"),
)
async def pipeline_select_project(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Handle project selection from list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return
    project_id = int(callback.data.split(":")[2])

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)

    if project is None:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    await state.update_data(project_id=project.id, project_name=project.name)
    await _show_connection_step(
        callback,
        state,
        user,
        db,
        redis,
        project.id,
        project.name,
        http_client=http_client,
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.select_project,
    F.data.regexp(r"^page:pipeline_social_projects:\d+$"),
)
async def pipeline_projects_page(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Handle project list pagination."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    page = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    await msg.edit_text(
        f"Пост (1/{_TOTAL_STEPS}) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_projects_kb(projects, page=page, pipeline_type="social"),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 1 sub-flow: Inline project creation (4 states)
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_project,
    F.data == "pipeline:social:create_project",
)
async def pipeline_start_create_project(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start inline project creation within social pipeline."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.set_state(SocialPipelineFSM.create_project_name)
    await state.update_data(last_update_time=time.time())
    await msg.edit_text(
        f"Пост (1/{_TOTAL_STEPS}) — Создание проекта\n\nКак назовём проект?\n<i>Пример: Мебель Комфорт</i>",
    )
    await callback.answer()


@router.message(SocialPipelineFSM.create_project_name, F.text)
async def pipeline_create_project_name(
    message: Message,
    state: FSMContext,
) -> None:
    """Inline project creation step 1: project name (2-100 chars)."""
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 100:
        await message.answer(
            "Название должно быть от 2 до 100 символов.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    await state.update_data(new_project_name=text, last_update_time=time.time())
    await state.set_state(SocialPipelineFSM.create_project_company)
    await message.answer(
        "Как называется ваша компания?\n<i>Пример: ООО Мебель Комфорт</i>",
        reply_markup=cancel_kb("pipeline:social:cancel"),
    )


@router.message(SocialPipelineFSM.create_project_company, F.text)
async def pipeline_create_project_company(
    message: Message,
    state: FSMContext,
) -> None:
    """Inline project creation step 2: company name (2-255 chars)."""
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 255:
        await message.answer(
            "Название компании: от 2 до 255 символов.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    await state.update_data(new_company_name=text, last_update_time=time.time())
    await state.set_state(SocialPipelineFSM.create_project_spec)
    await message.answer(
        "Опишите специализацию в 2-3 словах.\n<i>Пример: мебель на заказ</i>",
        reply_markup=cancel_kb("pipeline:social:cancel"),
    )


@router.message(SocialPipelineFSM.create_project_spec, F.text)
async def pipeline_create_project_spec(
    message: Message,
    state: FSMContext,
) -> None:
    """Inline project creation step 3: specialization (2-500 chars)."""
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 500:
        await message.answer(
            "Специализация: от 2 до 500 символов.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    await state.update_data(new_specialization=text, last_update_time=time.time())
    await state.set_state(SocialPipelineFSM.create_project_url)
    await message.answer(
        "Адрес сайта (необязательно).\nЕсли нет — напишите «Пропустить».\n<i>Пример: comfort-mebel.ru</i>",
        reply_markup=cancel_kb("pipeline:social:cancel"),
    )


@router.message(SocialPipelineFSM.create_project_url, F.text)
async def pipeline_create_project_url(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Inline project creation step 4: URL -> create project -> proceed to step 2."""
    text = (message.text or "").strip()

    website_url: str | None = None
    if text.lower() not in ("пропустить", "нет", "-", ""):
        if not URL_RE.match(text):
            await message.answer(
                "Некорректный URL. Попробуйте ещё раз или напишите «Пропустить».",
                reply_markup=cancel_kb("pipeline:social:cancel"),
            )
            return
        website_url = text if text.startswith("http") else f"https://{text}"

    data = await state.get_data()
    proj_svc = project_service_factory(db)
    project = await proj_svc.create_project(
        ProjectCreate(
            user_id=user.id,
            name=data["new_project_name"],
            company_name=data["new_company_name"],
            specialization=data["new_specialization"],
            website_url=website_url,
        )
    )

    if not project:
        await state.clear()
        await clear_checkpoint(redis, user.id)
        await message.answer("Достигнут лимит проектов.")
        return

    log.info("pipeline.social.project_created", project_id=project.id, user_id=user.id)

    await state.update_data(project_id=project.id, project_name=project.name)
    await message.answer(f"Проект «{html.escape(project.name)}» создан!")

    # Proceed to step 2 (connection selection)
    await _show_connection_step_msg(
        message,
        state,
        user,
        db,
        redis,
        project.id,
        project.name,
        http_client=http_client,
    )


# ---------------------------------------------------------------------------
# Step 2: Connection selection (F6.2 — implemented in connection.py)
# ---------------------------------------------------------------------------

# _show_connection_step and _show_connection_step_msg are imported
# from connection.py at module level below.


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

    UX_PIPELINE.md §5.3:
    - 0 categories -> inline create (text input)
    - 1 category -> auto-select, skip to step 4
    - >1 categories -> show list with pagination
    """
    msg = safe_message(callback)
    if not msg:
        return

    cat_svc = CategoryService(db=db)
    categories = await cat_svc.list_by_project(project_id, user.id) or []

    if not categories:
        await msg.edit_text(
            f"Пост (3/{_TOTAL_STEPS}) — Тема\n\nО чём будет пост? Назовите тему.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        await state.set_state(SocialPipelineFSM.create_category_name)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_category",
            pipeline_type="social",
            project_id=project_id,
            project_name=project_name,
        )
        return

    if len(categories) == 1:
        cat = categories[0]
        await state.update_data(category_id=cat.id, category_name=cat.name)
        await show_social_readiness_check(callback, state, user, db, redis)
        return

    await msg.edit_text(
        f"Пост (3/{_TOTAL_STEPS}) -- Тема\n\nКакая тема?",
        reply_markup=pipeline_categories_kb(categories, project_id, pipeline_type="social"),
    )
    await state.set_state(SocialPipelineFSM.select_category)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_category",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
    )


async def _show_category_step_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
) -> None:
    """Show category selection via message (non-edit context)."""
    cat_svc = CategoryService(db=db)
    categories = await cat_svc.list_by_project(project_id, user.id) or []

    if not categories:
        await message.answer(
            f"Пост (3/{_TOTAL_STEPS}) -- Тема\n\nО чём будет пост? Назовите тему.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        await state.set_state(SocialPipelineFSM.create_category_name)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_category",
            pipeline_type="social",
            project_id=project_id,
            project_name=project_name,
        )
        return

    if len(categories) == 1:
        cat = categories[0]
        await state.update_data(category_id=cat.id, category_name=cat.name)
        await show_social_readiness_check_msg(message, state, user, db, redis)
        return

    await message.answer(
        f"Пост (3/{_TOTAL_STEPS}) -- Тема\n\nКакая тема?",
        reply_markup=pipeline_categories_kb(categories, project_id, pipeline_type="social"),
    )
    await state.set_state(SocialPipelineFSM.select_category)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_category",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
    )


@router.callback_query(
    SocialPipelineFSM.select_category,
    F.data.regexp(r"^pipeline:social:\d+:cat:(\d+)$"),
)
async def pipeline_select_category(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Handle category selection from list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[4])

    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(category_id, user.id)

    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.update_data(category_id=category.id, category_name=category.name)

    await show_social_readiness_check(callback, state, user, db, redis)
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.select_category,
    F.data.regexp(r"^page:pipeline_social_categories:\d+$"),
)
async def pipeline_categories_page(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Handle category list pagination."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await callback.answer("Проект не выбран.", show_alert=True)
        return

    page = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    categories = await cat_svc.list_by_project(project_id, user.id) or []

    await msg.edit_text(
        f"Пост (3/{_TOTAL_STEPS}) — Тема\n\nКакая тема?",
        reply_markup=pipeline_categories_kb(categories, project_id, page=page, pipeline_type="social"),
    )
    await callback.answer()


@router.message(SocialPipelineFSM.create_category_name)
async def pipeline_create_category_name(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Inline category creation — user typed a category name."""
    name = (message.text or "").strip()
    if not name or len(name) < 2 or len(name) > 100:
        await message.answer(
            "Введите название темы (от 2 до 100 символов).",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await message.answer("Проект не выбран. Начните создание поста заново.", reply_markup=menu_kb())
        return

    cat_svc = category_service_factory(db)
    category = await cat_svc.create_category(project_id, user.id, name)
    if category is None:
        await message.answer("Не удалось создать категорию. Попробуйте снова.", reply_markup=menu_kb())
        return

    await state.update_data(category_id=category.id, category_name=category.name)
    await message.answer(f"Тема «{html.escape(category.name)}» создана.")

    await show_social_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Cancel handler
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:social:cancel")
async def pipeline_social_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
) -> None:
    """Cancel social pipeline, clear FSM and checkpoint."""
    await state.clear()
    await clear_checkpoint(redis, user.id)
    msg = safe_message(callback)
    if msg:
        await msg.edit_text("Публикация отменена.", reply_markup=menu_kb())
    await callback.answer()
