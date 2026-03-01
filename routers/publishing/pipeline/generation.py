"""Article Pipeline steps 5-8: confirmation, generation, preview, publish (F5.4).

Step 5: Confirm cost — balance check, rate limit, GOD_MODE
Step 6: Generation — charge, progress messages, PreviewService
Step 7: Preview — publish, regenerate, cancel+refund, copy HTML
Step 8: Result — WP publish, more articles, dashboard

UX: UX_PIPELINE.md §4.1 steps 5-8, §11.3/§11.8, §12.2.
FSM: FSM_SPEC.md §2.1-2.2 (ArticlePipelineFSM).
Edge cases: E01/E05/E07/E10/E18/E25/E34/E35/E43-E48.
Rules: .claude/rules/pipeline.md — inline handlers, NOT FSM delegation.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from typing import Any

import httpx
import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.config import get_settings
from bot.exceptions import RateLimitError
from bot.helpers import safe_message
from bot.service_factory import ProjectServiceFactory
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import ArticlePreviewCreate, ArticlePreviewUpdate, PublicationLogCreate, User
from db.repositories.previews import PreviewsRepository
from db.repositories.publications import PublicationsRepository
from keyboards.inline import menu_kb
from keyboards.pipeline import (
    pipeline_confirm_kb,
    pipeline_generation_error_kb,
    pipeline_insufficient_balance_kb,
    pipeline_preview_kb,
    pipeline_preview_no_wp_kb,
    pipeline_result_kb,
)
from routers.publishing.pipeline._common import (
    ArticlePipelineFSM,
    clear_checkpoint,
    save_checkpoint,
    select_keyword,
    try_refund,
)
from services.ai.rate_limiter import RateLimiter
from services.connections import ConnectionService
from services.external.telegraph import TelegraphClient
from services.preview import ArticleContent, PreviewService
from services.tokens import (
    COST_PER_IMAGE,
    TokenService,
    estimate_article_cost,
)

log = structlog.get_logger()
router = Router()

# Max free regenerations before charging (G2, E10)
MAX_REGENERATIONS_FREE = 2

# Publish lock TTL (E07: double-click prevention)
_PUBLISH_LOCK_TTL = 60

# Progress steps for cumulative loader (UX_PIPELINE.md §11.3)
_ARTICLE_STEPS = [
    ("Сбор данных из Google", "Данные собраны"),
    ("Анализ конкурентов", "Конкуренты проанализированы"),
    ("Генерация текста и изображений", "Текст и изображения готовы"),
    ("Подготовка предпросмотра", "Предпросмотр готов"),
]

# Delays before each step's progress message appears (seconds)
_ARTICLE_STEP_DELAYS = [0, 5, 15, 50]


def _progress_text(title: str, steps: list[tuple[str, str]], current: int) -> str:
    """Build cumulative progress text with checkmarks for completed steps."""
    lines = [title, ""]
    for i, (active_label, done_label) in enumerate(steps):
        if i < current:
            lines.append(f"\u2705 {done_label}")
        elif i == current:
            lines.append(f"\u23f3 {active_label}...")
        # Future steps are not shown
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 5: Cost confirmation
# ---------------------------------------------------------------------------


async def show_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
    report: Any,
    fsm_data: dict[str, Any],
) -> None:
    """Show step 5 confirmation screen (callback context).

    Called from readiness.py when all required items are filled.
    """
    msg = safe_message(callback)
    if not msg:
        return

    text = _build_confirm_text(fsm_data, report, user)
    kb = _get_confirm_kb(report, user)
    await msg.edit_text(text, reply_markup=kb)
    await state.set_state(ArticlePipelineFSM.confirm_cost)
    await save_checkpoint(
        redis,
        user.id,
        current_step="confirm_cost",
        project_id=fsm_data.get("project_id"),
        project_name=fsm_data.get("project_name"),
        category_id=fsm_data.get("category_id"),
        connection_id=fsm_data.get("connection_id"),
    )


async def show_confirm_msg(
    message: Message,
    state: FSMContext,
    user: User,
    redis: RedisClient,
    report: Any,
    fsm_data: dict[str, Any],
) -> None:
    """Show step 5 confirmation screen (message context)."""
    text = _build_confirm_text(fsm_data, report, user)
    kb = _get_confirm_kb(report, user)
    await message.answer(text, reply_markup=kb)
    await state.set_state(ArticlePipelineFSM.confirm_cost)
    await save_checkpoint(
        redis,
        user.id,
        current_step="confirm_cost",
        project_id=fsm_data.get("project_id"),
        project_name=fsm_data.get("project_name"),
        category_id=fsm_data.get("category_id"),
        connection_id=fsm_data.get("connection_id"),
    )


def _build_confirm_text(fsm_data: dict[str, Any], report: Any, user: User) -> str:
    """Build step 5 confirmation text."""
    project_name = html.escape(str(fsm_data.get("project_name", "")))
    category_name = html.escape(str(fsm_data.get("category_name", "")))
    wp_id = fsm_data.get("wp_identifier", "")
    preview_only = fsm_data.get("preview_only", False)

    settings = get_settings()
    is_god = user.id in settings.admin_ids

    wp_display = html.escape(str(wp_id)) if wp_id else ("только превью" if preview_only else "")
    cost_line = f"Стоимость: ~{report.estimated_cost} ток."
    if is_god:
        cost_line = f"Стоимость: ~{report.estimated_cost} ток. (GOD_MODE — бесплатно)"

    return (
        "Статья (5/5) — Подтверждение\n\n"
        f"{project_name}"
        f"{' → ' + wp_display if wp_display else ''}\n"
        f"Тема: {category_name}\n"
        f"Ключевики: {report.keyword_count} фраз | Изображения: {report.image_count} шт.\n\n"
        f"{cost_line}\n"
        f"Баланс: {report.user_balance} ток."
    )


def _get_confirm_kb(report: Any, user: User) -> Any:
    """Return appropriate keyboard for step 5."""
    settings = get_settings()
    is_god = user.id in settings.admin_ids

    if not report.is_sufficient_balance and not is_god:
        return pipeline_insufficient_balance_kb()
    return pipeline_confirm_kb()


# ---------------------------------------------------------------------------
# Step 5 handlers
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.confirm_cost,
    F.data == "pipeline:article:confirm",
)
async def confirm_generate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
    image_storage: Any,
    serper_client: Any = None,
    firecrawl_client: Any = None,
) -> None:
    """User confirmed — charge and start generation (step 5 → step 6)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    if not category_id or not project_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    settings = get_settings()

    # C25: re-read image_count from category on retry (user may have changed settings
    # between error and retry via another FSM or Toolbox)
    fresh_image_count = await _fresh_image_count(db, category_id)
    image_count = fresh_image_count if fresh_image_count is not None else data.get("image_count", 4)

    old_cost = data.get("_last_estimated_cost")
    cost = estimate_article_cost(images_count=image_count)

    # C25: update FSM data with fresh image_count if changed
    if image_count != data.get("image_count"):
        await state.update_data(image_count=image_count)
        data["image_count"] = image_count
        log.info(
            "pipeline.retry_image_count_refreshed",
            user_id=user.id,
            old=data.get("image_count"),
            new=image_count,
        )

    # C25: notify user if cost changed since last estimate
    if old_cost is not None and cost != old_cost:
        log.info(
            "pipeline.retry_cost_changed",
            user_id=user.id,
            old_cost=old_cost,
            new_cost=cost,
        )

    await state.update_data(_last_estimated_cost=cost)

    # H15: per-user generation rate limit (3 per 10 min) BEFORE charge
    rate_limiter = RateLimiter(redis)
    try:
        await rate_limiter.check(user.id, "pipeline_generation")
    except RateLimitError as exc:
        await callback.answer(
            f"Слишком частые генерации. Подождите {(exc.retry_after_seconds + 59) // 60} мин.",
            show_alert=True,
        )
        return

    # E25: rate limit check BEFORE charge
    try:
        await rate_limiter.check(user.id, "text_generation")
    except RateLimitError as exc:
        await callback.answer(exc.user_message, show_alert=True)
        return

    # E01: balance check
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    is_god = user.id in settings.admin_ids

    if not is_god:
        has_balance = await token_svc.check_balance(user.id, cost)
        if not has_balance:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                token_svc.format_insufficient_msg(cost, balance),
                show_alert=True,
            )
            return

    # Charge tokens BEFORE generation
    if not is_god:
        await token_svc.charge(
            user_id=user.id,
            amount=cost,
            operation_type="article",
            description=f"Статья (категория #{category_id})",
        )
    await state.update_data(tokens_charged=cost, last_update_time=time.time())
    # Sync local dict so _run_generation sees charged amount (same as regenerate path)
    data["tokens_charged"] = cost

    await state.set_state(ArticlePipelineFSM.generating)
    await callback.answer()

    # Run generation as background process
    await _run_generation(
        msg,
        state,
        user,
        db,
        redis,
        http_client,
        data,
        ai_orchestrator=ai_orchestrator,
        image_storage=image_storage,
        serper_client=serper_client,
        firecrawl_client=firecrawl_client,
    )


