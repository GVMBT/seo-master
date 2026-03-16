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

import base64 as b64mod
import contextlib
import html
import time
from typing import Any, Literal

import httpx
import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message

from bot.config import get_settings
from bot.custom_emoji import EMOJI_DONE, EMOJI_PROGRESS
from bot.exceptions import RateLimitError
from bot.helpers import safe_edit_text, safe_message
from bot.texts.emoji import Emoji
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import PublicationLogCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
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
from services.ai.images import ImageService
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

# Platform display names (Russian)
_PLATFORM_NAMES: dict[str, str] = {
    "telegram": "Telegram",
    "vk": "ВКонтакте",
    "pinterest": "Pinterest",
}

# Publish progress steps (platform name inserted at runtime)
_SOCIAL_PUBLISH_STEPS = [
    ("Подготовка контента", "Контент подготовлен"),
    ("Публикация в {platform}", "Опубликовано в {platform}"),
    ("Сохранение результата", "Результат сохранён"),
]

# Progress steps for cumulative social loader
_SOCIAL_STEPS = [
    ("Подбор ключевых фраз", "Фразы подобраны"),
    ("Генерация поста", "Пост сгенерирован"),
    ("Генерация изображения", "Изображение готово"),
]


def _social_progress_text(steps: list[tuple[str, str]], current: int) -> str:
    """Build cumulative progress text for social post generation."""
    lines = [f"{Emoji.EDIT_DOC} Генерация поста", ""]
    for i, (active_label, done_label) in enumerate(steps):
        if i < current:
            lines.append(f"{EMOJI_DONE} {done_label}")
        elif i == current:
            lines.append(f"{EMOJI_PROGRESS} {active_label}...")
    return "\n".join(lines)


def _social_publish_progress(platform: str, current: int) -> str:
    """Build cumulative progress text for social post publishing."""
    name = _PLATFORM_NAMES.get(platform, platform.title())
    lines = [f"{Emoji.UPLOAD} Публикация поста", ""]
    for i, (active_tpl, done_tpl) in enumerate(_SOCIAL_PUBLISH_STEPS):
        active_label = active_tpl.format(platform=name)
        done_label = done_tpl.format(platform=name)
        if i < current:
            lines.append(f"{EMOJI_DONE} {done_label}")
        elif i == current:
            lines.append(f"{EMOJI_PROGRESS} {active_label}...")
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
    await safe_edit_text(msg, text, reply_markup=kb)
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
    await safe_edit_text(msg, _social_progress_text(_SOCIAL_STEPS, 0))
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
        await safe_edit_text(message, "Данные сессии устарели. Начните заново.", reply_markup=menu_kb())
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    # Select keyword for generation
    keyword = await select_keyword(db, category_id, content_type="social")
    if not keyword:
        await try_refund(db, user, cost, "Нет ключевых фраз")
        await safe_edit_text(
            message,
            "Нет доступных ключевых фраз. Добавьте их в категорию.",
            reply_markup=menu_kb(),
        )
        await state.set_state(SocialPipelineFSM.confirm_cost)
        return

    try:
        # Update progress: step 1 done, step 2 active
        try:
            await safe_edit_text(message, _social_progress_text(_SOCIAL_STEPS, 1))
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

        # Generate 1 image for social post (B2 fix)
        image_b64: str | None = None
        with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
            await safe_edit_text(message, _social_progress_text(_SOCIAL_STEPS, 2))

        try:
            image_service = ImageService(ai_orchestrator)
            cat = await CategoriesRepository(db).get_by_id(category_id)
            proj = await ProjectsRepository(db).get_by_id(project_id)
            img_settings = dict((proj.image_settings if proj else None) or (cat.image_settings if cat else None) or {})
            # Pinterest: vertical 2:3 aspect ratio
            if platform_type == "pinterest":
                img_settings["formats"] = ["2:3"]
            img_context: dict[str, Any] = {
                "keyword": keyword,
                "content_type": "social_post",
                "company_name": (proj.company_name or "") if proj else "",
                "specialization": (proj.specialization or "") if proj else "",
                "image_settings": img_settings,
            }
            images = await image_service.generate(user_id=user.id, context=img_context, count=1)
            if images:
                image_b64 = b64mod.b64encode(images[0].data).decode("ascii")
                log.info("social_image_generated", size=len(images[0].data), user_id=user.id)
        except RateLimitError:
            raise  # Re-raise to respect rate limits
        except Exception:
            # Graceful degradation for TG/VK; Pinterest validated at publish
            log.warning("social_image_generation_failed", exc_info=True, user_id=user.id)

        # Extract pin_title from AI response
        pin_title = ""
        if isinstance(result.content, dict):
            pin_title = result.content.get("pin_title", "")

        # E38: store in FSM state.data (not DB), acceptable to lose on timeout
        update_data: dict[str, Any] = {
            "generated_text": post_text,
            "generated_hashtags": hashtags,
            "generated_keyword": keyword,
            "generated_model": result.model_used,
            "generated_prompt_version": result.prompt_version,
            "generated_image_b64": image_b64,
            "generated_pin_title": pin_title,
        }
        await state.update_data(**update_data)
        await state.set_state(SocialPipelineFSM.review)

        # Build review screen text (show inline, no Telegraph for social posts)
        data = await state.get_data()
        regen_count = data.get("regen_count", 0)
        tokens_charged = data.get("tokens_charged", cost)

        review_text = _build_review_text(post_text, hashtags, keyword, tokens_charged, platform_type)

        review_kb = social_review_kb(regen_count=regen_count, regen_cost=cost)
        await _show_review(message, review_text, review_kb, image_b64)
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
        await safe_edit_text(
            message,
            "Ошибка генерации поста. Токены возвращены.\n\nПопробуйте ещё раз.",
            reply_markup=menu_kb(),
        )
        await state.set_state(SocialPipelineFSM.confirm_cost)


