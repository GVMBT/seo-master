"""Article Pipeline — Goal-Oriented Pipeline for article creation (F5).

FSM: ArticlePipelineFSM (20 states, FSM_SPEC.md §1).
UX: UX_PIPELINE.md §4 (steps 1-8, inline sub-flows).
Rules: .claude/rules/pipeline.md.

This file implements steps 1-3 (selection) + inline sub-flows (F5.2):
- Inline project creation (1 state: name)
- Inline WP connection (3 states: url → login → password)
- Inline category creation (1 state: name)
Step 4 (readiness) is in readiness.py. Steps 5-8 will be added in F5.4.
"""

from __future__ import annotations

import html
import time

import httpx
import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.service_factory import CategoryServiceFactory, ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from bot.validators import URL_RE
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, ProjectCreate, User
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import cancel_kb, menu_kb
from keyboards.pipeline import (
    pipeline_categories_kb,
    pipeline_no_projects_kb,
    pipeline_no_wp_kb,
    pipeline_preview_kb,
    pipeline_projects_kb,
)
from routers.publishing.pipeline._common import (
    ArticlePipelineFSM,
    clear_checkpoint,
    save_checkpoint,
)
from routers.publishing.pipeline.readiness import (
    show_readiness_check,
    show_readiness_check_msg,
)
from services.categories import CategoryService
from services.connections import ConnectionService

log = structlog.get_logger()
router = Router()

def _get_image_count(category: object, project: object | None = None) -> int:
    """Extract image count from project/category image_settings, default 4.

    Fallback: project.image_settings -> category.image_settings.
    """
    proj_settings = getattr(project, "image_settings", None) if project else None
    cat_settings = getattr(category, "image_settings", None)
    settings = proj_settings or cat_settings or {}
    count = settings.get("count", 0) if isinstance(settings, dict) else 0
    try:
        return max(0, int(count))
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Step 1: Entry point — pipeline:article:start
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:article:start")
async def pipeline_article_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start article pipeline — show project selection (step 1).

    UX_PIPELINE.md §4.1:
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
        log.info("pipeline.article.fsm_interrupted", user_id=user.id, interrupted=interrupted)

    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    if not projects:
        # No projects — offer inline create
        text = (
            Screen(E.DOC, S.ARTICLE_STEP1_TITLE)
            .blank()
            .line(S.ARTICLE_STEP1_NO_PROJECTS)
            .build()
        )
        await safe_edit_text(msg, text, reply_markup=pipeline_no_projects_kb())
        await state.set_state(ArticlePipelineFSM.select_project)
        await save_checkpoint(redis, user.id, current_step="select_project")
        await callback.answer()
        return

    if len(projects) == 1:
        # Auto-select the only project
        project = projects[0]
        await state.update_data(
            project_id=project.id,
            project_name=project.name,
            company_name=project.company_name,
        )
        await _show_wp_step(callback, state, user, db, http_client, redis, project.id, project.name)
        await callback.answer()
        return

    # Multiple projects — show list
    text = (
        Screen(E.DOC, S.ARTICLE_STEP1_TITLE)
        .blank()
        .line(S.ARTICLE_STEP1_PROMPT)
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=pipeline_projects_kb(projects))
    await state.set_state(ArticlePipelineFSM.select_project)
    await save_checkpoint(redis, user.id, current_step="select_project")
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
    http_client: httpx.AsyncClient,
    redis: RedisClient,
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
    project_id = int(callback.data.split(":")[2])  # pipeline:article:{id}:select

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)

    if project is None:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    await state.update_data(
        project_id=project.id,
        project_name=project.name,
        company_name=project.company_name,
    )
    await _show_wp_step(callback, state, user, db, http_client, redis, project.id, project.name)
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.select_project,
    F.data.regexp(r"^page:pipeline_article_projects:\d+$"),
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

    cb_data = safe_callback_data(callback)
    page = int(cb_data.split(":")[-1])
    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    text = (
        Screen(E.DOC, S.ARTICLE_STEP1_TITLE)
        .blank()
        .line(S.ARTICLE_STEP1_PROMPT)
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=pipeline_projects_kb(projects, page=page))
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 1 shortcut: Start pipeline for a specific project (from project card)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^pipeline:article:project:\d+$"))
async def pipeline_article_from_project(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start article pipeline with a pre-selected project (from project card)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return
    project_id = int(callback.data.split(":")[3])  # pipeline:article:project:{id}

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        log.info("pipeline.article.fsm_interrupted", user_id=user.id, interrupted=interrupted)

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)
    if project is None:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    await state.update_data(
        project_id=project.id,
        project_name=project.name,
        company_name=project.company_name,
    )
    await _show_wp_step(callback, state, user, db, http_client, redis, project.id, project.name)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 1 sub-flow: Inline project creation (1 step)
