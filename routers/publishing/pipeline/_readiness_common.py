"""Common readiness sub-flow logic shared between article and social pipelines (S1b).

Extracts the keyword generation pipeline and description generation logic
that were duplicated between readiness.py and social/readiness.py.
Differences are passed via parameters (FSM state, callback prefix, log prefix, etc.).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

import structlog
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.helpers import safe_message
from db.models import CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from keyboards.pipeline import pipeline_back_to_checklist_kb
from services.ai.description import DescriptionService
from services.keywords import KeywordService
from services.tokens import COST_DESCRIPTION, TokenService

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.state import State

    from cache.client import RedisClient
    from db.client import SupabaseClient
    from services.ai.orchestrator import AIOrchestrator
    from services.external.dataforseo import DataForSEOClient

log = structlog.get_logger()


# ---------------------------------------------------------------------------
# Keyword generation pipeline (shared between article and social readiness)
# ---------------------------------------------------------------------------


async def run_keyword_generation(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    *,
    category_id: int,
    project_id: int,
    products: str,
    geography: str,
    quantity: int,
    cost: int,
    token_service: TokenService,
    ai_orchestrator: AIOrchestrator,
    dataforseo_client: DataForSEOClient,
    log_prefix: str,
    readiness_state: State,
    back_kb_prefix: str = "pipeline:readiness",
    on_success: Callable[[Message, FSMContext, User, SupabaseClient, RedisClient], Awaitable[None]],
) -> None:
    """Run keyword pipeline: fetch -> cluster -> enrich -> save -> return to checklist.

    This is the shared core of both article and social readiness keyword generation.
    AI clustering (DeepSeek) can take 60-90 seconds. Progress updates use _safe_edit
    (tolerates Telegram errors) and the final result is sent as a NEW message.

    Args:
        log_prefix: e.g. "pipeline.readiness" or "pipeline.social.readiness"
        readiness_state: FSM state to set on error (e.g. ArticlePipelineFSM.readiness_check)
        back_kb_prefix: prefix for the back-to-checklist button
        on_success: async callback to show readiness checklist after success
    """
    msg = safe_message(callback)
    if not msg:
        return

    async def _safe_edit(text: str) -> None:
        """Edit message, silently ignoring Telegram errors (expired message, etc.)."""
        try:
            await msg.edit_text(text)  # type: ignore[union-attr]
        except Exception:
            log.debug(f"{log_prefix}.edit_failed", text=text[:50])

    try:
        kw_service = KeywordService(
            orchestrator=ai_orchestrator,
            dataforseo=dataforseo_client,
            db=db,
        )

        # Step 1: Fetch raw phrases from DataForSEO (~1-3s)
        raw_phrases = await kw_service.fetch_raw_phrases(
            products=products,
            geography=geography,
            quantity=quantity,
            project_id=project_id,
            user_id=user.id,
        )

        if raw_phrases:
            # Step 2a: DataForSEO had data -> AI clustering (~60-90s)
            await _safe_edit(f"Получено {len(raw_phrases)} фраз. Группирую по интенту (до 1.5 мин)...")
            clusters = await kw_service.cluster_phrases(
                raw_phrases=raw_phrases,
                products=products,
                geography=geography,
                quantity=quantity,
                project_id=project_id,
                user_id=user.id,
            )
        else:
            # Step 2b: DataForSEO empty -> single AI call generates clusters directly
            await _safe_edit("DataForSEO без данных. Генерирую фразы через AI (до 1.5 мин)...")
            clusters = await kw_service.generate_clusters_direct(
                products=products,
                geography=geography,
                quantity=quantity,
                project_id=project_id,
                user_id=user.id,
            )

        # Step 3: Enrich with metrics (~3s)
        await _safe_edit(f"Создано {len(clusters)} кластеров. Обогащаю данными...")
        enriched = await kw_service.enrich_clusters(clusters)

        # Filter AI-invented zero-volume junk
        enriched = kw_service.filter_low_quality(enriched)

        # Save (MERGE with existing)
        cats_repo = CategoriesRepository(db)
        category = await cats_repo.get_by_id(category_id)
        existing: list[dict[str, Any]] = (category.keywords if category else []) or []
        merged = existing + enriched
        await cats_repo.update_keywords(category_id, merged)

        total_phrases = sum(len(c.get("phrases", [])) for c in enriched)
        total_volume = sum(c.get("total_volume", 0) for c in enriched)

        log.info(
            f"{log_prefix}.keywords_generated",
            user_id=user.id,
            category_id=category_id,
            clusters=len(enriched),
            phrases=total_phrases,
            cost=cost,
        )

        # Delete progress message and send results as a NEW message
        # (original callback message may be stale after 90s)
        try:
            await msg.delete()
        except Exception:
            log.debug(f"{log_prefix}.delete_progress_failed")

        bot = msg.bot
        if not bot:
            return
        await bot.send_message(
            chat_id=msg.chat.id,
            text=(
                f"Готово! Добавлено:\n"
                f"Кластеров: {len(enriched)}\n"
                f"Фраз: {total_phrases}\n"
                f"Общий объём: {total_volume:,}/мес\n\n"
                f"Списано {cost} токенов."
            ),
        )
        await asyncio.sleep(1)
        await on_success(msg, state, user, db, redis)

    except Exception:
        log.exception(
            f"{log_prefix}.keywords_failed",
            user_id=user.id,
            category_id=category_id,
        )
        # Refund on error
        await token_service.refund(
            user_id=user.id,
            amount=cost,
            reason="refund",
            description=f"Возврат: ошибка подбора фраз ({log_prefix}, категория #{category_id})",
        )
        # Send error as new message (original may be expired)
        with contextlib.suppress(Exception):
            await msg.delete()
        bot = msg.bot
        if not bot:
            return
        await bot.send_message(
            chat_id=msg.chat.id,
            text="Ошибка при подборе фраз. Токены возвращены.\nПопробуйте позже.",
            reply_markup=pipeline_back_to_checklist_kb(prefix=back_kb_prefix),
        )
        await state.set_state(readiness_state)


# ---------------------------------------------------------------------------
# Description AI generation (shared between article and social readiness)
# ---------------------------------------------------------------------------


async def generate_description_ai(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
    *,
    log_prefix: str,
    on_success: Callable[
        [CallbackQuery, FSMContext, User, SupabaseClient, RedisClient], Awaitable[None]
    ],
) -> None:
    """Generate category description via AI, charge tokens, and return to checklist.

    Shared between article and social readiness description:ai handlers.

    Args:
        log_prefix: e.g. "pipeline.readiness" or "pipeline.social.readiness"
        on_success: async callback to show readiness checklist after success
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    if not category_id or not project_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)

    # E01: balance check
    has_balance = await token_svc.check_balance(user.id, COST_DESCRIPTION)
    if not has_balance:
        balance = await token_svc.get_balance(user.id)
        await callback.answer(
            token_svc.format_insufficient_msg(COST_DESCRIPTION, balance),
            show_alert=True,
        )
        return

    # Answer callback immediately so the button stops "loading"
    await callback.answer()
    await callback.message.edit_text("Генерирую описание...")  # type: ignore[union-attr]

    # Debit-first: charge before generation, refund on failure
    try:
        await token_svc.charge(
            user_id=user.id,
            amount=COST_DESCRIPTION,
            operation_type="description",
            description=f"Описание ({log_prefix}, категория #{category_id})",
        )
    except Exception:
        log.exception(f"{log_prefix}.description_charge_failed", user_id=user.id)
        await callback.message.edit_text("Ошибка списания токенов.")  # type: ignore[union-attr]
        return

    # Generate + save; refund on any failure
    desc_svc = DescriptionService(orchestrator=ai_orchestrator, db=db)
    try:
        result = await desc_svc.generate(
            user_id=user.id,
            project_id=project_id,
            category_id=category_id,
        )
        generated = result.content if isinstance(result.content, str) else str(result.content)

        cats_repo = CategoriesRepository(db)
        save_result = await cats_repo.update(category_id, CategoryUpdate(description=generated))
        if not save_result:
            raise RuntimeError("description_save_failed")  # noqa: TRY301
    except Exception:
        # Refund on any error after charge
        await token_svc.refund(
            user_id=user.id,
            amount=COST_DESCRIPTION,
            reason="refund",
            description=f"Возврат: ошибка описания (категория #{category_id})",
        )
        log.exception(
            f"{log_prefix}.description_ai_failed",
            user_id=user.id,
            category_id=category_id,
        )
        await callback.message.edit_text("Ошибка генерации описания. Токены возвращены.")  # type: ignore[union-attr]
        return

    log.info(
        f"{log_prefix}.description_generated",
        user_id=user.id,
        category_id=category_id,
        cost=COST_DESCRIPTION,
    )

    await on_success(callback, state, user, db, redis)
