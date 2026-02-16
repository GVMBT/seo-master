"""Router: Article Pipeline -- Goal-Oriented funnel for article creation.

Phase 13A: steps 1-3 (select project/WP/category), 5-8 (confirm/generate/preview/publish).
Readiness check (step 4) + inline sub-flows -> Phase 13B.

PIPELINE_UX_PROPOSAL.md section 4.1, section 12, section 13 Phase A
FSM_SPEC.md: ArticlePipelineFSM (23 states)
"""

from __future__ import annotations

import html
import json
import time
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import get_settings
from bot.exceptions import InsufficientBalanceError
from bot.fsm_utils import ensure_no_active_fsm
from cache.client import RedisClient
from cache.keys import PIPELINE_CHECKPOINT_TTL, CacheKeys
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import (
    ArticlePreview,
    ArticlePreviewCreate,
    ArticlePreviewUpdate,
    PublicationLogCreate,
    User,
)
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from keyboards.errors import error_generic_kb, error_no_keywords_kb, error_not_found_kb
from keyboards.pipeline import (
    pipeline_category_list_kb,
    pipeline_confirm_kb,
    pipeline_no_entities_kb,
    pipeline_post_publish_kb,
    pipeline_preview_kb,
    pipeline_project_list_kb,
    pipeline_resume_kb,
    pipeline_wp_list_kb,
)
from routers._helpers import guard_callback_message
from services.tokens import TokenService, estimate_article_cost

if TYPE_CHECKING:
    import httpx

    from services.ai.orchestrator import AIOrchestrator
    from services.ai.rate_limiter import RateLimiter
    from services.storage import ImageStorage

log = structlog.get_logger()

router = Router(name="article_pipeline")


# ---------------------------------------------------------------------------
# FSM Definition (full 23 states per FSM_SPEC.md -- handlers added per phase)
# ---------------------------------------------------------------------------


class ArticlePipelineFSM(StatesGroup):
    # Step 1: select project
    select_project = State()
    # Inline: create project (Phase 13B)
    create_project_name = State()
    create_project_company = State()
    create_project_spec = State()
    create_project_url = State()
    # Step 2: select WP connection
    select_wp = State()
    # Inline: connect WP (Phase 13B)
    connect_wp_url = State()
    connect_wp_login = State()
    connect_wp_password = State()
    # Step 3: select category
    select_category = State()
    # Inline: create category (Phase 13B)
    create_category_name = State()
    # Step 4: readiness check (Phase 13B)
    readiness_check = State()
    readiness_keywords_products = State()
    readiness_keywords_geo = State()
    readiness_keywords_qty = State()
    readiness_keywords_generating = State()
    readiness_description = State()
    configure_images = State()
    # Step 5: confirm cost
    confirm_cost = State()
    # Step 6: generating
    generating = State()
    # Step 7: preview
    preview = State()
    # Step 8: publishing
    publishing = State()
    # Regeneration
    regenerating = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_pipeline_preview(preview: ArticlePreview, cost: int, telegraph_url: str | None) -> str:
    """Format preview text for pipeline step 7."""
    title = html.escape(preview.title or "Без заголовка")
    word_count = preview.word_count or 0
    images_count = preview.images_count or 0

    lines = [
        "Статья (5/5) — Превью\n",
        f"<b>{title}</b>",
        f"Слов: {word_count}, изображений: {images_count}",
        f"Стоимость: {cost} токенов",
    ]
    url = telegraph_url or preview.telegraph_url
    if url:
        lines.append(f"\nПревью: {url}")
    elif preview.content_html:
        snippet = preview.content_html[:500]
        lines.append(f"\n{html.escape(snippet)}...")

    lines.append("\nПревью приблизительное. На сайте статья будет в вашем дизайне.")
    return "\n".join(lines)


async def _get_last_project_id(db: SupabaseClient, user_id: int) -> int | None:
    """Get project_id of the user's most recent publication (for sorting)."""
    pub_repo = PublicationsRepository(db)
    logs = await pub_repo.get_by_user(user_id, limit=1)
    if logs:
        return logs[0].project_id
    return None