@router.callback_query(
    ArticlePipelineFSM.confirm_cost,
    F.data == "pipeline:article:back_readiness",
)
async def back_to_readiness(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Go back to readiness checklist (step 5 → step 4)."""
    from routers.publishing.pipeline.readiness import show_readiness_check

    await show_readiness_check(callback, state, user, db, redis, force_show=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 6: Generation
# ---------------------------------------------------------------------------


async def _progress_task(
    message: Message,
    done_event: asyncio.Event,
) -> None:
    """Send cumulative progress messages while generation runs (G7: cancel on fast gen)."""
    title = "\U0001f4dd Генерация статьи"
    for step_idx, delay in enumerate(_ARTICLE_STEP_DELAYS):
        if done_event.is_set():
            return
        if delay > 0:
            try:
                await asyncio.wait_for(done_event.wait(), timeout=delay)
                return  # Generation completed during wait
            except TimeoutError:
                pass
        if done_event.is_set():
            return
        try:
            await message.edit_text(_progress_text(title, _ARTICLE_STEPS, step_idx))
        except (TelegramBadRequest, TelegramRetryAfter):  # fmt: skip
            log.debug("progress_msg_edit_failed")


async def _run_generation(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    fsm_data: dict[str, Any],
    *,
    ai_orchestrator: Any,
    image_storage: Any,
    serper_client: Any = None,
    firecrawl_client: Any = None,
) -> None:
    """Core generation logic — called from confirm and regenerate."""
    category_id = fsm_data.get("category_id")
    project_id = fsm_data.get("project_id")
    image_count = fsm_data.get("image_count", 4)
    tokens_charged = fsm_data.get("tokens_charged") or 0
    connection_id = fsm_data.get("connection_id")
    preview_only = fsm_data.get("preview_only", False)

    if not category_id or not project_id:
        await message.edit_text("Данные сессии устарели. Начните заново.", reply_markup=menu_kb())
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    # Select keyword for generation
    keyword = await select_keyword(db, category_id)
    if not keyword:
        await try_refund(db, user, tokens_charged, "Нет ключевых фраз")
        await message.edit_text(
            "Нет доступных ключевых фраз. Добавьте их в категорию.",
            reply_markup=pipeline_generation_error_kb(),
        )
        await state.set_state(ArticlePipelineFSM.confirm_cost)
        return

    # Register active generation for shutdown refund guard
    gen_key = CacheKeys.active_generation(user.id)
    await redis.set(
        gen_key,
        json.dumps({"tokens": tokens_charged, "ts": int(time.time())}),
        ex=600,  # auto-expire after 10 min (safety net)
    )

    # Start progress messages (G7)
    done_event = asyncio.Event()
    progress = asyncio.create_task(_progress_task(message, done_event))

    try:
        # Build PreviewService from injected deps (DI via dp.workflow_data)
        preview_svc = PreviewService(
            ai_orchestrator=ai_orchestrator,
            db=db,
            image_storage=image_storage,
            http_client=http_client,
            serper_client=serper_client,
            firecrawl_client=firecrawl_client,
        )

        content: ArticleContent = await preview_svc.generate_article_content(
            user_id=user.id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            image_count=image_count,
        )
    except Exception as exc:
        # E35: text generation failed — full refund
        done_event.set()
        progress.cancel()
        log.exception("pipeline.generation_failed", user_id=user.id, error=str(exc))
        await try_refund(db, user, tokens_charged, "Ошибка генерации")
        await message.edit_text(
            "Ошибка генерации. Токены возвращены.\n\nПопробуйте ещё раз.",
            reply_markup=pipeline_generation_error_kb(),
        )
        await state.set_state(ArticlePipelineFSM.confirm_cost)
        return
    finally:
        done_event.set()
        if not progress.done():
            progress.cancel()
        # Unregister active generation guard
        await redis.delete(gen_key)

    # E34: partial/zero images — refund for missing images (including all-fail case)
    actual_images = content.images_count
    if actual_images < image_count:
        missing = image_count - actual_images
        partial_refund = missing * COST_PER_IMAGE
        if partial_refund > 0:
            settings = get_settings()
            token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
            is_god = user.id in settings.admin_ids
            if not is_god:
                await token_svc.refund(
                    user_id=user.id,
                    amount=partial_refund,
                    reason="refund",
                    description=f"Частичный возврат: {missing} изобр. не удалось",
                )
            tokens_charged -= partial_refund

    # Create Telegraph page (E05: graceful degradation)
    telegraph = TelegraphClient(http_client)
    telegraph_author = str(fsm_data.get("company_name") or fsm_data.get("project_name") or "")
    telegraph_page = await telegraph.create_page(
        title=content.title,
        html=content.content_html,
        author=telegraph_author or "SEO Master Bot",
    )
    telegraph_url = telegraph_page.url if telegraph_page else None
    telegraph_path = telegraph_page.path if telegraph_page else None

    # Expire previous preview to prevent orphaned draft refund (M3 fix)
    # Best-effort: don't break generation if expiration fails
    previews_repo = PreviewsRepository(db)
    old_preview_id = fsm_data.get("preview_id")
    if old_preview_id:
        try:
            await previews_repo.mark_expired(old_preview_id)
        except Exception:
            log.warning(
                "pipeline.expire_old_preview_failed",
                old_preview_id=old_preview_id,
                user_id=user.id,
            )

    # Save preview to DB
    preview = await previews_repo.create(
        ArticlePreviewCreate(
            user_id=user.id,
            project_id=project_id,
            category_id=category_id,
            connection_id=connection_id,
            telegraph_url=telegraph_url,
            telegraph_path=telegraph_path,
            title=content.title,
            keyword=keyword,
            meta_description=content.meta_description,
            word_count=content.word_count,
            images_count=actual_images,
            tokens_charged=tokens_charged,
            content_html=content.content_html,
            images=content.stored_images,
        )
    )

    await state.update_data(preview_id=preview.id, keyword=keyword)
    await state.set_state(ArticlePipelineFSM.preview)

    # Build preview text
    preview_text = _build_preview_text(content, keyword, tokens_charged, telegraph_url)

    # Choose keyboard variant
    can_publish = bool(connection_id) and not preview_only
    if can_publish:
        kb = pipeline_preview_kb(
            telegraph_url,
            can_publish=True,
            regen_count=preview.regeneration_count,
            regen_cost=tokens_charged,
        )
    else:
        kb = pipeline_preview_no_wp_kb(
            telegraph_url,
            regen_count=preview.regeneration_count,
            regen_cost=tokens_charged,
        )

    await message.edit_text(preview_text, reply_markup=kb)
    await save_checkpoint(
        redis,
        user.id,
        current_step="preview",
        project_id=project_id,
        project_name=fsm_data.get("project_name"),
        category_id=category_id,
        connection_id=connection_id,
        preview_id=preview.id,
    )

    log.info(
        "pipeline.generation_complete",
        user_id=user.id,
        preview_id=preview.id,
        word_count=content.word_count,
        images=actual_images,
        tokens=tokens_charged,
    )


def _build_preview_text(
    content: ArticleContent,
    keyword: str,
    tokens_charged: int,
    telegraph_url: str | None,
) -> str:
    """Build preview display text."""
    lines = [
        "Статья готова!\n",
        f"<b>{html.escape(content.title)}</b>\n",
        f"Ключевая фраза: {html.escape(keyword)}",
        f"Объём: ~{content.word_count} слов | Изображения: {content.images_count}",
        f"Списано: {tokens_charged} ток.",
    ]
    if not telegraph_url:
        # E05: Telegraph down — show inline snippet (strip HTML tags, Telegram rejects <h1> etc.)
        raw = re.sub(r"<[^>]+>", "", content.content_html or "")
        snippet = html.escape(raw[:500])
        lines.append(f"\n<i>(Превью недоступно, фрагмент ниже)</i>\n{snippet}...")
    return "\n".join(lines)


async def _fresh_image_count(db: SupabaseClient, category_id: int) -> int | None:
    """Re-read image_count from category settings (C25: stale cost prevention).

    Returns None if category not found or no image settings.
    """
    from services.categories import CategoryService

    cat_svc = CategoryService(db=db)
    category = await cat_svc.get_category_raw(category_id)
    if not category:
        return None
    image_settings = category.image_settings or {}
    count = image_settings.get("count")
    if count is not None:
        try:
            return int(count)
        except ValueError, TypeError:
            return None
    return None


# ---------------------------------------------------------------------------
# Step 7: Preview handlers
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.preview,
    F.data == "pipeline:article:publish",
)
async def publish_article(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
    image_storage: Any,
) -> None:
    """Publish article to WordPress (step 7 → step 8)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    preview_id = data.get("preview_id")
    connection_id = data.get("connection_id")

    if not preview_id or not connection_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    # E07: Redis NX lock to prevent double-click
    lock_key = f"publish:{preview_id}"
    acquired = await redis.set(lock_key, "1", ex=_PUBLISH_LOCK_TTL, nx=True)
    if not acquired:
        await callback.answer("Публикация уже выполняется...", show_alert=True)
        return

    # E18 + P0-3: CAS — atomic mark published (prevents race with cleanup)
    previews_repo = PreviewsRepository(db)
    preview = await previews_repo.atomic_mark_published(preview_id)
    if not preview:
        await redis.delete(lock_key)
        await callback.answer("Превью устарело или уже опубликовано.", show_alert=True)
        return

    # Ownership check (defense-in-depth: preview_id from FSM state, not callback_data)
    if preview.user_id != user.id:
        log.warning("pipeline.publish_ownership_mismatch", user_id=user.id, preview_user_id=preview.user_id)
        await previews_repo.update(preview_id, ArticlePreviewUpdate(status="draft"))
        await redis.delete(lock_key)
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    await state.update_data(last_update_time=time.time())
    await state.set_state(ArticlePipelineFSM.publishing)
    await msg.edit_text("Публикую на WordPress...")

    try:
        # Load WP connection
        conn_svc = ConnectionService(db, http_client)
        connection = await conn_svc.get_by_id(connection_id)
        if not connection:
            await msg.edit_text(
                "WordPress-подключение не найдено. Проверьте настройки.",
                reply_markup=menu_kb(),
            )
            await callback.answer()
            return

        try:
            preview_svc = PreviewService(
                ai_orchestrator=ai_orchestrator,
                db=db,
                image_storage=image_storage,
                http_client=http_client,
            )
            result = await preview_svc.publish_to_wordpress(preview, connection)
        except Exception as exc:
            log.exception("pipeline.publish_failed", preview_id=preview_id, error=str(exc))
            # Revert to draft on failure
            await previews_repo.update(preview_id, ArticlePreviewUpdate(status="draft"))
            await msg.edit_text(
                "Ошибка публикации на WordPress. Попробуйте снова.",
                reply_markup=pipeline_preview_kb(
                    preview.telegraph_url,
                    can_publish=True,
                    regen_count=preview.regeneration_count,
                    regen_cost=preview.tokens_charged or 0,
                ),
            )
            await state.set_state(ArticlePipelineFSM.preview)
            await callback.answer()
            return

        # Log publication
        pub_repo = PublicationsRepository(db)
        await pub_repo.create_log(
            PublicationLogCreate(
                user_id=user.id,
                project_id=preview.project_id,
                category_id=preview.category_id,
                platform_type="wordpress",
                connection_id=connection_id,
                keyword=preview.keyword,
                content_type="article",
                images_count=preview.images_count or 0,
                post_url=result.post_url,
                word_count=preview.word_count or 0,
                tokens_spent=preview.tokens_charged or 0,
            )
        )

        # Show result (step 8)
        await state.set_state(ArticlePipelineFSM.result)
        balance = await TokenService(db=db, admin_ids=get_settings().admin_ids).get_balance(user.id)

        result_text = (
            "Статья опубликована!\n\n"
            f"<b>{html.escape(preview.title or '')}</b>\n"
            f"Списано: {preview.tokens_charged or 0} ток. | Баланс: {balance} ток."
        )
        await msg.edit_text(
            result_text,
            reply_markup=pipeline_result_kb(result.post_url),
        )
        await clear_checkpoint(redis, user.id)
        await callback.answer()

        log.info(
            "pipeline.article_published",
            user_id=user.id,
            preview_id=preview_id,
            post_url=result.post_url,
        )
    finally:
        await redis.delete(lock_key)


@router.callback_query(
    ArticlePipelineFSM.preview,
    F.data == "pipeline:article:regenerate",
)
async def regenerate_article(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
    image_storage: Any,
    serper_client: Any = None,
    firecrawl_client: Any = None,
) -> None:
    """Regenerate article content (step 7 → regenerating → step 7).

    Free for first MAX_REGENERATIONS_FREE (2), then charges tokens (E10).
    Uses tokens_charged from first generation as fixed cost (P1-12).
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    preview_id = data.get("preview_id")
    if not preview_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    previews_repo = PreviewsRepository(db)
    preview = await previews_repo.get_by_id(preview_id)
    if not preview or preview.status != "draft":
        await callback.answer("Превью устарело.", show_alert=True)
        return
    if preview.user_id != user.id:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    regen_count = preview.regeneration_count
    settings = get_settings()
    is_god = user.id in settings.admin_ids

    # E10: charge for regeneration after free attempts
    tokens_charged = preview.tokens_charged or 0
    if regen_count >= MAX_REGENERATIONS_FREE and not is_god:
        token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
        has_balance = await token_svc.check_balance(user.id, tokens_charged)
        if not has_balance:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                token_svc.format_insufficient_msg(tokens_charged, balance),
                show_alert=True,
            )
            return

        # Charge for this regeneration
        await token_svc.charge(
            user_id=user.id,
            amount=tokens_charged,
            operation_type="article",
            description=f"Перегенерация #{regen_count + 1} (превью #{preview_id})",
        )

    # Increment regen counter in DB (G2: persistent in PostgreSQL)
    try:
        new_count = await previews_repo.increment_regeneration(preview_id)
    except Exception:
        log.exception("pipeline.increment_regen_failed", preview_id=preview_id)
        # Refund if charge happened
        if regen_count >= MAX_REGENERATIONS_FREE and not is_god:
            await try_refund(db, user, tokens_charged, "increment_regen_failed")
        await callback.answer("Ошибка обновления счётчика. Попробуйте снова.", show_alert=True)
        return

    # For free regenerations: set tokens_charged=0 so try_refund won't refund
    # tokens that were never charged. For paid regens, tokens_charged is the actual
    # amount charged above (C2 fix: prevent free regen refund leak).
    actually_charged = tokens_charged if (regen_count >= MAX_REGENERATIONS_FREE and not is_god) else 0

    # Update state for regeneration
    await state.update_data(
        tokens_charged=actually_charged,
        last_update_time=time.time(),
    )
    await state.set_state(ArticlePipelineFSM.regenerating)
    await callback.answer()

    log.info(
        "pipeline.regenerate_start",
        user_id=user.id,
        preview_id=preview_id,
        regen_count=new_count,
        charged=regen_count >= MAX_REGENERATIONS_FREE,
    )

    # Sync data dict with updated state (avoid stale tokens_charged in refund path)
    data["tokens_charged"] = actually_charged

    # Run generation with same data
    await _run_generation(
        msg,
        state,
        user,
        db,
        redis,
        http_client,
        data,
        ai_orchestrator=ai_orchestrator,
        image_storage=image_storage,
        serper_client=serper_client,
        firecrawl_client=firecrawl_client,
    )


@router.callback_query(
    ArticlePipelineFSM.preview,
    F.data == "pipeline:article:cancel_refund",
)
async def cancel_refund(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    image_storage: Any,
) -> None:
    """Cancel pipeline and refund tokens (step 7 → clear).

    CR-77a: Redis NX lock prevents double-refund on rapid double-click.
    C14: cleanup Telegraph page + Storage images BEFORE refund to prevent
    users from copying the preview URL, cancelling, and repeating for free content.
    Cleanup errors must NOT block the refund — refund is more important.
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    preview_id = data.get("preview_id")

    if preview_id:
        # CR-77a: Redis NX lock to prevent double-refund race condition
        lock_key = f"cancel_refund:{preview_id}"
        acquired = await redis.set(lock_key, "1", ex=60, nx=True)
        if not acquired:
            await callback.answer("Отмена уже выполняется...", show_alert=True)
            return

        try:
            await _do_cancel_refund(
                callback,
                db,
                redis,
                http_client,
                image_storage,
                user,
                preview_id,
            )
        finally:
            await redis.delete(lock_key)
    else:
        # No preview_id -- just clear state
        pass

    await state.clear()
    await clear_checkpoint(redis, user.id)
    await msg.edit_text("Статья отменена. Токены возвращены.", reply_markup=menu_kb())
    await callback.answer()


async def _do_cancel_refund(
    callback: CallbackQuery,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    image_storage: Any,
    user: User,
    preview_id: int,
) -> None:
    """Execute the cancel+refund logic (extracted for CR-77a lock wrapper)."""
    previews_repo = PreviewsRepository(db)
    preview = await previews_repo.get_by_id(preview_id)
    if not preview or preview.status != "draft" or preview.user_id != user.id:
        return

    # C14: cleanup Telegraph page before refund (best-effort)
    if preview.telegraph_path:
        try:
            telegraph = TelegraphClient(http_client)
            await telegraph.delete_page(preview.telegraph_path)
        except Exception:
            log.warning(
                "pipeline.cancel_telegraph_cleanup_failed",
                preview_id=preview_id,
                telegraph_path=preview.telegraph_path,
            )

    # C14: cleanup Storage images before refund (best-effort)
    if preview.images:
        try:
            paths = [
                img.get("storage_path") for img in preview.images if isinstance(img, dict) and img.get("storage_path")
            ]
            if paths:
                await image_storage.cleanup_by_paths(paths)
        except Exception:
            log.warning(
                "pipeline.cancel_storage_cleanup_failed",
                preview_id=preview_id,
                images_count=len(preview.images),
            )

    # Mark as cancelled
    await previews_repo.update(preview_id, ArticlePreviewUpdate(status="cancelled"))
    # Refund tokens
    if preview.tokens_charged and preview.tokens_charged > 0:
        await try_refund(db, user, preview.tokens_charged, "Отмена пользователем")


@router.callback_query(
    ArticlePipelineFSM.preview,
    F.data == "pipeline:article:copy_html",
)
async def copy_html(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Send article HTML as a downloadable .html file."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    preview_id = data.get("preview_id")
    if not preview_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    previews_repo = PreviewsRepository(db)
    preview = await previews_repo.get_by_id(preview_id)
    if not preview or not preview.content_html:
        await callback.answer("Контент недоступен.", show_alert=True)
        return

    if preview.user_id != user.id:
        await callback.answer("Доступ запрещён.", show_alert=True)
        return

    # Send as .html document (sanitize filename: keep only alnum, dash, underscore)
    html_bytes = preview.content_html.encode("utf-8")
    safe_name = re.sub(r"[^\w\-]", "_", preview.keyword or "article")[:40].strip("_") or "article"
    filename = f"{safe_name}.html"
    doc = BufferedInputFile(html_bytes, filename=filename)
    await msg.answer_document(doc, caption="HTML-код статьи")
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.preview,
    F.data == "pipeline:article:connect_wp_publish",
)
async def connect_wp_publish(
    callback: CallbackQuery,
    state: FSMContext,
    db: SupabaseClient,
    user: User,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start WP connection sub-flow from preview (Variant B, G1).

    Reuses existing WP connection states from article.py.
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.update_data(from_preview=True)

    # If project already has website_url, skip URL step
    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id:
        proj_svc = project_service_factory(db)
        project = await proj_svc.get_owned_project(project_id, user.id)
        if project and project.website_url:
            await state.update_data(wp_url=project.website_url)
            await state.set_state(ArticlePipelineFSM.connect_wp_login)
            await msg.edit_text(
                f"Подключение WordPress\n\n"
                f"Сайт: {html.escape(project.website_url)}\n\n"
                f"Введите логин WordPress (имя пользователя).",
            )
            await callback.answer()
            return

    await state.set_state(ArticlePipelineFSM.connect_wp_url)
    await msg.edit_text(
        "Подключение WordPress\n\nВведите адрес вашего сайта.\n<i>Пример: example.com</i>",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 8: Result handlers
# ---------------------------------------------------------------------------


async def _jump_to_category_selection(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Jump to step 3 (category selection), clearing generation data.

    Shared by more_articles and change_topic handlers.
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")

    if not project_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    # Clear generation-specific data, keep project + connection
    await state.update_data(
        category_id=None,
        category_name=None,
        preview_id=None,
        keyword=None,
        tokens_charged=None,
    )

    from services.categories import CategoryService

    cat_svc = CategoryService(db=db)
    categories = await cat_svc.list_by_project(project_id, user.id) or []

    from keyboards.pipeline import pipeline_categories_kb

    if not categories:
        from keyboards.inline import cancel_kb

        await msg.edit_text(
            "Статья (3/5) — Тема\n\nО чём будет статья? Назовите тему.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        await state.set_state(ArticlePipelineFSM.create_category_name)
    elif len(categories) == 1:
        cat = categories[0]
        await state.update_data(category_id=cat.id, category_name=cat.name)
        from routers.publishing.pipeline.readiness import show_readiness_check

        await show_readiness_check(callback, state, user, db, redis)
    else:
        await msg.edit_text(
            "Статья (3/5) — Тема\n\nКакая тема?",
            reply_markup=pipeline_categories_kb(categories, project_id),
        )
        await state.set_state(ArticlePipelineFSM.select_category)

    await save_checkpoint(
        redis,
        user.id,
        current_step="select_category",
        project_id=project_id,
        project_name=project_name,
        connection_id=data.get("connection_id"),
    )
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.result,
    F.data == "pipeline:article:more",
)
async def more_articles(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Write another article — jump to step 3 (category), keeping project+WP (G5)."""
    await _jump_to_category_selection(callback, state, user, db, redis)


@router.callback_query(F.data == "pipeline:article:change_topic")
async def change_topic(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Change topic after error — jump to step 3 (category), keeping project+WP.

    Stateless filter: error can leave FSM in various states (confirm_cost etc.).
    """
    await _jump_to_category_selection(callback, state, user, db, redis)
