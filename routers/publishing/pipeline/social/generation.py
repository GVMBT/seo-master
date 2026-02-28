"""Social Pipeline steps 5-7: confirm, generate, review, publish (F6.3).

Step 5: Confirm cost -- balance check, rate limit, GOD_MODE
Step 6: Generation -- charge, social post via SocialPostService
Step 7: Review -- publish, regenerate, cancel+refund

UX: UX_PIPELINE.md §5 steps 5-7.
FSM: SocialPipelineFSM (28 states, FSM_SPEC.md §2.2).
Edge cases: E01/E07/E10/E25/E38.
Rules: .claude/rules/pipeline.md -- inline handlers, NOT FSM delegation.
"""

from __future__ import annotations

import html
import time
from typing import Any, Literal

import httpx
import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.exceptions import RateLimitError
from bot.helpers import safe_message
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import PublicationLogCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.publications import PublicationsRepository
from keyboards.inline import menu_kb
from keyboards.pipeline import (
    social_confirm_kb,
    social_insufficient_balance_kb,
    social_result_kb,
    social_review_kb,
)
from routers.publishing.pipeline._common import (
    SocialPipelineFSM,
    clear_checkpoint,
    save_checkpoint,
    select_keyword,
    try_refund,
)
from services.ai.orchestrator import AIOrchestrator
from services.ai.rate_limiter import RateLimiter
from services.connections import ConnectionService
from services.publishers.base import PublishRequest, PublishResult
from services.readiness import ReadinessReport
from services.tokens import TokenService, estimate_social_post_cost

log = structlog.get_logger()
router = Router()

# Max free regenerations before charging (E10, matches article pipeline)
MAX_REGENERATIONS_FREE = 2

# Publish lock TTL (E07: double-click prevention)
_PUBLISH_LOCK_TTL = 60

# Progress steps for cumulative social loader
_SOCIAL_STEPS = [
    ("Подбор ключевых фраз", "Фразы подобраны"),
    ("Генерация поста", "Пост сгенерирован"),
]


def _social_progress_text(steps: list[tuple[str, str]], current: int) -> str:
    """Build cumulative progress text for social post generation."""
    lines = ["\U0001f4dd Генерация поста", ""]
    for i, (active_label, done_label) in enumerate(steps):
        if i < current:
            lines.append(f"\u2705 {done_label}")
        elif i == current:
            lines.append(f"\u23f3 {active_label}...")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 5: Cost confirmation
# ---------------------------------------------------------------------------


async def show_social_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    report: ReadinessReport,
    fsm_data: dict[str, Any],
) -> None:
    """Show step 5 confirmation screen (callback context).

    Called from readiness.py when all required items are filled.
    """
    msg = safe_message(callback)
    if not msg:
        return

    text = _build_social_confirm_text(fsm_data, report, user)
    kb = _get_social_confirm_kb(report, user)
    await msg.edit_text(text, reply_markup=kb)
    await state.set_state(SocialPipelineFSM.confirm_cost)
    await save_checkpoint(
        redis,
        user.id,
        current_step="confirm_cost",
        pipeline_type="social",
        project_id=fsm_data.get("project_id"),
        project_name=fsm_data.get("project_name"),
        category_id=fsm_data.get("category_id"),
        connection_id=fsm_data.get("connection_id"),
    )


async def show_social_confirm_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    report: ReadinessReport,
    fsm_data: dict[str, Any],
) -> None:
    """Show step 5 confirmation screen (message context)."""
    text = _build_social_confirm_text(fsm_data, report, user)
    kb = _get_social_confirm_kb(report, user)
    await message.answer(text, reply_markup=kb)
    await state.set_state(SocialPipelineFSM.confirm_cost)
    await save_checkpoint(
        redis,
        user.id,
        current_step="confirm_cost",
        pipeline_type="social",
        project_id=fsm_data.get("project_id"),
        project_name=fsm_data.get("project_name"),
        category_id=fsm_data.get("category_id"),
        connection_id=fsm_data.get("connection_id"),
    )