# ---------------------------------------------------------------------------
# Entry point -- callback pipeline:article:start
# ---------------------------------------------------------------------------


async def _start_pipeline_fresh(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Shared logic: load projects, auto-select or show list. Used by entry + restart."""
    # E26: Clear any active FSM
    await ensure_no_active_fsm(state)

    projects = await ProjectsRepository(db).get_by_user(user.id)
    if not projects:
        await msg.edit_text(
            "Статья (1/5) — Проект\n\nУ вас нет проектов. Создайте первый проект.",
            reply_markup=pipeline_no_entities_kb("project").as_markup(),
        )
        return

    if len(projects) == 1:
        await state.set_state(ArticlePipelineFSM.select_wp)
        await state.update_data(project_id=projects[0].id)
        await show_wp_selection(msg, user, db, projects[0].id, state)
        return

    last_project_id = await _get_last_project_id(db, user.id)
    await state.set_state(ArticlePipelineFSM.select_project)
    await msg.edit_text(
        "Статья (1/5) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_project_list_kb(projects, last_used_id=last_project_id).as_markup(),
    )


@router.callback_query(F.data == "pipeline:article:start")
async def cb_pipeline_article_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Start article pipeline. Check for active pipeline conflict (E49)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # E49: Check for active pipeline checkpoint
    checkpoint_key = CacheKeys.pipeline_state(user.id)
    existing = await redis.get(checkpoint_key)
    if existing:
        try:
            checkpoint = json.loads(existing)
        except (json.JSONDecodeError, TypeError):
            checkpoint = {}
        step = checkpoint.get("current_step", "?")
        await msg.edit_text(
            f"У вас есть незавершённый pipeline.\nОстановились на: {step}\n",
            reply_markup=pipeline_resume_kb().as_markup(),
        )
        await callback.answer()
        return

    await _start_pipeline_fresh(msg, state, user, db, redis)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 1: select project
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.select_project,
    F.data.regexp(r"^pipeline:article:project:(\d+)$"),
)
async def cb_pipeline_select_project(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """User selected a project -> move to WP selection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return
    await state.set_state(ArticlePipelineFSM.select_wp)
    await state.update_data(project_id=project_id)
    await show_wp_selection(msg, user, db, project_id, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 2: WP selection helper + handler
# ---------------------------------------------------------------------------


async def show_wp_selection(
    msg: Message,
    user: User,
    db: SupabaseClient,
    project_id: int,
    state: FSMContext,
) -> None:
    """Show WP connection selection (HEAD validation deferred to generation)."""
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    connections = await ConnectionsRepository(db, cm).get_by_project(project_id)
    wp_connections = [c for c in connections if c.platform_type == "wordpress" and c.status == "active"]

    if not wp_connections:
        await msg.edit_text(
            "Статья (2/5) — WordPress\n\nДля публикации нужен WordPress-сайт.",
            reply_markup=pipeline_no_entities_kb("wp", project_id=project_id).as_markup(),
        )
        return

    if len(wp_connections) == 1:
        # Auto-select
        await state.update_data(connection_id=wp_connections[0].id, preview_only=False)
        await state.set_state(ArticlePipelineFSM.select_category)
        data = await state.get_data()
        await _show_category_selection(msg, user, db, data, state)
        return

    # Multiple WP connections (E28)
    await msg.edit_text(
        "Статья (2/5) — WordPress\n\nНа какой сайт?",
        reply_markup=pipeline_wp_list_kb(wp_connections, project_id).as_markup(),
    )


@router.callback_query(
    ArticlePipelineFSM.select_wp,
    F.data.regexp(r"^pipeline:article:wp:(\d+|preview_only)$"),
)
async def cb_pipeline_select_wp(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """User selected WP connection or preview-only."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    target = callback.data.split(":")[-1]  # type: ignore[union-attr]
    if target == "preview_only":
        await state.update_data(connection_id=None, preview_only=True)
    else:
        await state.update_data(connection_id=int(target), preview_only=False)

    await state.set_state(ArticlePipelineFSM.select_category)
    data = await state.get_data()
    await _show_category_selection(msg, user, db, data, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 3: category selection
# ---------------------------------------------------------------------------


async def _show_category_selection(
    msg: Message,
    user: User,
    db: SupabaseClient,
    data: dict[str, Any],
    state: FSMContext,
) -> None:
    """Show category selection."""
    project_id = data["project_id"]
    categories = await CategoriesRepository(db).get_by_project(project_id)

    if not categories:
        await msg.edit_text(
            "Статья (3/5) — Тема\n\nВ проекте нет категорий.",
            reply_markup=pipeline_no_entities_kb("category", project_id=project_id).as_markup(),
        )
        return

    if len(categories) == 1:
        await state.update_data(category_id=categories[0].id)
        # Phase 13A: skip readiness -> go to confirm_cost
        await state.set_state(ArticlePipelineFSM.confirm_cost)
        await _show_confirm(msg, user, db, state)
        return

    await msg.edit_text(
        "Статья (3/5) — Тема\n\nКакая тема?",
        reply_markup=pipeline_category_list_kb(categories).as_markup(),
    )


@router.callback_query(
    ArticlePipelineFSM.select_category,
    F.data.regexp(r"^pipeline:article:cat:(\d+)$"),
)
async def cb_pipeline_select_category(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """User selected a category -> move to cost confirmation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    cat = await CategoriesRepository(db).get_by_id(category_id)
    data = await state.get_data()
    if not cat or cat.project_id != data.get("project_id"):
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    await state.update_data(category_id=category_id)
    await state.set_state(ArticlePipelineFSM.confirm_cost)
    await _show_confirm(msg, user, db, state)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 5: confirm cost
# ---------------------------------------------------------------------------


async def _show_confirm(msg: Message, user: User, db: SupabaseClient, state: FSMContext) -> None:
    """Show cost confirmation (GOD_MODE awareness)."""
    data = await state.get_data()
    settings = get_settings()
    is_god = user.id in settings.admin_ids

    cost = estimate_article_cost()

    project = await ProjectsRepository(db).get_by_id(data["project_id"])
    category = await CategoriesRepository(db).get_by_id(data["category_id"])

    project_name = html.escape(project.name) if project else "?"
    category_name = html.escape(category.name) if category else "?"
    conn_text = "Telegraph (превью)" if data.get("preview_only") else "WordPress"

    cost_text = f"~{cost} ток. (GOD_MODE -- бесплатно)" if is_god else f"~{cost} ток."

    text = (
        "Статья (4/5) — Подтверждение\n\n"
        f"{project_name} -> {conn_text}\n"
        f"Тема: {category_name}\n\n"
        f"Стоимость: {cost_text} | Баланс: {user.balance}"
    )

    await state.update_data(estimated_cost=cost)
    await msg.edit_text(text, reply_markup=pipeline_confirm_kb(cost, is_god).as_markup(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Step 6: generate
# ---------------------------------------------------------------------------


@router.callback_query(ArticlePipelineFSM.confirm_cost, F.data == "pipeline:article:generate")
async def cb_pipeline_generate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    rate_limiter: RateLimiter,
    ai_orchestrator: AIOrchestrator,
    image_storage: ImageStorage,
    http_client: httpx.AsyncClient,
) -> None:
    """User confirmed -- start generation (step 6)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    settings = get_settings()
    cost = data.get("estimated_cost", 320)
    is_god = user.id in settings.admin_ids
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    connection_id = data.get("connection_id")

    if not category_id or not project_id:
        await callback.answer("Данные сессии потеряны. Начните заново.", show_alert=True)
        await state.clear()
        return

    # E25: rate limit check
    await rate_limiter.check(user.id, "text_generation")

    token_svc = TokenService(db, settings.admin_ids)

    # E01: balance check
    if not is_god:
        has_balance = await token_svc.check_balance(user.id, cost)
        if not has_balance:
            from keyboards.publish import insufficient_balance_kb

            balance = await token_svc.get_balance(user.id)
            await msg.edit_text(
                token_svc.format_insufficient_msg(cost, balance),
                reply_markup=insufficient_balance_kb().as_markup(),
            )
            await callback.answer()
            return

    # Save checkpoint
    checkpoint = {
        "pipeline_type": "article",
        "current_step": "generating",
        "project_id": project_id,
        "connection_id": connection_id,
        "category_id": category_id,
        "preview_only": data.get("preview_only", False),
        "estimated_cost": cost,
    }
    await redis.set(
        CacheKeys.pipeline_state(user.id),
        json.dumps(checkpoint),
        ex=PIPELINE_CHECKPOINT_TTL,
    )

    await state.set_state(ArticlePipelineFSM.generating)
    await callback.answer()

    # Charge tokens
    try:
        await token_svc.charge(
            user_id=user.id,
            amount=cost,
            operation_type="article_generation",
            description=f"Pipeline article for category {category_id}",
        )
    except InsufficientBalanceError:
        from keyboards.publish import insufficient_balance_kb

        balance = await token_svc.get_balance(user.id)
        await msg.edit_text(
            token_svc.format_insufficient_msg(cost, balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await state.clear()
        await redis.delete(CacheKeys.pipeline_state(user.id))
        return
    except Exception:
        log.exception("pipeline_charge_failed", user_id=user.id)
        await msg.edit_text(
            "Ошибка списания токенов. Попробуйте позже.",
            reply_markup=error_generic_kb().as_markup(),
        )
        await state.clear()
        await redis.delete(CacheKeys.pipeline_state(user.id))
        return

    await state.update_data(tokens_charged=cost if not is_god else 0)

    # Progress: picking keyword
    await msg.edit_text("Статья — Генерация...\n\nПодбираю ключевую фразу...")

    # Keyword rotation
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await _pipeline_refund_and_error(
            msg,
            token_svc,
            user.id,
            cost,
            state,
            redis,
            "Категория не найдена.",
            reply_markup=error_not_found_kb("menu:main").as_markup(),
        )
        return

    pub_repo = PublicationsRepository(db)
    keyword, low_pool = await pub_repo.get_rotation_keyword(
        category_id,
        category.keywords,
        content_type="article",
    )
    if not keyword:
        await _pipeline_refund_and_error(
            msg,
            token_svc,
            user.id,
            cost,
            state,
            redis,
            "Нет доступных ключевых фраз.\nДобавьте фразы для генерации.",
            reply_markup=error_no_keywords_kb(category_id).as_markup(),
        )
        return

    await state.update_data(keyword=keyword)

    # Progress: generating article
    start_time = time.monotonic()
    await msg.edit_text(f"Статья — Генерация...\n\nГенерирую статью по фразе: {html.escape(keyword)}...")

    # Generate article via PreviewService (same as Toolbox flow)
    from services.preview import PreviewService

    preview_svc = PreviewService(ai_orchestrator, db, image_storage, http_client)
    previews_repo = PreviewsRepository(db)

    try:
        article = await preview_svc.generate_article_content(
            user_id=user.id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
        )
    except Exception:
        log.exception("pipeline_generation_failed", user_id=user.id, keyword=keyword)
        await _pipeline_refund_and_error(
            msg,
            token_svc,
            user.id,
            cost,
            state,
            redis,
            "Ошибка генерации статьи.",
            reply_markup=error_generic_kb().as_markup(),
        )
        return

    # Create preview record
    try:
        preview = await previews_repo.create(
            ArticlePreviewCreate(
                user_id=user.id,
                project_id=project_id,
                category_id=category_id,
                connection_id=connection_id,
                title=article.title,
                keyword=keyword,
                word_count=article.word_count,
                images_count=article.images_count,
                tokens_charged=cost,
                content_html=article.content_html,
                images=article.stored_images,
            )
        )
    except Exception:
        log.exception("pipeline_preview_create_failed", user_id=user.id)
        await _pipeline_refund_and_error(
            msg,
            token_svc,
            user.id,
            cost,
            state,
            redis,
            "Ошибка создания превью.",
            reply_markup=error_generic_kb().as_markup(),
        )
        return

    await state.update_data(preview_id=preview.id)

    # Telegraph preview (E05: fallback if fails)
    await msg.edit_text("Статья — Генерация...\n\nСоздаю превью...")
    telegraph_url: str | None = None
    telegraph_path: str | None = None
    try:
        from services.external.telegraph import TelegraphClient

        telegraph = TelegraphClient(http_client)
        page = await telegraph.create_page(
            title=preview.title or article.title,
            html=preview.content_html or "",
        )
        if page:
            telegraph_url = page.url
            telegraph_path = page.path
    except Exception:
        log.exception("pipeline_telegraph_failed", preview_id=preview.id)

    # Update preview with Telegraph info
    if telegraph_url:
        await previews_repo.update(
            preview.id,
            ArticlePreviewUpdate(
                telegraph_url=telegraph_url,
                telegraph_path=telegraph_path,
            ),
        )
        preview = await previews_repo.get_by_id(preview.id) or preview

    elapsed = int((time.monotonic() - start_time) * 1000)
    log.info(
        "pipeline_article_generated",
        user_id=user.id,
        preview_id=preview.id,
        keyword=keyword,
        generation_time_ms=elapsed,
    )

    # Show preview (step 7)
    await state.set_state(ArticlePipelineFSM.preview)
    await state.update_data(
        telegraph_url=telegraph_url,
        regeneration_count=0,
    )

    has_wp = not data.get("preview_only", False)

    warning = ""
    if low_pool:
        warning = "\nДобавьте ещё фраз для разнообразия контента."

    await msg.edit_text(
        _format_pipeline_preview(preview, cost, telegraph_url) + warning,
        reply_markup=pipeline_preview_kb(0, has_wp=has_wp).as_markup(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Step 7: preview actions (publish, regen, cancel)
# ---------------------------------------------------------------------------


@router.callback_query(ArticlePipelineFSM.preview, F.data == "pipeline:article:publish")
async def cb_pipeline_publish(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
    image_storage: ImageStorage,
    http_client: httpx.AsyncClient,
) -> None:
    """Publish article (step 8). E07: one-time transition."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # E07: set state FIRST to prevent double-click race (FSM filter is the guard)
    await state.set_state(ArticlePipelineFSM.publishing)
    await callback.answer()

    data = await state.get_data()

    if data.get("preview_only"):
        # Mark preview as viewed to prevent cleanup cron refund (P0-3)
        preview_id = data.get("preview_id")
        if preview_id:
            await PreviewsRepository(db).update(preview_id, ArticlePreviewUpdate(status="viewed"))
        # No WP -- just show Telegraph link
        await msg.edit_text(
            "Статья — Готово\n\n"
            f"Статья доступна по ссылке:\n{data.get('telegraph_url', 'Ссылка недоступна')}\n\n"
            "Подключите WordPress для публикации на сайт.",
        )
        await state.clear()
        await redis.delete(CacheKeys.pipeline_state(user.id))
        return

    preview_id = data.get("preview_id")
    if not preview_id:
        await state.clear()
        await redis.delete(CacheKeys.pipeline_state(user.id))
        await msg.edit_text(
            "Превью не найдено. Начните заново.",
            reply_markup=error_generic_kb().as_markup(),
        )
        return

    # Publish to WordPress
    await msg.edit_text("Статья — Публикация...\n\nПубликую на WordPress...")

    previews_repo = PreviewsRepository(db)
    preview = await previews_repo.get_by_id(preview_id)
    if not preview or preview.status != "draft":
        await state.clear()
        await redis.delete(CacheKeys.pipeline_state(user.id))
        await msg.edit_text(
            "Превью устарело. Сгенерируйте статью заново.",
            reply_markup=error_generic_kb().as_markup(),
        )
        return

    try:
        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        conn = await ConnectionsRepository(db, cm).get_by_id(int(data.get("connection_id", 0)))
        if not conn:
            await state.set_state(ArticlePipelineFSM.preview)
            regen_count = data.get("regeneration_count", 0)
            await msg.edit_text(
                "Подключение не найдено.",
                reply_markup=pipeline_preview_kb(regen_count, has_wp=True).as_markup(),
            )
            return

        # Publish via PreviewService (downloads images from Storage, uploads to WP)
        from services.preview import PreviewService

        preview_svc = PreviewService(ai_orchestrator, db, image_storage, http_client)
        pub_result = await preview_svc.publish_to_wordpress(preview, conn)

        if not pub_result.success:
            msg_err = f"WP publish failed: {pub_result.error}"
            raise RuntimeError(msg_err)

        # Update preview status
        await previews_repo.update(preview_id, ArticlePreviewUpdate(status="published"))

        # Create publication log
        await PublicationsRepository(db).create_log(
            PublicationLogCreate(
                user_id=user.id,
                project_id=data.get("project_id", 0),
                category_id=data.get("category_id"),
                platform_type="wordpress",
                connection_id=data.get("connection_id"),
                keyword=data.get("keyword"),
                content_type="article",
                images_count=preview.images_count or 0,
                post_url=pub_result.post_url or "",
                word_count=preview.word_count or 0,
                tokens_spent=data.get("tokens_charged", 0),
            )
        )

        await state.clear()
        await redis.delete(CacheKeys.pipeline_state(user.id))
        await msg.edit_text(
            "Статья — Опубликовано!\n\n"
            f"Ссылка: {pub_result.post_url}\n"
            f"Списано: {data.get('tokens_charged', 0)} токенов",
            reply_markup=pipeline_post_publish_kb().as_markup(),
        )
        log.info(
            "pipeline_article_published",
            user_id=user.id,
            preview_id=preview_id,
            post_url=pub_result.post_url,
        )

    except Exception:
        log.exception("pipeline_publish_failed", user_id=user.id, preview_id=preview_id)
        await state.set_state(ArticlePipelineFSM.preview)
        regen_count = data.get("regeneration_count", 0)
        await msg.edit_text(
            "Статья — Ошибка публикации\n\nНе удалось опубликовать на WordPress. Попробуйте ещё раз.",
            reply_markup=pipeline_preview_kb(regen_count, has_wp=True).as_markup(),
        )


@router.callback_query(ArticlePipelineFSM.preview, F.data == "pipeline:article:regen")
async def cb_pipeline_regen(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
    image_storage: ImageStorage,
    http_client: httpx.AsyncClient,
) -> None:
    """Regenerate article. 2 free, then paid (FSM_SPEC section 2.2)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    regen_count = data.get("regeneration_count", 0)
    cost = data.get("estimated_cost", 320)
    settings = get_settings()
    is_god = user.id in settings.admin_ids

    if regen_count >= settings.max_regenerations_free and not is_god:
        # E10: paid regeneration after free limit
        token_svc = TokenService(db, settings.admin_ids)
        try:
            await token_svc.charge(
                user_id=user.id,
                amount=cost,
                operation_type="article_regeneration",
                description=f"Pipeline regen #{regen_count + 1}",
            )
        except InsufficientBalanceError:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                f"Перегенерация стоит ~{cost} токенов, у вас {balance}.",
                show_alert=True,
            )
            return
        except Exception:
            log.exception("pipeline_regen_charge_failed", user_id=user.id)
            await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)
            return

    # E07: set state FIRST (FSM filter is the double-click guard)
    await state.set_state(ArticlePipelineFSM.regenerating)
    await callback.answer()
    new_count = regen_count + 1
    await state.update_data(regeneration_count=new_count)

    await msg.edit_text("Статья — Перегенерация...\n\nГенерирую новый вариант...")

    preview_id = data.get("preview_id")
    keyword = data.get("keyword", "")

    # Re-generate via PreviewService
    from services.preview import PreviewService

    preview_svc = PreviewService(ai_orchestrator, db, image_storage, http_client)
    previews_repo = PreviewsRepository(db)

    try:
        article = await preview_svc.generate_article_content(
            user_id=user.id,
            project_id=data.get("project_id", 0),
            category_id=data.get("category_id", 0),
            keyword=keyword,
        )
    except Exception:
        log.exception("pipeline_regen_failed", user_id=user.id, preview_id=preview_id)
        await state.set_state(ArticlePipelineFSM.preview)
        has_wp = not data.get("preview_only", False)
        await msg.edit_text(
            "Перегенерация не удалась.",
            reply_markup=pipeline_preview_kb(new_count, has_wp=has_wp).as_markup(),
        )
        return

    try:
        if preview_id:
            await previews_repo.update(
                preview_id,
                ArticlePreviewUpdate(
                    regeneration_count=new_count,
                    title=article.title,
                    word_count=article.word_count,
                    images_count=article.images_count,
                    content_html=article.content_html,
                    images=article.stored_images,
                ),
            )

        # Re-create Telegraph preview
        telegraph_url: str | None = None
        try:
            from services.external.telegraph import TelegraphClient

            telegraph = TelegraphClient(http_client)
            page = await telegraph.create_page(
                title=article.title,
                html=article.content_html,
            )
            if page:
                telegraph_url = page.url
                if preview_id:
                    await previews_repo.update(
                        preview_id,
                        ArticlePreviewUpdate(
                            telegraph_url=page.url,
                            telegraph_path=page.path,
                        ),
                    )
        except Exception:
            log.exception("pipeline_regen_telegraph_failed", preview_id=preview_id)

        updated_preview = await previews_repo.get_by_id(preview_id) if preview_id else None

    except Exception:
        log.exception("pipeline_regen_update_failed", preview_id=preview_id)
        await state.set_state(ArticlePipelineFSM.preview)
        has_wp = not data.get("preview_only", False)
        await msg.edit_text(
            "Перегенерация не удалась.",
            reply_markup=pipeline_preview_kb(new_count, has_wp=has_wp).as_markup(),
        )
        return

    await state.set_state(ArticlePipelineFSM.preview)
    await state.update_data(telegraph_url=telegraph_url)
    has_wp = not data.get("preview_only", False)

    if updated_preview:
        text = _format_pipeline_preview(updated_preview, cost, telegraph_url)
    else:
        text = (
            "Статья (5/5) — Превью\n\n"
            f"<b>{html.escape(article.title)}</b>\n"
            f"Слов: {article.word_count}, изображений: {article.images_count}\n"
            f"Стоимость: {cost} токенов"
        )
        if telegraph_url:
            text += f"\n\nПревью: {telegraph_url}"

    await msg.edit_text(
        text,
        reply_markup=pipeline_preview_kb(new_count, has_wp=has_wp).as_markup(),
        parse_mode="HTML",
    )
    log.info("pipeline_article_regenerated", user_id=user.id, preview_id=preview_id, regen_count=new_count)


@router.callback_query(
    ArticlePipelineFSM.preview,
    F.data == "pipeline:article:cancel_refund",
)
async def cb_pipeline_cancel_refund(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Cancel and refund tokens at preview stage."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    tokens = data.get("tokens_charged", 0)
    settings = get_settings()
    is_god = user.id in settings.admin_ids

    if tokens > 0 and not is_god:
        token_svc = TokenService(db, settings.admin_ids)
        try:
            await token_svc.refund(user.id, tokens, reason="refund", description="Pipeline cancelled by user")
        except Exception:
            log.exception("pipeline_cancel_refund_failed", user_id=user.id, amount=tokens)

    await state.clear()
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await msg.edit_text(f"Статья отменена. Возвращено {tokens} токенов.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Cancel + Resume handlers
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:article:cancel")
async def cb_pipeline_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
) -> None:
    """Cancel pipeline without refund (before generation)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await state.clear()
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await msg.edit_text("Pipeline отменён.")
    await callback.answer()


@router.callback_query(F.data == "pipeline:resume")
async def cb_pipeline_resume(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Resume pipeline from checkpoint (E49)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    checkpoint_raw = await redis.get(CacheKeys.pipeline_state(user.id))
    if not checkpoint_raw:
        await msg.edit_text(
            "Сохранённый прогресс не найден. Начните заново.",
            reply_markup=error_generic_kb().as_markup(),
        )
        await callback.answer()
        return

    try:
        checkpoint = json.loads(checkpoint_raw)
    except (json.JSONDecodeError, TypeError):
        await msg.edit_text(
            "Сохранённый прогресс повреждён. Начните заново.",
            reply_markup=error_generic_kb().as_markup(),
        )
        await redis.delete(CacheKeys.pipeline_state(user.id))
        await callback.answer()
        return

    # Restore FSM state from checkpoint
    await state.update_data(**checkpoint)

    # Route to confirm step (simplest safe resume point)
    await state.set_state(ArticlePipelineFSM.confirm_cost)
    await _show_confirm(msg, user, db, state)
    await callback.answer()


@router.callback_query(F.data == "pipeline:restart")
async def cb_pipeline_restart(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Restart pipeline (clear checkpoint)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await state.clear()
    await redis.delete(CacheKeys.pipeline_state(user.id))
    # Start fresh pipeline (shared logic, no callback mutation)
    await _start_pipeline_fresh(msg, state, user, db, redis)


@router.callback_query(F.data == "pipeline:cancel")
async def cb_pipeline_cancel_full(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
) -> None:
    """Cancel pipeline completely (from resume dialog)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await state.clear()
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await msg.edit_text("Pipeline отменён.")
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM guards (E07): block callbacks during generation/publishing/regen
# ---------------------------------------------------------------------------


@router.callback_query(ArticlePipelineFSM.generating)
async def cb_pipeline_generating_guard(callback: CallbackQuery) -> None:
    """E07: Block all callbacks while generation is in progress."""
    await callback.answer("Генерация в процессе.", show_alert=True)


@router.callback_query(ArticlePipelineFSM.publishing)
async def cb_pipeline_publishing_guard(callback: CallbackQuery) -> None:
    """E07: Block all callbacks while publishing is in progress."""
    await callback.answer("Публикация в процессе.", show_alert=True)


@router.callback_query(ArticlePipelineFSM.regenerating)
async def cb_pipeline_regen_guard(callback: CallbackQuery) -> None:
    """Block all callbacks while regeneration is in progress."""
    await callback.answer("Перегенерация в процессе.", show_alert=True)


# ---------------------------------------------------------------------------
# Pagination handlers
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.select_project,
    F.data.regexp(r"^page:pipeline_proj:(\d+)$"),
)
async def cb_pipeline_proj_page(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Paginate pipeline project list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    page = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    projects = await ProjectsRepository(db).get_by_user(user.id)
    last_project_id = await _get_last_project_id(db, user.id)
    await msg.edit_text(
        "Статья (1/5) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_project_list_kb(projects, page=page, last_used_id=last_project_id).as_markup(),
    )
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.select_category,
    F.data.regexp(r"^page:pipeline_cat:(\d+)$"),
)
async def cb_pipeline_cat_page(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Paginate pipeline category list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    page = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    data = await state.get_data()
    categories = await CategoriesRepository(db).get_by_project(data["project_id"])
    await msg.edit_text(
        "Статья (3/5) — Тема\n\nКакая тема?",
        reply_markup=pipeline_category_list_kb(categories, page=page).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _pipeline_refund_and_error(
    msg: Message,
    token_svc: TokenService,
    user_id: int,
    amount: int,
    state: FSMContext,
    redis: RedisClient,
    error_text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    """Refund tokens on error and clear FSM + checkpoint."""
    try:
        await token_svc.refund(user_id, amount, reason="refund", description="Pipeline generation failed")
    except Exception:
        log.exception("pipeline_refund_failed_during_error", user_id=user_id, amount=amount)
    await state.clear()
    await redis.delete(CacheKeys.pipeline_state(user_id))
    await msg.edit_text(
        f"Статья — Ошибка\n\n{error_text}\nТокены возвращены.",
        reply_markup=reply_markup,
    )