# UX_PIPELINE.md §4.1 step 1: 0 projects -> inline create
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.select_project,
    F.data == "pipeline:article:create_project",
)
async def pipeline_start_create_project(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start inline project creation within pipeline."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.set_state(ArticlePipelineFSM.create_project_name)
    await state.update_data(last_update_time=time.time())
    text = (
        Screen(E.DOC, S.ARTICLE_CREATE_PROJECT_TITLE)
        .blank()
        .line(S.PROJECT_CREATE_QUESTION)
        .hint(S.PROJECT_CREATE_HINT)
        .build()
    )
    await safe_edit_text(msg, text)
    await callback.answer()


@router.message(ArticlePipelineFSM.create_project_name, F.text)
async def pipeline_create_project_name(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Inline project creation: name (2-100 chars) -> create -> proceed to step 2."""
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 100:
        await message.answer(
            "Название должно быть от 2 до 100 символов.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    proj_svc = project_service_factory(db)
    project = await proj_svc.create_project(
        ProjectCreate(user_id=user.id, name=text, company_name=text)
    )

    if not project:
        await state.clear()
        await clear_checkpoint(redis, user.id)
        await message.answer("Достигнут лимит проектов.")
        return

    log.info("pipeline.project_created", project_id=project.id, user_id=user.id)

    await state.update_data(
        project_id=project.id,
        project_name=project.name,
        company_name=project.company_name,
    )
    await message.answer(f"Проект «{html.escape(project.name)}» создан!")

    # Proceed to step 2 (WP check) — message context, can't edit
    await _show_wp_step_msg(message, state, user, db, http_client, redis, project.id, project.name)


# ---------------------------------------------------------------------------
# Step 2: WP connection check
# ---------------------------------------------------------------------------


async def _show_wp_step(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
    *,
    auto_skip: bool = True,
) -> None:
    """Show WP connection selection (step 2).

    UX_PIPELINE.md §4.1:
    - 1 WP connection -> auto-select, skip to step 3 (unless auto_skip=False)
    - 0 WP connections -> offer connect or preview-only

    Rule: 1 project = max 1 WordPress connection. No multi-WP branch needed.
    """
    msg = safe_message(callback)
    if not msg:
        return

    conn_svc = ConnectionService(db, http_client)
    wp_connections = await conn_svc.get_by_project_and_platform(project_id, "wordpress")

    if wp_connections and auto_skip:
        # Auto-select the WP connection (max 1 per project)
        conn = wp_connections[0]
        await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
        await _show_category_step(callback, state, user, db, redis, project_id, project_name)
        return

    if wp_connections:
        # WP exists but back navigation — show selection without auto-skip
        conn = wp_connections[0]
        await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
        await safe_edit_text(
            msg,
            Screen(E.DOC, S.ARTICLE_STEP2_TITLE)
            .blank()
            .line(f"{E.CHECK} WordPress подключён: {html.escape(conn.identifier)}")
            .build(),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Продолжить", callback_data="pipeline:article:wp_continue")],
                    [InlineKeyboardButton(text="Назад", callback_data="pipeline:article:back_project")],
                ]
            ),
        )
        await state.set_state(ArticlePipelineFSM.select_wp)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_wp",
            project_id=project_id,
            project_name=project_name,
        )
        return

    # No WP connections — offer connect or preview-only
    await safe_edit_text(
        msg,
        Screen(E.DOC, S.ARTICLE_STEP2_TITLE).blank().line(S.ARTICLE_STEP2_NO_WP).build(),
        reply_markup=pipeline_no_wp_kb(),
    )
    await state.set_state(ArticlePipelineFSM.select_wp)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_wp",
        project_id=project_id,
        project_name=project_name,
    )


@router.callback_query(
    ArticlePipelineFSM.select_wp,
    F.data == "pipeline:article:wp_continue",
)
async def pipeline_wp_continue(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Continue from WP step to category selection (step 3)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")

    if not project_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

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
    http_client: httpx.AsyncClient,
    redis: RedisClient,
) -> None:
    """User chose preview-only (no WP publication)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")

    await state.update_data(connection_id=None, wp_identifier=None, preview_only=True)
    if not project_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return
    await callback.answer()
    await _show_category_step(callback, state, user, db, redis, project_id, project_name)


async def _show_wp_step_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
) -> None:
    """Show WP connection step via message (non-edit context).

    Used after inline project creation (text messages can't be edited).
    Same logic as _show_wp_step but sends new messages.
    """
    conn_svc = ConnectionService(db, http_client)
    wp_connections = await conn_svc.get_by_project_and_platform(project_id, "wordpress")

    if wp_connections:
        conn = wp_connections[0]
        await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
        await _show_category_step_msg(message, state, user, db, redis, project_id, project_name)
        return

    await message.answer(
        Screen(E.DOC, S.ARTICLE_STEP2_TITLE).blank().line(S.ARTICLE_STEP2_NO_WP).build(),
        reply_markup=pipeline_no_wp_kb(),
    )
    await state.set_state(ArticlePipelineFSM.select_wp)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_wp",
        project_id=project_id,
        project_name=project_name,
    )