def _build_social_confirm_text(
    fsm_data: dict[str, Any],
    report: ReadinessReport,
    user: User,
) -> str:
    """Build step 5 confirmation text for social post."""
    project_name = html.escape(str(fsm_data.get("project_name", "")))
    category_name = html.escape(str(fsm_data.get("category_name", "")))
    platform_type = fsm_data.get("platform_type", "")
    identifier = html.escape(str(fsm_data.get("connection_identifier", "")))

    platform_labels = {
        "telegram": "Телеграм",
        "vk": "ВКонтакте",
        "pinterest": "Пинтерест",
    }
    platform_label = platform_labels.get(platform_type, platform_type)

    settings = get_settings()
    is_god = user.id in settings.admin_ids

    cost_line = f"Стоимость: ~{report.estimated_cost} ток."
    if is_god:
        cost_line = f"Стоимость: ~{report.estimated_cost} ток. (GOD_MODE -- бесплатно)"

    return (
        "Пост (5/5) -- Подтверждение\n\n"
        f"{project_name} -> {platform_label} ({identifier})\n"
        f"Тема: {category_name}\n"
        f"Ключевики: {report.keyword_count} фраз\n\n"
        f"{cost_line}\n"
        f"Баланс: {report.user_balance} ток."
    )


def _get_social_confirm_kb(report: ReadinessReport, user: User) -> Any:
    """Return appropriate keyboard for step 5."""
    settings = get_settings()
    is_god = user.id in settings.admin_ids

    if not report.is_sufficient_balance and not is_god:
        return social_insufficient_balance_kb()
    return social_confirm_kb()


# ---------------------------------------------------------------------------
# Step 5 handlers
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.confirm_cost,
    F.data == "pipeline:social:confirm",
)
async def confirm_social_generate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """User confirmed -- charge and start generation (step 5 -> step 6)."""
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
    cost = estimate_social_post_cost()

    # E25: rate limit check BEFORE charge
    rate_limiter = RateLimiter(redis)
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
            operation_type="social_post",
            description=f"Пост (категория #{category_id})",
        )
    await state.update_data(tokens_charged=cost, regen_count=0, last_update_time=time.time())

    await state.set_state(SocialPipelineFSM.generating)
    await msg.edit_text(_social_progress_text(_SOCIAL_STEPS, 0))
    await callback.answer()

    # Run generation
    await _run_social_generation(
        msg,
        state,
        user,
        db,
        redis,
        data,
        ai_orchestrator=ai_orchestrator,
        cost=cost,
    )


