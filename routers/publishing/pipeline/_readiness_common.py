"""Common readiness sub-flow logic shared between article and social pipelines (S1b).

Extracts the keyword generation pipeline, description generation logic,
and readiness sub-flow handler registration factory that were duplicated
between readiness.py and social/readiness.py.
Differences are passed via ReadinessConfig and parameters.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.helpers import safe_message
from db.models import CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import cancel_kb
from keyboards.pipeline import (
    pipeline_back_to_checklist_kb,
    pipeline_description_options_kb,
    pipeline_keywords_city_kb,
    pipeline_keywords_confirm_kb,
    pipeline_keywords_options_kb,
    pipeline_keywords_qty_kb,
)
from services.ai.description import DescriptionService
from services.keywords import KeywordService
from services.tokens import COST_DESCRIPTION, TokenService, estimate_keywords_cost

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

    from cache.client import RedisClient
    from db.client import SupabaseClient
    from services.ai.orchestrator import AIOrchestrator
    from services.external.dataforseo import DataForSEOClient

log = structlog.get_logger()

# Limits for keyword upload (shared between article and social readiness)
MAX_KEYWORD_PHRASES = 500
MAX_KEYWORD_FILE_SIZE = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# ReadinessConfig — parameterizes differences between article/social
# ---------------------------------------------------------------------------


# Type alias for the show_check callback (called after callback_query sub-flows)
ShowCheckCb = Callable[
    [CallbackQuery, "FSMContext", User, "SupabaseClient", "RedisClient"],
    Awaitable[None],
]
# Type alias for the show_check_msg callback (called after message sub-flows)
ShowCheckMsgCb = Callable[
    [Message, "FSMContext", User, "SupabaseClient", "RedisClient"],
    Awaitable[None],
]


@dataclass(frozen=True)
class ReadinessConfig:
    """Configuration that parameterizes readiness sub-flow differences.

    Used by register_readiness_subflows() to create handlers with
    the correct FSM states, callback prefixes, and return functions.
    """

    fsm_class: Any
    """FSM StatesGroup: ArticlePipelineFSM or SocialPipelineFSM.

    Typed as Any because both FSM classes are StatesGroup subclasses with
    matching readiness_* State attributes, but mypy can't express this
    structural subtyping for StatesGroup classes.
    """

    prefix: str
    """Callback prefix: 'pipeline:readiness' or 'pipeline:social:readiness'."""

    cancel_cb: str
    """Cancel callback_data: 'pipeline:article:cancel' or 'pipeline:social:cancel'."""

    log_prefix: str
    """Structlog prefix: 'pipeline.readiness' or 'pipeline.social.readiness'."""

    show_check: ShowCheckCb
    """Callback to show readiness checklist after callback_query sub-flows."""

    show_check_msg: ShowCheckMsgCb
    """Callback to show readiness checklist after message sub-flows."""

    description_hint: str = "статьи"
    """Hint text for description prompt: 'статьи' or 'посты'."""

    charge_suffix: str = "pipeline"
    """Suffix for token charge description: 'pipeline' or 'social pipeline'."""

    extra_back_states: list[Any] = field(default_factory=list)
    """Extra FSM states for the back-from-input handler (e.g. readiness_prices)."""


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
            raise RuntimeError("description_save_failed")
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


# ---------------------------------------------------------------------------
# Readiness sub-flow handler factory
# ---------------------------------------------------------------------------


def register_readiness_subflows(router: Router, cfg: ReadinessConfig) -> dict[str, Any]:  # noqa: C901
    """Register keyword/description/navigation handlers on the given router.

    Uses programmatic registration (router.callback_query / router.message)
    instead of decorators so the same logic can serve both article and social pipelines.

    Returns a dict mapping handler names to handler functions (for test imports).

    Note: C901 complexity is expected -- this is a factory function that defines
    18 handler functions. Splitting would reduce cohesion without improving readability.
    """
    fsm = cfg.fsm_class
    prefix = cfg.prefix
    cancel_cb = cfg.cancel_cb
    log_prefix = cfg.log_prefix

    # Build regex for qty callback to match e.g. "pipeline:readiness:keywords:qty_100"
    # We need to escape prefix for regex since it contains colons
    prefix_escaped = re.escape(prefix)
    qty_pattern = rf"^{prefix_escaped}:keywords:qty_(\d+)$"

    # -----------------------------------------------------------------------
    # Keywords sub-flow
    # -----------------------------------------------------------------------

    async def readiness_keywords_menu(callback: CallbackQuery) -> None:
        """Show keyword generation options."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        await callback.message.edit_text(
            "Ключевые фразы\n\nВыберите способ добавления:",
            reply_markup=pipeline_keywords_options_kb(prefix=prefix),
        )
        await callback.answer()

    router.callback_query.register(
        readiness_keywords_menu,
        fsm.readiness_check,
        F.data == f"{prefix}:keywords",
    )

    async def readiness_keywords_auto(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
    ) -> None:
        """Auto keyword generation -- quick path (100 phrases, defaults from DB)."""
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

        cats_repo = CategoriesRepository(db)
        category = await cats_repo.get_by_id(category_id)
        if not category:
            await callback.answer("Категория не найдена.", show_alert=True)
            return

        projects_repo = ProjectsRepository(db)
        project = await projects_repo.get_by_id(project_id)

        products = category.name
        geography = project.company_city if project and project.company_city else None

        # UX_PIPELINE SS4a: if no company_city -- ask city first
        if not geography:
            await state.set_state(fsm.readiness_keywords_geo)
            await state.update_data(kw_products=products, kw_mode="auto")

            await callback.message.edit_text(
                "В каком городе ваш бизнес?\n<i>Для точных SEO-фраз</i>",
                reply_markup=pipeline_keywords_city_kb(prefix=prefix),
            )
            await callback.answer()
            return

        quantity = 100
        cost = estimate_keywords_cost(quantity)

        settings = get_settings()
        token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
        balance = await token_svc.get_balance(user.id)

        await state.set_state(fsm.readiness_keywords_qty)
        await state.update_data(
            kw_products=products,
            kw_geography=geography,
            kw_quantity=quantity,
            kw_cost=cost,
        )

        await callback.message.edit_text(
            f"Автоподбор ключевых фраз\n\n"
            f"Тема: {html.escape(products)}\n"
            f"География: {html.escape(geography)}\n"
            f"Количество: {quantity} фраз\n\n"
            f"Стоимость: {cost} ток. Баланс: {balance}.",
            reply_markup=pipeline_keywords_confirm_kb(cost, balance, prefix=prefix),
        )
        await callback.answer()

    router.callback_query.register(
        readiness_keywords_auto,
        fsm.readiness_check,
        F.data == f"{prefix}:keywords:auto",
    )

    async def readiness_keywords_configure(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        """Configure keyword generation -- full path (products -> geo -> qty -> confirm)."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        await state.set_state(fsm.readiness_keywords_products)
        await state.update_data(kw_mode="configure")

        await callback.message.edit_text(
            "Какие товары или услуги продвигаете?\n"
            "<i>Например: кухни на заказ, шкафы-купе, корпусная мебель</i>\n\n"
            "От 3 до 1000 символов.",
            reply_markup=pipeline_back_to_checklist_kb(prefix=prefix),
        )
        await callback.answer()

    router.callback_query.register(
        readiness_keywords_configure,
        fsm.readiness_check,
        F.data == f"{prefix}:keywords:configure",
    )

    async def readiness_keywords_upload_start(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        """Start keyword upload sub-flow -- prompt for TXT file."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        await callback.message.edit_text(
            "Загрузите TXT-файл с ключевыми фразами.\n"
            "Одна фраза на строку, максимум 500 фраз, до 1 МБ.\n\n"
            "Или отправьте фразы текстом (каждая с новой строки).",
            reply_markup=pipeline_back_to_checklist_kb(prefix=prefix),
        )
        await state.set_state(fsm.readiness_keywords_products)
        await state.update_data(kw_mode="upload")
        await callback.answer()

    router.callback_query.register(
        readiness_keywords_upload_start,
        fsm.readiness_check,
        F.data == f"{prefix}:keywords:upload",
    )

    async def readiness_keywords_upload_file(
        message: Message,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Process uploaded TXT file with keyword phrases."""
        doc = message.document
        if not doc:
            await message.answer("Файл не найден.")
            return

        filename = doc.file_name or ""
        if not filename.lower().endswith(".txt"):
            await message.answer(
                "Нужен .txt файл (UTF-8), одна фраза на строку.",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        if doc.file_size and doc.file_size > MAX_KEYWORD_FILE_SIZE:
            await message.answer(
                "Файл слишком большой (макс. 1 МБ).",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        file = await message.bot.download(doc)  # type: ignore[union-attr]
        if file is None:
            await message.answer("Не удалось загрузить файл.")
            return

        content = file.read().decode("utf-8", errors="replace")
        phrases = [line.strip() for line in content.splitlines() if line.strip()]

        if not phrases:
            await message.answer(
                "Файл пустой. Добавьте фразы (одна на строку).",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        if len(phrases) > MAX_KEYWORD_PHRASES:
            await message.answer(
                f"Максимум {MAX_KEYWORD_PHRASES} фраз. Сейчас: {len(phrases)}.",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        # Save as flat keyword format
        data = await state.get_data()
        category_id = data.get("category_id")
        if not category_id:
            await message.answer("Категория не найдена. Начните заново.")
            return

        keywords = [{"phrase": p, "volume": 0, "cpc": 0.0} for p in phrases]
        cats_repo = CategoriesRepository(db)
        await cats_repo.update_keywords(category_id, keywords)

        log.info(
            f"{log_prefix}.keywords_uploaded",
            user_id=user.id,
            category_id=category_id,
            phrase_count=len(phrases),
        )

        await message.answer(f"Загружено {len(phrases)} фраз.")
        await cfg.show_check_msg(message, state, user, db, redis)

    router.message.register(
        readiness_keywords_upload_file,
        fsm.readiness_keywords_products,
        F.document,
    )

    async def _handle_configure_products(message: Message, state: FSMContext) -> None:
        """Validate products input for configure keyword path (3-1000 chars)."""
        text = (message.text or "").strip()
        if len(text) < 3 or len(text) > 1000:
            await message.answer(
                "Введите от 3 до 1000 символов.",
                reply_markup=pipeline_back_to_checklist_kb(prefix=prefix),
            )
            return

        await state.set_state(fsm.readiness_keywords_geo)
        await state.update_data(kw_products=text)

        await message.answer(
            "Укажите географию продвижения:\n<i>Например: Москва, Россия, СНГ</i>\n\nОт 2 до 200 символов.",
            reply_markup=pipeline_back_to_checklist_kb(prefix=prefix),
        )

    async def readiness_keywords_text_input(
        message: Message,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Handle text input -- route by kw_mode (configure=products, upload=phrases)."""
        data = await state.get_data()
        kw_mode = data.get("kw_mode", "upload")

        if kw_mode == "configure":
            await _handle_configure_products(message, state)
            return

        # Upload mode: process text as keyword phrases (one per line)
        text = (message.text or "").strip()
        if not text:
            await message.answer(
                "Отправьте TXT-файл или введите фразы текстом (каждая с новой строки).",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        phrases = [line.strip() for line in text.splitlines() if line.strip()]
        if not phrases:
            await message.answer(
                "Не удалось распознать фразы. Каждая фраза -- с новой строки.",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        if len(phrases) > MAX_KEYWORD_PHRASES:
            await message.answer(
                f"Максимум {MAX_KEYWORD_PHRASES} фраз. Сейчас: {len(phrases)}.",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        category_id = data.get("category_id")
        if not category_id:
            await message.answer("Категория не найдена. Начните заново.")
            return

        keywords = [{"phrase": p, "volume": 0, "cpc": 0.0} for p in phrases]
        cats_repo = CategoriesRepository(db)
        await cats_repo.update_keywords(category_id, keywords)

        log.info(
            f"{log_prefix}.keywords_text",
            user_id=user.id,
            category_id=category_id,
            phrase_count=len(phrases),
        )

        await message.answer(f"Сохранено {len(phrases)} фраз.")
        await cfg.show_check_msg(message, state, user, db, redis)

    router.message.register(
        readiness_keywords_text_input,
        fsm.readiness_keywords_products,
        F.text,
    )

    # -----------------------------------------------------------------------
    # Keywords: configure sub-flow (products -> geo -> qty -> confirm -> generate)
    # -----------------------------------------------------------------------

    async def readiness_keywords_city_select(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
    ) -> None:
        """Quick city selection for auto-keywords (UX_PIPELINE SS4a).

        Saves city to project and proceeds to confirm screen.
        """
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        if not callback.data:
            await callback.answer()
            return

        city = callback.data.split(":")[-1]
        data = await state.get_data()
        kw_mode = data.get("kw_mode", "")
        products = data.get("kw_products", "")
        project_id = data.get("project_id")

        # Save city to project for future use
        if project_id:
            from db.models import ProjectUpdate

            projects_repo = ProjectsRepository(db)
            await projects_repo.update(project_id, ProjectUpdate(company_city=city))

        if kw_mode == "auto":
            # Auto path: city selected -> go straight to confirm (100 phrases)
            quantity = 100
            cost = estimate_keywords_cost(quantity)

            settings = get_settings()
            token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
            balance = await token_svc.get_balance(user.id)

            await state.set_state(fsm.readiness_keywords_qty)
            await state.update_data(
                kw_geography=city,
                kw_quantity=quantity,
                kw_cost=cost,
            )

            await callback.message.edit_text(
                f"Автоподбор ключевых фраз\n\n"
                f"Тема: {html.escape(products)}\n"
                f"География: {html.escape(city)}\n"
                f"Количество: {quantity} фраз\n\n"
                f"Стоимость: {cost} ток. Баланс: {balance}.",
                reply_markup=pipeline_keywords_confirm_kb(cost, balance, prefix=prefix),
            )
        else:
            # Configure path: city selected -> go to qty selection
            await state.set_state(fsm.readiness_keywords_qty)
            await state.update_data(kw_geography=city)

            await callback.message.edit_text(
                "Сколько ключевых фраз подобрать?",
                reply_markup=pipeline_keywords_qty_kb(prefix=prefix),
            )

        await callback.answer()

    router.callback_query.register(
        readiness_keywords_city_select,
        fsm.readiness_keywords_geo,
        F.data.startswith(f"{prefix}:keywords:city:"),
    )

    async def readiness_keywords_geo_input(
        message: Message,
        state: FSMContext,
    ) -> None:
        """Geography text input for configure keyword path (2-200 chars)."""
        text = (message.text or "").strip()
        if len(text) < 2 or len(text) > 200:
            await message.answer(
                "Введите от 2 до 200 символов.",
                reply_markup=pipeline_back_to_checklist_kb(prefix=prefix),
            )
            return

        await state.set_state(fsm.readiness_keywords_qty)
        await state.update_data(kw_geography=text)

        await message.answer(
            "Сколько ключевых фраз подобрать?",
            reply_markup=pipeline_keywords_qty_kb(prefix=prefix),
        )

    router.message.register(
        readiness_keywords_geo_input,
        fsm.readiness_keywords_geo,
        F.text,
    )

    async def readiness_keywords_qty_select(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
    ) -> None:
        """Select keyword quantity and show cost confirmation."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        if not callback.data:
            await callback.answer()
            return

        try:
            quantity = int(callback.data.split("_")[-1])
        except ValueError:
            await callback.answer()
            return

        if quantity not in (50, 100, 150, 200):
            await callback.answer("Недопустимое количество.", show_alert=True)
            return

        cost = estimate_keywords_cost(quantity)

        settings = get_settings()
        token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
        balance = await token_svc.get_balance(user.id)

        data = await state.get_data()
        products = data.get("kw_products", "")
        geography = data.get("kw_geography", "")

        await state.update_data(kw_quantity=quantity, kw_cost=cost)

        await callback.message.edit_text(
            f"Подбор ключевых фраз\n\n"
            f"Тема: {html.escape(products)}\n"
            f"География: {html.escape(geography)}\n"
            f"Количество: {quantity} фраз\n\n"
            f"Стоимость: {cost} ток. Баланс: {balance}.",
            reply_markup=pipeline_keywords_confirm_kb(cost, balance, prefix=prefix),
        )
        await callback.answer()

    router.callback_query.register(
        readiness_keywords_qty_select,
        fsm.readiness_keywords_qty,
        F.data.regexp(qty_pattern),
    )

    async def readiness_keywords_confirm(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
        ai_orchestrator: AIOrchestrator,
        dataforseo_client: DataForSEOClient,
    ) -> None:
        """Confirm keyword generation: E01 balance check -> charge -> run pipeline."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        data = await state.get_data()
        cost = int(data.get("kw_cost", 0))
        quantity = int(data.get("kw_quantity", 100))
        products = str(data.get("kw_products", ""))
        geography = str(data.get("kw_geography", ""))
        category_id = data.get("category_id")
        project_id = data.get("project_id")

        if not category_id or not project_id or not cost:
            await callback.answer("Данные не найдены. Начните заново.", show_alert=True)
            return

        settings = get_settings()
        token_svc = TokenService(db=db, admin_ids=settings.admin_ids)

        # E01: balance check
        has_balance = await token_svc.check_balance(user.id, cost)
        if not has_balance:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                token_svc.format_insufficient_msg(cost, balance),
                show_alert=True,
            )
            return

        # Charge tokens
        await token_svc.charge(
            user_id=user.id,
            amount=cost,
            operation_type="keywords",
            description=f"Подбор ключевых фраз ({quantity} шт., {cfg.charge_suffix})",
        )

        await state.set_state(fsm.readiness_keywords_generating)
        await callback.message.edit_text("Получаю реальные фразы из DataForSEO...")
        await callback.answer()

        await run_keyword_generation(
            callback=callback,
            state=state,
            user=user,
            db=db,
            redis=redis,
            category_id=category_id,
            project_id=project_id,
            products=products,
            geography=geography,
            quantity=quantity,
            cost=cost,
            token_service=token_svc,
            ai_orchestrator=ai_orchestrator,
            dataforseo_client=dataforseo_client,
            log_prefix=log_prefix,
            readiness_state=fsm.readiness_check,
            back_kb_prefix=prefix,
            on_success=cfg.show_check_msg,
        )

    router.callback_query.register(
        readiness_keywords_confirm,
        fsm.readiness_keywords_qty,
        F.data == f"{prefix}:keywords:confirm",
    )

    async def readiness_keywords_cancel(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Cancel keyword generation -- return to readiness checklist."""
        await cfg.show_check(callback, state, user, db, redis)
        await callback.answer()

    router.callback_query.register(
        readiness_keywords_cancel,
        StateFilter(
            fsm.readiness_keywords_geo,
            fsm.readiness_keywords_qty,
        ),
        F.data == f"{prefix}:keywords:cancel",
    )

    # -----------------------------------------------------------------------
    # Description sub-flow
    # -----------------------------------------------------------------------

    async def readiness_description_menu(callback: CallbackQuery) -> None:
        """Show description options."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        await callback.message.edit_text(
            "Описание компании/категории\n\nAI напишет точнее с контекстом о вашей компании.",
            reply_markup=pipeline_description_options_kb(prefix=prefix),
        )
        await callback.answer()

    router.callback_query.register(
        readiness_description_menu,
        fsm.readiness_check,
        F.data == f"{prefix}:description",
    )

    async def readiness_description_ai(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
        ai_orchestrator: AIOrchestrator,
    ) -> None:
        """Generate category description via AI (delegates to generate_description_ai)."""
        await generate_description_ai(
            callback=callback,
            state=state,
            user=user,
            db=db,
            redis=redis,
            ai_orchestrator=ai_orchestrator,
            log_prefix=log_prefix,
            on_success=cfg.show_check,
        )

    router.callback_query.register(
        readiness_description_ai,
        fsm.readiness_check,
        F.data == f"{prefix}:description:ai",
    )

    async def readiness_description_manual_start(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        """Start manual description input."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        await callback.message.edit_text(
            f"Введите описание компании/категории (10-2000 символов).\n\n"
            f"Чем подробнее -- тем точнее будут {cfg.description_hint}.",
            reply_markup=pipeline_back_to_checklist_kb(prefix=prefix),
        )
        await state.set_state(fsm.readiness_description)
        await callback.answer()

    router.callback_query.register(
        readiness_description_manual_start,
        fsm.readiness_check,
        F.data == f"{prefix}:description:manual",
    )

    async def readiness_description_manual_input(
        message: Message,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Save manually entered description."""
        text = (message.text or "").strip()
        if len(text) < 10 or len(text) > 2000:
            await message.answer(
                "Описание: от 10 до 2000 символов.",
                reply_markup=cancel_kb(cancel_cb),
            )
            return

        data = await state.get_data()
        category_id = data.get("category_id")
        if not category_id:
            await message.answer("Категория не найдена. Начните заново.")
            return

        cats_repo = CategoriesRepository(db)
        await cats_repo.update(category_id, CategoryUpdate(description=text))

        log.info(
            f"{log_prefix}.description_manual",
            user_id=user.id,
            category_id=category_id,
        )

        await message.answer("Описание сохранено.")
        await cfg.show_check_msg(message, state, user, db, redis)

    router.message.register(
        readiness_description_manual_input,
        fsm.readiness_description,
        F.text,
    )

    # -----------------------------------------------------------------------
    # Navigation: back to checklist, done
    # -----------------------------------------------------------------------

    # Collect all states that need "back to checklist" from text-input sub-flows
    back_input_states = [
        fsm.readiness_keywords_products,
        fsm.readiness_keywords_geo,
        fsm.readiness_keywords_qty,
        fsm.readiness_description,
        *cfg.extra_back_states,
    ]

    async def readiness_back_from_input(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Return to readiness checklist from text-input sub-flows (M5)."""
        await cfg.show_check(callback, state, user, db, redis)
        await callback.answer()

    router.callback_query.register(
        readiness_back_from_input,
        StateFilter(*back_input_states),
        F.data == f"{prefix}:back",
    )

    async def readiness_back(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Return to readiness checklist from any sub-flow options screen."""
        await cfg.show_check(callback, state, user, db, redis)
        await callback.answer()

    router.callback_query.register(
        readiness_back,
        fsm.readiness_check,
        F.data == f"{prefix}:back",
    )

    # Note: readiness_done is NOT registered here because it differs between
    # article and social pipelines (article checks image_count, social passes
    # pipeline_type="social"). Each pipeline registers its own done handler.

    # Return handler functions for test imports
    return {
        "readiness_keywords_menu": readiness_keywords_menu,
        "readiness_keywords_auto": readiness_keywords_auto,
        "readiness_keywords_configure": readiness_keywords_configure,
        "readiness_keywords_upload_start": readiness_keywords_upload_start,
        "readiness_keywords_upload_file": readiness_keywords_upload_file,
        "readiness_keywords_text_input": readiness_keywords_text_input,
        "_handle_configure_products": _handle_configure_products,
        "readiness_keywords_city_select": readiness_keywords_city_select,
        "readiness_keywords_geo_input": readiness_keywords_geo_input,
        "readiness_keywords_qty_select": readiness_keywords_qty_select,
        "readiness_keywords_confirm": readiness_keywords_confirm,
        "readiness_keywords_cancel": readiness_keywords_cancel,
        "readiness_description_menu": readiness_description_menu,
        "readiness_description_ai": readiness_description_ai,
        "readiness_description_manual_start": readiness_description_manual_start,
        "readiness_description_manual_input": readiness_description_manual_input,
        "readiness_back_from_input": readiness_back_from_input,
        "readiness_back": readiness_back,
    }