_CAPTION_LIMIT = 1024


async def _show_review(
    message: Message,
    review_text: str,
    review_kb: InlineKeyboardMarkup,
    image_b64: str | None,
) -> None:
    """Show review screen with optional photo preview.

    If image_b64 is provided, sends photo+caption. Falls back to text
    if caption exceeds Telegram's 1024-char limit (photo first, then text+KB).
    """
    if not image_b64:
        await safe_edit_text(message, review_text, reply_markup=review_kb)
        return

    image_bytes = b64mod.b64decode(image_b64)
    photo = BufferedInputFile(image_bytes, filename="preview.webp")

    # Delete previous message (could be progress text or old photo)
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()

    if len(review_text) <= _CAPTION_LIMIT:
        await message.answer_photo(
            photo=photo,
            caption=review_text,
            reply_markup=review_kb,
        )
    else:
        # Photo without caption, then text with keyboard
        await message.answer_photo(photo=photo)
        await message.answer(review_text, reply_markup=review_kb)


def _build_review_text(
    post_text: str,
    hashtags: list[str],
    keyword: str,
    tokens_charged: int,
    platform: str,
) -> str:
    """Build review display text for social post.

    Escaping strategy differs by platform:
    - Telegram: nh3 preserved <b>,<i> tags — already valid HTML for parse_mode=HTML.
    - VK/Pinterest: nh3 stripped all tags, output has HTML entities (& → &amp;).
      We unescape then re-escape to normalize for Telegram's parse_mode=HTML display.
    """
    lines = [
        "Пост готов!\n",
        f"Ключевая фраза: {html.escape(keyword)}",
        f"Списано: {tokens_charged} ток.\n",
        "---",
    ]
    if platform == "telegram":
        # nh3 left <b>,<i> — already valid HTML for parse_mode=HTML
        lines.append(post_text)
    else:
        # nh3 output has HTML entities (e.g. &amp;) — normalize for display
        lines.append(html.escape(html.unescape(post_text)))

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
    generated_hashtags: list[str] = data.get("generated_hashtags", [])
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
    # Capture return: safe_edit_text may delete photo and send new text msg
    msg = await safe_edit_text(msg, _social_publish_progress(platform_type, 0))

    try:
        # Load connection
        conn_svc = ConnectionService(db, http_client)
        connection = await conn_svc.get_by_id(connection_id)
        if not connection:
            await safe_edit_text(
                msg,
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
            await safe_edit_text(msg, "Доступ запрещён.", reply_markup=menu_kb())
            await callback.answer()
            return

        # Get publisher for platform (with token refresh to persist refreshed credentials)
        from bot.config import get_settings as _get_settings
        from services.publishers.factory import make_token_refresh_cb

        _settings = _get_settings()
        _enc_key = _settings.encryption_key.get_secret_value()
        _on_refresh = make_token_refresh_cb(db, connection.id, _enc_key)
        publisher = _get_publisher(platform_type, http_client, _settings, on_token_refresh=_on_refresh)
        content_type = _get_content_type(platform_type)

        # Append hashtags for all social platforms (Pinterest uses description field)
        publish_text = generated_text
        if generated_hashtags:
            tags_str = " ".join(f"#{h.lstrip('#')}" for h in generated_hashtags)
            publish_text = f"{generated_text}\n\n{tags_str}"

        # Pinterest metadata: use AI-generated pin_title, fallback to keyword
        pub_metadata: dict[str, Any] = {}
        if platform_type == "pinterest":
            pin_title = data.get("generated_pin_title") or keyword[:100]
            pub_metadata["pin_title"] = pin_title

        # Decode image from FSM state (B2 fix)
        publish_images: list[bytes] = []
        image_b64_stored = data.get("generated_image_b64")
        if image_b64_stored:
            publish_images = [b64mod.b64decode(image_b64_stored)]

        # Pinterest requires at least one image
        if platform_type == "pinterest" and not publish_images:
            await safe_edit_text(
                msg,
                "Для Pinterest требуется изображение, но оно не было сгенерировано.\nПопробуйте перегенерировать пост.",
                reply_markup=social_review_kb(
                    regen_count=data.get("regen_count", 0),
                    regen_cost=tokens_charged,
                ),
            )
            await state.set_state(SocialPipelineFSM.review)
            await callback.answer()
            return

        # Step 2: Publishing to platform
        with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
            await safe_edit_text(msg, _social_publish_progress(platform_type, 1))

        try:
            pub_result: PublishResult = await publisher.publish(
                PublishRequest(
                    connection=connection,
                    content=publish_text,
                    content_type=content_type,
                    metadata=pub_metadata,
                    images=publish_images,
                )
            )
        except Exception as exc:
            log.exception("pipeline.social.publish_failed", error=str(exc))
            await safe_edit_text(
                msg,
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
            await safe_edit_text(
                msg,
                f"Ошибка публикации: {pub_result.error or 'неизвестная ошибка'}",
                reply_markup=social_review_kb(
                    regen_count=data.get("regen_count", 0),
                    regen_cost=tokens_charged,
                ),
            )
            await state.set_state(SocialPipelineFSM.review)
            await callback.answer()
            return

        # Step 3: Saving result
        with contextlib.suppress(TelegramBadRequest, TelegramRetryAfter):
            await safe_edit_text(msg, _social_publish_progress(platform_type, 2))

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
                images_count=len(publish_images),
                post_url=pub_result.post_url,
                word_count=len(generated_text.split()),
                tokens_spent=tokens_charged,
                ai_model=data.get("generated_model"),
                prompt_version=data.get("generated_prompt_version"),
            )
        )

        # Check if there are other social connections for cross-posting
        has_crosspost = False
        if project_id:
            all_connections = await conn_svc.get_by_project(project_id)
            has_crosspost = any(c.id != connection_id and c.platform_type != "wordpress" for c in all_connections)

        # Show result
        balance = await TokenService(db=db, admin_ids=get_settings().admin_ids).get_balance(user.id)

        result_text = (
            "Пост опубликован!\n\n"
            f"Ключевая фраза: {html.escape(keyword)}\n"
            f"Списано: {tokens_charged} ток. | Баланс: {balance} ток."
        )
        await safe_edit_text(
            msg,
            result_text,
            reply_markup=social_result_kb(pub_result.post_url, has_crosspost),
        )
        await clear_checkpoint(redis, user.id)
        await callback.answer()

        log.info(
            "pipeline.social.published",
            user_id=user.id,
            platform=platform_type,
            post_url=pub_result.post_url,
        )
    except Exception:
        log.exception("pipeline.social.publish_unhandled", user_id=user.id)
        # Ensure user is never stuck: reset to review with error message
        with contextlib.suppress(Exception):
            await msg.answer(
                "Ошибка публикации. Попробуйте снова.",
                reply_markup=social_review_kb(
                    regen_count=data.get("regen_count", 0),
                    regen_cost=tokens_charged,
                ),
            )
        await state.set_state(SocialPipelineFSM.review)
        with contextlib.suppress(Exception):
            await callback.answer()
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

    # Previous review may be a photo message — delete and send fresh text
    with contextlib.suppress(TelegramBadRequest):
        await msg.delete()
    progress_msg = await msg.answer(_social_progress_text(_SOCIAL_STEPS, 0))
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
        progress_msg,
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
    await safe_edit_text(msg, "Пост отменён. Токены возвращены.", reply_markup=menu_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Result handlers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_publisher(
    platform_type: str,
    http_client: httpx.AsyncClient,
    settings: Any = None,
    on_token_refresh: Any = None,
) -> Any:
    """Get publisher instance for platform type with proper credentials."""
    from services.publishers.factory import create_publisher

    if settings is None:
        from bot.config import get_settings

        settings = get_settings()
    return create_publisher(platform_type, http_client, settings, on_token_refresh=on_token_refresh)


def _get_content_type(platform_type: str) -> Literal["html", "telegram_html", "plain_text", "pin_text"]:
    """Map platform type to content type for PublishRequest."""
    content_types: dict[str, Literal["html", "telegram_html", "plain_text", "pin_text"]] = {
        "telegram": "telegram_html",
        "vk": "plain_text",
        "pinterest": "pin_text",
    }
    return content_types.get(platform_type, "plain_text")


# ---------------------------------------------------------------------------
# Cross-post flow (F6.4, UX_PIPELINE.md §6)
# ---------------------------------------------------------------------------

_SOCIAL_TYPES = {"telegram", "vk", "pinterest"}


@router.callback_query(F.data == "pipeline:crosspost:start")
async def crosspost_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
) -> None:
    """Start cross-post: show platform selection or go directly if only 1."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    connection_id = data.get("connection_id")
    generated_text = data.get("generated_text", "")
    keyword = data.get("generated_keyword", "")

    if not project_id or not connection_id or not generated_text:
        await callback.answer("Данные сессии устарели.", show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    all_conns = await conn_svc.get_by_project(project_id)
    targets = [c for c in all_conns if c.id != connection_id and c.platform_type in _SOCIAL_TYPES]

    if not targets:
        await callback.answer("Нет других подключений для кросс-поста.", show_alert=True)
        return

    # Store targets and all selected by default
    target_ids = {c.id for c in targets}
    await state.update_data(
        crosspost_target_ids=list(target_ids),
        crosspost_selected_ids=list(target_ids),
    )

    if len(targets) == 1:
        # Skip selection screen, go directly to adaptation
        await state.update_data(crosspost_selected_ids=[targets[0].id])
        await state.set_state(SocialPipelineFSM.cross_post_running)
        await _execute_crosspost(msg, state, user, db, redis, http_client, ai_orchestrator, callback)
        return

    from keyboards.pipeline import crosspost_select_kb

    await safe_edit_text(
        msg,
        f"Кросс-пост: {html.escape(keyword)}\n\nНа какие платформы адаптировать?",
        reply_markup=crosspost_select_kb(targets, target_ids),
    )
    await state.set_state(SocialPipelineFSM.cross_post_select)
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.cross_post_select,
    F.data.startswith("pipeline:crosspost:toggle:"),
)
async def crosspost_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Toggle a platform in cross-post selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    try:
        toggle_id = int(parts[3])
    except ValueError:
        await callback.answer()
        return

    data = await state.get_data()
    selected: set[int] = set(data.get("crosspost_selected_ids", []))
    target_ids: list[int] = data.get("crosspost_target_ids", [])

    if toggle_id in selected:
        selected.discard(toggle_id)
    else:
        selected.add(toggle_id)

    await state.update_data(crosspost_selected_ids=list(selected))

    # Rebuild keyboard with updated selection
    project_id: int = data.get("project_id", 0)
    conn_svc = ConnectionService(db, http_client)
    all_conns = await conn_svc.get_by_project(project_id)
    targets = [c for c in all_conns if c.id in target_ids]

    from keyboards.pipeline import crosspost_select_kb

    await msg.edit_reply_markup(reply_markup=crosspost_select_kb(targets, selected))
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.cross_post_select,
    F.data == "pipeline:crosspost:go",
)
async def crosspost_go(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
) -> None:
    """Execute cross-posting for selected platforms."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    selected = data.get("crosspost_selected_ids", [])
    if not selected:
        await callback.answer("Выберите хотя бы одну платформу.", show_alert=True)
        return

    await state.set_state(SocialPipelineFSM.cross_post_running)
    await _execute_crosspost(msg, state, user, db, redis, http_client, ai_orchestrator, callback)