@router.callback_query(
    SocialPipelineFSM.confirm_cost,
    F.data == "pipeline:social:back_readiness",
)
async def back_to_readiness_social(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Go back to readiness checklist (step 5 -> step 4)."""
    from routers.publishing.pipeline.social.readiness import show_social_readiness_check

    await show_social_readiness_check(callback, state, user, db, redis, force_show=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# Step 6: Generation
# ---------------------------------------------------------------------------


async def _run_social_generation(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    fsm_data: dict[str, Any],
    *,
    ai_orchestrator: AIOrchestrator,
    cost: int,
) -> None:
    """Core social generation logic -- called from confirm and regenerate."""
    category_id = fsm_data.get("category_id")
    project_id = fsm_data.get("project_id")
    connection_id = fsm_data.get("connection_id")
    platform_type = fsm_data.get("platform_type", "")

    if not category_id or not project_id or not connection_id:
        await message.edit_text("Данные сессии устарели. Начните заново.", reply_markup=menu_kb())
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    # Select keyword for generation
    keyword = await select_keyword(db, category_id)
    if not keyword:
        await try_refund(db, user, cost, "Нет ключевых фраз")
        await message.edit_text(
            "Нет доступных ключевых фраз. Добавьте их в категорию.",
            reply_markup=menu_kb(),
        )
        await state.set_state(SocialPipelineFSM.confirm_cost)
        return

    try:
        # Update progress: step 1 done, step 2 active
        try:
            await message.edit_text(_social_progress_text(_SOCIAL_STEPS, 1))
        except (TelegramBadRequest, TelegramRetryAfter):  # fmt: skip
            log.debug("social_progress_edit_failed")

        from services.ai.social_posts import SocialPostService

        social_service = SocialPostService(ai_orchestrator, db)
        result = await social_service.generate(
            user_id=user.id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            platform=platform_type,
        )

        # Extract text from structured response
        if isinstance(result.content, dict):
            post_text = result.content.get("text", "")
            hashtags = result.content.get("hashtags", [])
        else:
            post_text = str(result.content)
            hashtags = []

        # E38: store in FSM state.data (not DB), acceptable to lose on timeout
        await state.update_data(
            generated_text=post_text,
            generated_hashtags=hashtags,
            generated_keyword=keyword,
            generated_model=result.model_used,
            generated_prompt_version=result.prompt_version,
        )
        await state.set_state(SocialPipelineFSM.review)

        # Build review screen text (show inline, no Telegraph for social posts)
        data = await state.get_data()
        regen_count = data.get("regen_count", 0)
        tokens_charged = data.get("tokens_charged", cost)

        review_text = _build_review_text(post_text, hashtags, keyword, tokens_charged)

        await message.edit_text(
            review_text,
            reply_markup=social_review_kb(regen_count=regen_count, regen_cost=cost),
        )
        await save_checkpoint(
            redis,
            user.id,
            current_step="review",
            pipeline_type="social",
            project_id=project_id,
            project_name=fsm_data.get("project_name"),
            category_id=category_id,
            connection_id=connection_id,
        )

        log.info(
            "pipeline.social.generation_complete",
            user_id=user.id,
            keyword=keyword,
            platform=platform_type,
            tokens=tokens_charged,
        )

    except Exception as exc:
        log.exception("pipeline.social.generation_failed", user_id=user.id, error=str(exc))
        await try_refund(db, user, cost, "Ошибка генерации поста")
        await message.edit_text(
            "Ошибка генерации поста. Токены возвращены.\n\nПопробуйте ещё раз.",
            reply_markup=menu_kb(),
        )
        await state.set_state(SocialPipelineFSM.confirm_cost)


def _build_review_text(
    post_text: str,
    hashtags: list[str],
    keyword: str,
    tokens_charged: int,
) -> str:
    """Build review display text for social post."""
    lines = [
        "Пост готов!\n",
        f"Ключевая фраза: {html.escape(keyword)}",
        f"Списано: {tokens_charged} ток.\n",
        "---",
        html.escape(post_text),
    ]
    if hashtags:
        lines.append("\n" + " ".join(f"#{html.escape(h.lstrip('#'))}" for h in hashtags))
    lines.append("---")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 7: Review handlers
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.review,
    F.data == "pipeline:social:publish",
)
async def publish_social_post(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Publish social post to platform (step 7 -> result)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    connection_id = data.get("connection_id")
    generated_text = data.get("generated_text", "")
    tokens_charged = data.get("tokens_charged", 0)
    keyword = data.get("generated_keyword", "")
    platform_type = data.get("platform_type", "")
    project_id = data.get("project_id")
    category_id = data.get("category_id")

    if not connection_id or not generated_text:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    # E07: Redis NX lock to prevent double-click
    lock_key = f"social_publish:{user.id}:{connection_id}"
    acquired = await redis.set(lock_key, "1", ex=_PUBLISH_LOCK_TTL, nx=True)
    if not acquired:
        await callback.answer("Публикация уже выполняется...", show_alert=True)
        return

    await state.set_state(SocialPipelineFSM.publishing)
    await msg.edit_text("Публикую пост...")

    try:
        # Load connection
        conn_svc = ConnectionService(db, http_client)
        connection = await conn_svc.get_by_id(connection_id)
        if not connection:
            await msg.edit_text(
                "Подключение не найдено. Проверьте настройки.",
                reply_markup=menu_kb(),
            )
            await callback.answer()
            return

        # Ownership check via project (PlatformConnection has no user_id)
        if project_id and connection.project_id != project_id:
            log.warning(
                "pipeline.social.publish_ownership_mismatch",
                user_id=user.id,
                connection_project_id=connection.project_id,
                expected_project_id=project_id,
            )
            await msg.edit_text("Доступ запрещён.", reply_markup=menu_kb())
            await callback.answer()
            return

        # Get publisher for platform
        publisher = _get_publisher(platform_type, http_client)
        content_type = _get_content_type(platform_type)

        try:
            pub_result: PublishResult = await publisher.publish(
                PublishRequest(
                    connection=connection,
                    content=generated_text,
                    content_type=content_type,
                )
            )
        except Exception as exc:
            log.exception("pipeline.social.publish_failed", error=str(exc))
            await msg.edit_text(
                "Ошибка публикации. Попробуйте снова.",
                reply_markup=social_review_kb(
                    regen_count=data.get("regen_count", 0),
                    regen_cost=tokens_charged,
                ),
            )
            await state.set_state(SocialPipelineFSM.review)
            await callback.answer()
            return

        if not pub_result.success:
            await msg.edit_text(
                f"Ошибка публикации: {pub_result.error or 'неизвестная ошибка'}",
                reply_markup=social_review_kb(
                    regen_count=data.get("regen_count", 0),
                    regen_cost=tokens_charged,
                ),
            )
            await state.set_state(SocialPipelineFSM.review)
            await callback.answer()
            return

        # Log publication
        pub_repo = PublicationsRepository(db)
        await pub_repo.create_log(
            PublicationLogCreate(
                user_id=user.id,
                project_id=project_id or 0,
                category_id=category_id,
                platform_type=platform_type,
                connection_id=connection_id,
                keyword=keyword,
                content_type="social_post",
                images_count=0,
                post_url=pub_result.post_url,
                word_count=len(generated_text.split()),
                tokens_spent=tokens_charged,
                ai_model=data.get("generated_model"),
                prompt_version=data.get("generated_prompt_version"),
            )
        )

        # Get cross-post connections (other social platforms for same project)
        crosspost_conns: list[dict[str, Any]] | None = None
        if project_id:
            all_connections = await conn_svc.get_by_project(project_id)
            crosspost_conns = [
                {"id": c.id, "platform": c.platform_type}
                for c in all_connections
                if c.id != connection_id and c.platform_type != "wordpress"
            ]
            if not crosspost_conns:
                crosspost_conns = None

        # Show result
        balance = await TokenService(db=db, admin_ids=get_settings().admin_ids).get_balance(user.id)

        result_text = (
            "Пост опубликован!\n\n"
            f"Ключевая фраза: {html.escape(keyword)}\n"
            f"Списано: {tokens_charged} ток. | Баланс: {balance} ток."
        )
        await msg.edit_text(
            result_text,
            reply_markup=social_result_kb(pub_result.post_url, crosspost_conns),
        )
        await clear_checkpoint(redis, user.id)
        await callback.answer()

        log.info(
            "pipeline.social.published",
            user_id=user.id,
            platform=platform_type,
            post_url=pub_result.post_url,
        )
    finally:
        await redis.delete(lock_key)


@router.callback_query(
    SocialPipelineFSM.review,
    F.data == "pipeline:social:regen",
)
async def regenerate_social(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Regenerate social post (step 7 -> regenerating -> step 7).

    Free for first MAX_REGENERATIONS_FREE (2), then charges tokens (E10).
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    regen_count = int(data.get("regen_count", 0) or 0)
    total_charged = int(data.get("tokens_charged", 0) or 0)
    cost = estimate_social_post_cost()

    settings = get_settings()
    is_god = user.id in settings.admin_ids

    # E25: rate limit check before any generation attempt
    rate_limiter = RateLimiter(redis)
    try:
        await rate_limiter.check(user.id, "text_generation")
    except RateLimitError as exc:
        await callback.answer(exc.user_message, show_alert=True)
        return

    # E10: charge for regeneration after free attempts
    charged_now = 0
    if regen_count >= MAX_REGENERATIONS_FREE and not is_god:
        token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
        has_balance = await token_svc.check_balance(user.id, cost)
        if not has_balance:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                token_svc.format_insufficient_msg(cost, balance),
                show_alert=True,
            )
            return

        # Charge for this regeneration
        await token_svc.charge(
            user_id=user.id,
            amount=cost,
            operation_type="social_post",
            description=f"Перегенерация #{regen_count + 1} (social post)",
        )
        charged_now = cost

    new_regen_count = regen_count + 1
    new_total = total_charged + charged_now
    await state.update_data(
        regen_count=new_regen_count,
        tokens_charged=new_total,
        last_update_time=time.time(),
    )
    await state.set_state(SocialPipelineFSM.regenerating)
    await msg.edit_text(_social_progress_text(_SOCIAL_STEPS, 0))
    await callback.answer()

    log.info(
        "pipeline.social.regenerate_start",
        user_id=user.id,
        regen_count=new_regen_count,
        charged=regen_count >= MAX_REGENERATIONS_FREE,
    )

    # Refresh data with updated regen_count
    data = await state.get_data()

    await _run_social_generation(
        msg,
        state,
        user,
        db,
        redis,
        data,
        ai_orchestrator=ai_orchestrator,
        cost=charged_now,
    )


@router.callback_query(
    SocialPipelineFSM.review,
    F.data == "pipeline:social:cancel_refund",
)
async def cancel_refund_social(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Cancel pipeline and refund tokens (step 7 -> clear)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    tokens_charged = data.get("tokens_charged", 0)

    if tokens_charged and tokens_charged > 0:
        await try_refund(db, user, tokens_charged, "Отмена поста пользователем")

    await state.clear()
    await clear_checkpoint(redis, user.id)
    await msg.edit_text("Пост отменён. Токены возвращены.", reply_markup=menu_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Result handlers
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:social:more")
async def more_posts_social(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Write another post -- jump to category selection step (step 3).

    Keeps project and connection, clears generation-specific data.
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
        generated_text=None,
        generated_hashtags=None,
        generated_keyword=None,
        generated_model=None,
        generated_prompt_version=None,
        tokens_charged=None,
        regen_count=None,
    )

    cats_repo = CategoriesRepository(db)
    categories = await cats_repo.get_by_project(project_id)

    from keyboards.pipeline import pipeline_categories_kb

    if not categories:
        from keyboards.inline import cancel_kb

        await msg.edit_text(
            "Пост (3/5) -- Тема\n\nО чём будет пост? Назовите тему.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        await state.set_state(SocialPipelineFSM.create_category_name)
    elif len(categories) == 1:
        cat = categories[0]
        await state.update_data(category_id=cat.id, category_name=cat.name)
        from routers.publishing.pipeline.social.readiness import show_social_readiness_check

        await show_social_readiness_check(callback, state, user, db, redis)
    else:
        await msg.edit_text(
            "Пост (3/5) -- Тема\n\nКакая тема?",
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
        connection_id=data.get("connection_id"),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_publisher(platform_type: str, http_client: httpx.AsyncClient) -> Any:
    """Get publisher instance for platform type."""
    from services.publishers.pinterest import PinterestPublisher
    from services.publishers.telegram import TelegramPublisher
    from services.publishers.vk import VKPublisher

    publishers = {
        "telegram": lambda: TelegramPublisher(http_client),
        "vk": lambda: VKPublisher(http_client),
        "pinterest": lambda: PinterestPublisher(http_client=http_client),
    }
    factory = publishers.get(platform_type)
    if not factory:
        msg = f"Unknown social platform: {platform_type}"
        raise ValueError(msg)
    return factory()


def _get_content_type(platform_type: str) -> Literal["html", "telegram_html", "plain_text", "pin_text"]:
    """Map platform type to content type for PublishRequest."""
    content_types: dict[str, Literal["html", "telegram_html", "plain_text", "pin_text"]] = {
        "telegram": "telegram_html",
        "vk": "plain_text",
        "pinterest": "pin_text",
    }
    return content_types.get(platform_type, "plain_text")