# ---------------------------------------------------------------------------
# Step 2 sub-flow: Inline WP connection (3 states)
# UX_PIPELINE.md §4.1 step 2: 0 WP -> inline connect (3 questions)
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.select_wp,
    F.data == "pipeline:article:connect_wp",
)
async def pipeline_start_connect_wp(
    callback: CallbackQuery,
    state: FSMContext,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
    user: User,
) -> None:
    """Start inline WP connection within pipeline."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # If project already has website_url, skip URL step and go to login
    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id:
        proj_svc = project_service_factory(db)
        project = await proj_svc.get_owned_project(project_id, user.id)
        if project and project.website_url:
            await state.update_data(wp_url=project.website_url, last_update_time=time.time())
            await state.set_state(ArticlePipelineFSM.connect_wp_login)
            await safe_edit_text(
                msg,
                f"{E.DOC} <b>{S.ARTICLE_STEP2_TITLE}</b>\n\n"
                f"Сайт: {html.escape(project.website_url)}\n\n"
                f"Введите логин WordPress (имя пользователя).",
            )
            await callback.answer()
            return

    await state.set_state(ArticlePipelineFSM.connect_wp_url)
    await state.update_data(last_update_time=time.time())
    await safe_edit_text(
        msg,
        Screen(E.DOC, S.ARTICLE_STEP2_TITLE)
        .blank()
        .line("Введите адрес вашего сайта.")
        .line("<i>Пример: example.com</i>")
        .build(),
    )
    await callback.answer()


@router.message(ArticlePipelineFSM.connect_wp_url, F.text)
async def pipeline_connect_wp_url(
    message: Message,
    state: FSMContext,
) -> None:
    """Inline WP connection step 1: site URL."""
    text = (message.text or "").strip()
    if not URL_RE.match(text):
        await message.answer(
            "Некорректный URL. Попробуйте ещё раз.",
            reply_markup=cancel_kb("pipeline:article:cancel_wp"),
        )
        return

    url = text if text.startswith("http") else f"https://{text}"
    await state.update_data(wp_url=url, last_update_time=time.time())
    await state.set_state(ArticlePipelineFSM.connect_wp_login)
    await message.answer(
        "Введите логин WordPress (имя пользователя).",
        reply_markup=cancel_kb("pipeline:article:cancel_wp"),
    )


@router.message(ArticlePipelineFSM.connect_wp_login, F.text)
async def pipeline_connect_wp_login(
    message: Message,
    state: FSMContext,
) -> None:
    """Inline WP connection step 2: login."""
    text = (message.text or "").strip()
    if len(text) < 1 or len(text) > 100:
        await message.answer(
            "Логин: от 1 до 100 символов.",
            reply_markup=cancel_kb("pipeline:article:cancel_wp"),
        )
        return

    await state.update_data(wp_login=text, last_update_time=time.time())
    await state.set_state(ArticlePipelineFSM.connect_wp_password)
    await message.answer(
        "Введите Application Password.\n\n"
        "Создайте его в WordPress: Пользователи → Профиль → Application Passwords.\n"
        "Формат: xxxx xxxx xxxx xxxx xxxx xxxx",
        reply_markup=cancel_kb("pipeline:article:cancel_wp"),
    )


@router.message(ArticlePipelineFSM.connect_wp_password, F.text)
async def pipeline_connect_wp_password(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Inline WP connection step 3: password -> validate -> create -> proceed to step 3."""
    text = (message.text or "").strip()

    # Delete message with password for security
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("pipeline.failed_to_delete_password_message", reason=str(exc))

    if len(text) < 10:
        await message.answer(
            "Application Password слишком короткий. Попробуйте ещё раз.",
            reply_markup=cancel_kb("pipeline:article:cancel_wp"),
        )
        return

    data = await state.get_data()
    wp_url = data.get("wp_url")
    wp_login = data.get("wp_login")
    project_id = data.get("project_id")
    if not (wp_url and wp_login and project_id):
        await state.clear()
        await clear_checkpoint(redis, user.id)
        await message.answer("Сессия устарела. Начните подключение заново.", reply_markup=menu_kb())
        return
    project_name: str = data.get("project_name", "")

    # Validate WP REST API via service
    conn_svc = ConnectionService(db, http_client)
    error = await conn_svc.validate_wordpress(wp_url, wp_login, text)
    if error:
        await message.answer(
            error,
            reply_markup=cancel_kb("pipeline:article:cancel_wp"),
        )
        return

    # Re-validate project ownership
    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)
    if not project:
        await state.clear()
        await clear_checkpoint(redis, user.id)
        await message.answer("Проект не найден.", reply_markup=menu_kb())
        return

    # Check max 1 WP per project
    existing_wp = await conn_svc.get_by_project_and_platform(project_id, "wordpress")
    if existing_wp:
        await message.answer("К проекту уже подключён WordPress-сайт.")
        # Still proceed — auto-select the existing one
        conn = existing_wp[0]
        await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
        await _show_category_step_msg(message, state, user, db, redis, project_id, project_name)
        return

    # Create connection
    identifier = wp_url.replace("https://", "").replace("http://", "").rstrip("/")
    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="wordpress",
            identifier=identifier,
        ),
        raw_credentials={"url": wp_url, "login": wp_login, "app_password": text},
    )

    log.info("pipeline.wp_connected", conn_id=conn.id, project_id=project_id, identifier=identifier)

    await state.update_data(connection_id=conn.id, wp_identifier=conn.identifier)
    await message.answer(f"WordPress ({html.escape(identifier)}) подключён!")

    # If connecting from preview (Variant B → publish), return to preview screen
    if data.get("from_preview") and data.get("preview_id"):
        await state.update_data(from_preview=False)
        await _return_to_preview(message, state, user, db, redis, data["preview_id"], conn.id)
        return

    # Proceed to step 3 (category) — message context
    await _show_category_step_msg(message, state, user, db, redis, project_id, project_name)