@router.callback_query(F.data == "pipeline:crosspost:cancel")
async def crosspost_cancel(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Cancel cross-posting, return to dashboard."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.clear()
    await safe_edit_text(msg, "Кросс-постинг отменён.", reply_markup=menu_kb())
    await callback.answer()


async def _execute_crosspost(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
    callback: CallbackQuery,
) -> None:
    """Run AI adaptation and publish for each selected platform."""
    from services.ai.social_posts import SocialPostService
    from services.tokens import TokenService, estimate_cross_post_cost

    data = await state.get_data()
    selected_ids: list[int] = data.get("crosspost_selected_ids", [])
    project_id: int = data.get("project_id", 0)
    category_id: int = data.get("category_id", 0)
    generated_text: str = data.get("generated_text", "")
    keyword: str = data.get("generated_keyword", "")
    platform_type: str = data.get("platform_type", "")

    # E07: Redis NX lock to prevent double-click
    lock_key = f"crosspost:{user.id}:{project_id}"
    acquired = await redis.set(lock_key, "1", ex=_PUBLISH_LOCK_TTL, nx=True)
    if not acquired:
        await safe_edit_text(msg, "Кросс-постинг уже выполняется...")
        await callback.answer()
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    social_svc = SocialPostService(ai_orchestrator, db, skip_rate_limit=True)
    conn_svc = ConnectionService(db, http_client)

    # Progress message
    await safe_edit_text(msg, "Адаптирую посты...")

    results: list[str] = []
    total_cost = 0

    try:
        for conn_id in selected_ids:
            conn = await conn_svc.get_by_id(conn_id)
            if not conn or conn.status != "active":
                results.append(f"{Emoji.CLOSE} {conn_id}: подключение неактивно")
                continue

            cost = estimate_cross_post_cost()

            # Balance check (not GOD_MODE)
            is_god = user.id in settings.admin_ids
            if not is_god and not await token_svc.check_balance(user.id, cost):
                results.append(f"{Emoji.CLOSE} {conn.platform_type.upper()}: недостаточно токенов")
                break

            try:
                adapted = await social_svc.adapt_for_platform(
                    original_text=generated_text,
                    source_platform=platform_type,
                    target_platform=conn.platform_type,
                    user_id=user.id,
                    project_id=project_id,
                    keyword=keyword,
                )

                if isinstance(adapted.content, dict):
                    adapted_text = adapted.content.get("text", "")
                    hashtags = adapted.content.get("hashtags", [])
                    if hashtags:
                        tags_str = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
                        adapted_text = f"{adapted_text}\n\n{tags_str}"
                else:
                    adapted_text = str(adapted.content) if adapted.content else generated_text

                # Get publisher and publish (with token refresh for Pinterest)
                from services.publishers.factory import make_token_refresh_cb

                enc_key = settings.encryption_key.get_secret_value()
                on_refresh = make_token_refresh_cb(db, conn.id, enc_key)
                publisher = _get_publisher(conn.platform_type, http_client, settings, on_token_refresh=on_refresh)

                ct = _get_content_type(conn.platform_type)
                category = await CategoriesRepository(db).get_by_id(category_id)

                metadata: dict[str, str] = {}
                if conn.platform_type == "pinterest" and isinstance(adapted.content, dict):
                    metadata["pin_title"] = adapted.content.get("pin_title", "")[:100]

                # Attach image from FSM state (required for Pinterest)
                publish_images: list[bytes] = []
                image_b64_stored = data.get("generated_image_b64")
                if image_b64_stored:
                    publish_images = [b64mod.b64decode(image_b64_stored)]

                pub_result: PublishResult = await publisher.publish(
                    PublishRequest(
                        connection=conn,
                        content=adapted_text,
                        content_type=ct,
                        category=category,
                        metadata=metadata,
                        images=publish_images,
                    )
                )

                if not pub_result.success:
                    results.append(f"{Emoji.CLOSE} {conn.platform_type.upper()}: {pub_result.error}")
                    continue

                # Charge after successful publish
                if not is_god:
                    await token_svc.charge(
                        user.id,
                        cost,
                        "cross_post",
                        description=f"Cross-post: {keyword}",
                    )
                total_cost += cost

                # Log publication
                pub_repo = PublicationsRepository(db)
                await pub_repo.create_log(
                    PublicationLogCreate(
                        user_id=user.id,
                        project_id=project_id,
                        category_id=category_id,
                        platform_type=conn.platform_type,
                        connection_id=conn.id,
                        keyword=keyword,
                        content_type="cross_post",
                        tokens_spent=cost,
                        post_url=pub_result.post_url or "",
                    )
                )

                url_part = f": {pub_result.post_url}" if pub_result.post_url else ""
                results.append(f"{Emoji.CHECKMARK} {conn.platform_type.upper()}{url_part}")

                log.info(
                    "pipeline.crosspost.published",
                    user_id=user.id,
                    platform=conn.platform_type,
                    conn_id=conn.id,
                )

            except Exception:
                log.exception("pipeline.crosspost.failed", conn_id=conn_id)
                results.append(f"{Emoji.CLOSE} {conn.platform_type.upper()}: ошибка адаптации")
    finally:
        await redis.delete(lock_key)

    # Show results
    balance = await token_svc.get_balance(user.id)
    result_lines = "\n".join(results)
    text = f"Кросс-постинг завершён:\n\n{result_lines}\n\nСписано: {total_cost} ток. | Баланс: {balance} ток."

    from keyboards.pipeline import crosspost_result_kb

    await safe_edit_text(msg, text, reply_markup=crosspost_result_kb())
    await state.set_state(SocialPipelineFSM.cross_post_result)
    await callback.answer()