@router.callback_query(F.data == "pipeline:article:cancel_wp")
async def pipeline_cancel_wp_subflow(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Cancel WP connection sub-flow — return to step 2 screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")

    if project_id:
        await safe_edit_text(
            msg,
            Screen(E.DOC, S.ARTICLE_STEP2_TITLE).blank().line(S.ARTICLE_STEP2_NO_WP).build(),
            reply_markup=pipeline_no_wp_kb(),
        )
        await state.set_state(ArticlePipelineFSM.select_wp)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_wp",
            project_id=project_id,
            project_name=project_name,
        )
    else:
        await state.clear()
        await clear_checkpoint(redis, user.id)
        await safe_edit_text(msg, "Публикация отменена.", reply_markup=menu_kb())

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
    msg = safe_message(callback)
    if not msg:
        return

    cat_svc = CategoryService(db=db)
    categories = await cat_svc.list_by_project(project_id, user.id) or []

    if not categories:
        # No categories — prompt for inline creation
        await safe_edit_text(
            msg,
            Screen(E.DOC, S.ARTICLE_STEP3_TITLE).blank().line(S.ARTICLE_STEP3_PROMPT).build(),
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        await state.set_state(ArticlePipelineFSM.create_category_name)
        await save_checkpoint(
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
        proj = await ProjectsRepository(db).get_by_id(project_id)
        await state.update_data(
            category_id=cat.id,
            category_name=cat.name,
            image_count=_get_image_count(cat, proj),
        )
        await show_readiness_check(callback, state, user, db, redis)
        return

    # Multiple categories — show list
    await safe_edit_text(
        msg,
        Screen(E.DOC, S.ARTICLE_STEP3_TITLE).blank().line(S.ARTICLE_STEP3_WHICH).build(),
        reply_markup=pipeline_categories_kb(categories, project_id),
    )
    await state.set_state(ArticlePipelineFSM.select_category)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_category",
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
    """Show category selection via message (non-edit context).

    Used after inline project/WP creation (text messages can't be edited).
    Same logic as _show_category_step but sends new messages.
    """
    cat_svc = CategoryService(db=db)
    categories = await cat_svc.list_by_project(project_id, user.id) or []

    if not categories:
        await message.answer(
            Screen(E.DOC, S.ARTICLE_STEP3_TITLE).blank().line(S.ARTICLE_STEP3_PROMPT).build(),
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        await state.set_state(ArticlePipelineFSM.create_category_name)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_category",
            project_id=project_id,
            project_name=project_name,
        )
        return

    if len(categories) == 1:
        cat = categories[0]
        proj = await ProjectsRepository(db).get_by_id(project_id)
        await state.update_data(
            category_id=cat.id,
            category_name=cat.name,
            image_count=_get_image_count(cat, proj),
        )
        await show_readiness_check_msg(message, state, user, db, redis)
        return

    await message.answer(
        Screen(E.DOC, S.ARTICLE_STEP3_TITLE).blank().line(S.ARTICLE_STEP3_WHICH).build(),
        reply_markup=pipeline_categories_kb(categories, project_id),
    )
    await state.set_state(ArticlePipelineFSM.select_category)
    await save_checkpoint(
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
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Handle category selection from list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    category_id = int(parts[4])

    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(category_id, user.id)

    if category is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await callback.answer()
    proj = await ProjectsRepository(db).get_by_id(category.project_id)
    await state.update_data(
        category_id=category.id,
        category_name=category.name,
        image_count=_get_image_count(category, proj),
    )
    await show_readiness_check(callback, state, user, db, redis)


@router.message(ArticlePipelineFSM.create_category_name)
async def pipeline_create_category_name(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Inline category creation — user typed a category name.

    UX_PIPELINE.md §4.1 step 3: 0 categories -> text input.
    """
    name = (message.text or "").strip()
    if not name or len(name) < 2 or len(name) > 100:
        await message.answer(
            "Введите название темы (от 2 до 100 символов).",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await message.answer("Проект не выбран. Начните создание статьи заново.", reply_markup=menu_kb())
        return

    cat_svc = category_service_factory(db)
    category = await cat_svc.create_category(project_id, user.id, name)
    if category is None:
        await message.answer("Не удалось создать категорию. Попробуйте снова.", reply_markup=menu_kb())
        return

    proj = await ProjectsRepository(db).get_by_id(project_id)
    await state.update_data(
        category_id=category.id,
        category_name=category.name,
        image_count=_get_image_count(category, proj),
    )
    await message.answer(f"Тема «{html.escape(category.name)}» создана.")

    # Proceed to readiness (step 4)
    # For text messages we can't edit — send new message
    await show_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Back navigation: step 2 -> step 1, step 3 -> step 2
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.select_wp,
    F.data == "pipeline:article:back_project",
)
async def pipeline_back_to_project(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Go back from step 2 (WP) to step 1 (project selection)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    if not projects:
        text = (
            Screen(E.DOC, S.ARTICLE_STEP1_TITLE)
            .blank()
            .line(S.ARTICLE_STEP1_NO_PROJECTS)
            .build()
        )
        await safe_edit_text(msg, text, reply_markup=pipeline_no_projects_kb())
    else:
        text = (
            Screen(E.DOC, S.ARTICLE_STEP1_TITLE)
            .blank()
            .line(S.ARTICLE_STEP1_PROMPT)
            .build()
        )
        await safe_edit_text(msg, text, reply_markup=pipeline_projects_kb(projects))

    await state.set_state(ArticlePipelineFSM.select_project)
    await save_checkpoint(redis, user.id, current_step="select_project")
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.select_category,
    F.data == "pipeline:article:back_wp",
)
async def pipeline_back_to_wp(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
) -> None:
    """Go back from step 3 (category) to step 2 (WP)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")

    if not project_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    await _show_wp_step(
        callback, state, user, db, http_client, redis, project_id, project_name,
        auto_skip=False,
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Return to preview after WP connection from Variant B (F5.5)
# ---------------------------------------------------------------------------


async def _return_to_preview(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    preview_id: int,
    connection_id: int,
) -> None:
    """Return to preview screen after WP connection from Variant B.

    Loads the preview from DB, updates connection_id in state, and shows
    the preview with can_publish=True.
    """
    previews_repo = PreviewsRepository(db)
    preview = await previews_repo.get_by_id(preview_id)
    if not preview or preview.user_id != user.id or preview.status != "draft":
        await message.answer("Превью устарело. Начните заново.", reply_markup=menu_kb())
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    await state.update_data(connection_id=connection_id, preview_only=False)
    await state.set_state(ArticlePipelineFSM.preview)

    telegraph_url = preview.telegraph_url
    kb = pipeline_preview_kb(
        telegraph_url,
        can_publish=True,
        regen_count=preview.regeneration_count,
        regen_cost=preview.tokens_charged or 0,
    )

    preview_text = (
        Screen(E.CHECK, S.ARTICLE_READY_TITLE)
        .blank()
        .line(f"<b>{html.escape(preview.title or '')}</b>")
        .blank()
        .field(E.HASHTAG, "Ключевая фраза", html.escape(preview.keyword or ""))
        .field(E.DOC, "Объём", f"~{preview.word_count or 0} слов | Изображения: {preview.images_count or 0}")
        .separator()
        .line(f"\n{E.WALLET} Списано: {preview.tokens_charged or 0} ток.")
        .build()
    )
    await message.answer(preview_text, reply_markup=kb)
    await save_checkpoint(
        redis,
        user.id,
        current_step="preview",
        project_id=preview.project_id,
        category_id=preview.category_id,
        connection_id=connection_id,
        preview_id=preview.id,
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
    await clear_checkpoint(redis, user.id)
    msg = safe_message(callback)
    if msg:
        await safe_edit_text(msg, "Публикация отменена.", reply_markup=menu_kb())
    await callback.answer()
