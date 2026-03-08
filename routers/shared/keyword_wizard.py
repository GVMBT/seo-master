"""Unified keyword generation/upload wizard shared between Pipeline and Toolbox.

Extracted from routers/publishing/pipeline/_readiness_common.py (keyword sub-flow)
and routers/categories/keywords.py (sections 3-7) to eliminate duplication.

Keywords are FREE everywhere -- no token charging.
"""

from __future__ import annotations

import asyncio
import contextlib
import html
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.helpers import safe_edit_text, safe_message
from db.models import User
from keyboards.inline import cancel_kb, menu_kb
from services.categories import CategoryService
from services.keywords import KeywordService

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext

    from bot.service_factory import CategoryServiceFactory, ProjectServiceFactory
    from cache.client import RedisClient
    from db.client import SupabaseClient
    from services.ai.orchestrator import AIOrchestrator
    from services.external.dataforseo import DataForSEOClient

log = structlog.get_logger()

# Limits for keyword upload (shared between all callers)
MAX_KEYWORD_PHRASES = 500
MAX_KEYWORD_FILE_SIZE = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# Type aliases (re-exported from _readiness_common for compatibility)
# ---------------------------------------------------------------------------

ShowCheckCb = Callable[
    [CallbackQuery, "FSMContext", User, "SupabaseClient", "RedisClient"],
    Awaitable[None],
]
ShowCheckMsgCb = Callable[
    [Message, "FSMContext", User, "SupabaseClient", "RedisClient"],
    Awaitable[None],
]


# ---------------------------------------------------------------------------
# KeywordWizardConfig
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeywordWizardConfig:
    """Configuration for the unified keyword wizard.

    Parameterizes differences between Pipeline readiness sub-flow
    and Toolbox keyword generation/upload.
    """

    state_products: State
    """FSM state for waiting for products text / upload file."""

    state_geo: State
    """FSM state for waiting for geography text."""

    state_qty: State
    """FSM state for quantity selection + confirm."""

    state_generating: State
    """FSM state during generation progress."""

    prefix: str
    """Callback prefix: 'pipeline:readiness' or 'kw'."""

    log_prefix: str
    """Structlog event prefix."""

    cancel_cb_fn: Callable[[dict[str, Any]], str]
    """Dynamic cancel callback_data builder -- reads cat_id from FSM data."""

    on_done: ShowCheckCb
    """Return callback after wizard completes (callback sub-flows)."""

    on_done_msg: ShowCheckMsgCb
    """Return callback after wizard completes (message sub-flows)."""

    qty_kb_fn: Callable[[dict[str, Any]], InlineKeyboardMarkup]
    """Quantity selection keyboard builder (receives FSM data dict)."""

    confirm_kb_fn: Callable[[dict[str, Any]], InlineKeyboardMarkup]
    """Confirm generation keyboard builder (receives FSM data dict)."""

    cancel_nav_kb_fn: Callable[[dict[str, Any]], InlineKeyboardMarkup]
    """Cancel/back navigation keyboard for text input prompts."""

    error_state: State | None = None
    """FSM state to set on generation failure (None -> clear state)."""

    error_kb_fn: Callable[[dict[str, Any]], InlineKeyboardMarkup] | None = None
    """Error keyboard builder (receives FSM data dict). None -> no keyboard."""

    auto_mode: bool = False
    """Pipeline-only: auto-generate from category.name (enables city select)."""

    saved_answers: bool = False
    """Toolbox-only: persist kw_products_{cat_id}/kw_geography_{cat_id} in FSM data."""

    upload_enriches: bool = True
    """Toolbox: cluster+enrich uploaded phrases. Pipeline: save as flat keywords."""


# ---------------------------------------------------------------------------
# Core generation pipeline
# ---------------------------------------------------------------------------


async def run_keyword_generation(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    *,
    cfg: KeywordWizardConfig,
    category_id: int,
    project_id: int,
    products: str,
    geography: str,
    quantity: int,
    ai_orchestrator: AIOrchestrator,
    dataforseo_client: DataForSEOClient,
) -> None:
    """Run keyword pipeline: fetch -> cluster -> enrich -> save.

    AI clustering (DeepSeek) can take 60-90 seconds. Progress updates use
    _safe_edit (tolerates Telegram errors) and the final result is sent
    as a NEW message.
    """
    log_prefix = cfg.log_prefix
    msg = safe_message(callback)
    if not msg:
        return

    async def _safe_edit(text: str) -> None:
        """Edit message, silently ignoring Telegram errors."""
        try:
            await safe_edit_text(msg, text)
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

        # Save (MERGE with existing) via CategoryService
        cat_svc = CategoryService(db=db)
        category = await cat_svc.get_owned_category(category_id, user.id)
        if not category:
            raise RuntimeError("keywords_save_failed.ownership")
        existing: list[dict[str, Any]] = category.keywords or []
        merged = existing + enriched
        saved = await cat_svc.update_keywords(category_id, user.id, merged)
        if not saved:
            raise RuntimeError("keywords_save_failed.update")

        total_phrases = sum(len(c.get("phrases", [])) for c in enriched)
        total_volume = sum(c.get("total_volume", 0) for c in enriched)

        log.info(
            f"{log_prefix}.keywords_generated",
            user_id=user.id,
            category_id=category_id,
            clusters=len(enriched),
            phrases=total_phrases,
        )

    except Exception:
        log.exception(
            f"{log_prefix}.keywords_failed",
            user_id=user.id,
            category_id=category_id,
        )
        # Send error as new message (original may be expired)
        with contextlib.suppress(Exception):
            await msg.delete()
        bot = msg.bot
        if not bot:
            return

        fsm_data = await state.get_data()
        error_kb = cfg.error_kb_fn(fsm_data) if cfg.error_kb_fn else None
        await bot.send_message(
            chat_id=msg.chat.id,
            text="Ошибка при подборе фраз. Попробуйте позже.",
            reply_markup=error_kb,
        )
        if cfg.error_state is not None:
            await state.set_state(cfg.error_state)
        else:
            await state.clear()
        return

    # Build quality warning (toolbox feature)
    quality_note = ""
    if total_volume < 100:
        quality_note = (
            "\n\nНизкий объём поиска по этой нише -- фразы могут быть "
            "менее надёжными. Попробуйте более конкретные товары/услуги."
        )

    # Post-success UI
    try:
        await msg.delete()
    except Exception:
        log.debug(f"{log_prefix}.delete_progress_failed")

    bot = msg.bot
    if not bot:
        return
    with contextlib.suppress(Exception):
        await bot.send_message(
            chat_id=msg.chat.id,
            text=(
                f"Готово! Добавлено:\n"
                f"Кластеров: {len(enriched)}\n"
                f"Фраз: {total_phrases}\n"
                f"Общий объём: {total_volume:,}/мес{quality_note}"
            ),
        )
    await asyncio.sleep(1)
    with contextlib.suppress(Exception):
        await cfg.on_done_msg(msg, state, user, db, redis)


# ---------------------------------------------------------------------------
# Upload pipeline (cluster + enrich) for toolbox mode
# ---------------------------------------------------------------------------


async def _run_upload_enrich_pipeline(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    *,
    cfg: KeywordWizardConfig,
    cat_id: int,
    project_id: int,
    raw_phrases: list[dict[str, Any]],
    ai_orchestrator: AIOrchestrator,
    dataforseo_client: DataForSEOClient,
) -> None:
    """Upload pipeline: cluster -> enrich -> save (no charge -- upload is free)."""
    log_prefix = cfg.log_prefix

    try:
        kw_service = KeywordService(
            orchestrator=ai_orchestrator,
            dataforseo=dataforseo_client,
            db=db,
        )

        # Step 1: Cluster
        progress_msg = await msg.answer(f"Загружено {len(raw_phrases)} фраз. Группирую по интенту...")

        clusters = await kw_service.cluster_phrases(
            raw_phrases=raw_phrases,
            products="",
            geography="",
            quantity=len(raw_phrases),
            project_id=project_id,
            user_id=user.id,
        )

        # Step 2: Enrich
        await safe_edit_text(progress_msg, f"Создано {len(clusters)} кластеров. Обогащаю данными...")

        enriched = await kw_service.enrich_clusters(clusters)

        # Save (MERGE with existing)
        cat_svc = CategoryService(db=db)
        category = await cat_svc.get_owned_category(cat_id, user.id)
        existing: list[dict[str, Any]] = (category.keywords if category else []) or []
        merged = existing + enriched
        if category:
            await cat_svc.update_keywords(cat_id, user.id, merged)

        total_phrases = sum(len(c.get("phrases", [])) for c in enriched)
        total_volume = sum(c.get("total_volume", 0) for c in enriched)

        await safe_edit_text(
            progress_msg,
            f"Готово! Загружено:\nКластеров: {len(enriched)}\nФраз: {total_phrases}\nОбщий объём: {total_volume:,}/мес",
        )
        # Clear FSM state but preserve saved answers if configured
        if cfg.saved_answers:
            await state.set_state(None)
        else:
            await state.clear()

        log.info(
            f"{log_prefix}.keywords_uploaded",
            cat_id=cat_id,
            user_id=user.id,
            clusters=len(enriched),
        )

    except Exception:
        log.exception(f"{log_prefix}.upload_pipeline_failed", cat_id=cat_id, user_id=user.id)
        await state.clear()
        fsm_data = await state.get_data()
        error_kb = cfg.error_kb_fn(fsm_data) if cfg.error_kb_fn else None
        await msg.answer(
            "Ошибка при обработке файла. Попробуйте позже.",
            reply_markup=error_kb,
        )


# ---------------------------------------------------------------------------
# Handler factory
# ---------------------------------------------------------------------------


def register_keyword_wizard(router: Router, cfg: KeywordWizardConfig) -> dict[str, Any]:  # noqa: C901
    """Register keyword wizard handlers on the given router.

    Handles: products text/upload, geo text/city select, qty select,
    confirm, cancel. Entry points (menu, auto, configure, upload_start)
    are NOT registered here -- they stay in the caller module.

    Returns a dict mapping handler names to functions (for test imports).

    Note: C901 complexity is expected -- factory registering 7+ handlers.
    """
    prefix = cfg.prefix
    log_prefix = cfg.log_prefix

    # -----------------------------------------------------------------------
    # Products text input (routes by kw_mode: "configure" or "upload")
    # -----------------------------------------------------------------------

    async def wizard_products_text(
        message: Message,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
        category_service_factory: CategoryServiceFactory,
    ) -> None:
        """Handle text input -- route by kw_mode (configure=products, upload=phrases)."""
        data = await state.get_data()
        kw_mode = data.get("kw_mode", "upload")

        if kw_mode == "configure":
            # Validate products (3-1000 chars)
            text = (message.text or "").strip()
            if len(text) < 3 or len(text) > 1000:
                cancel_cb = cfg.cancel_cb_fn(data)
                await message.answer(
                    "Введите от 3 до 1000 символов.",
                    reply_markup=cfg.cancel_nav_kb_fn(data),
                )
                return

            await state.set_state(cfg.state_geo)
            prod_update: dict[str, Any] = {"kw_products": text}
            if cfg.saved_answers:
                cat_id = data.get("kw_cat_id", 0)
                prod_update[f"kw_products_{cat_id}"] = text
            await state.update_data(**prod_update)

            await message.answer(
                "Укажите географию продвижения:\n<i>Например: Москва, Россия, СНГ</i>\n\nОт 2 до 200 символов.",
                reply_markup=cfg.cancel_nav_kb_fn(data),
            )
            return

        # Upload mode: process text as keyword phrases (one per line)
        text = (message.text or "").strip()
        cancel_cb = cfg.cancel_cb_fn(data)
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

        category_id = data.get("category_id") or data.get("kw_cat_id")
        if not category_id:
            await message.answer("Категория не найдена. Начните заново.", reply_markup=menu_kb())
            return

        keywords = [{"phrase": p, "volume": 0, "cpc": 0.0} for p in phrases]
        cat_svc = category_service_factory(db)
        saved = await cat_svc.update_keywords(int(category_id), user.id, keywords)
        if not saved:
            log.error(f"{log_prefix}.keywords_text_failed", category_id=category_id, user_id=user.id)
            await message.answer("Не удалось сохранить фразы. Попробуйте снова.")
            return

        log.info(
            f"{log_prefix}.keywords_text",
            user_id=user.id,
            category_id=category_id,
            phrase_count=len(phrases),
        )

        await message.answer(f"Сохранено {len(phrases)} фраз.")
        await cfg.on_done_msg(message, state, user, db, redis)

    router.message.register(
        wizard_products_text,
        cfg.state_products,
        F.text,
    )

    # -----------------------------------------------------------------------
    # Upload file handler
    # -----------------------------------------------------------------------

    async def wizard_upload_file(
        message: Message,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
        category_service_factory: CategoryServiceFactory,
        ai_orchestrator: AIOrchestrator | None = None,
        dataforseo_client: DataForSEOClient | None = None,
    ) -> None:
        """Process uploaded TXT file with keyword phrases."""
        doc = message.document
        if not doc:
            await message.answer("Файл не найден.")
            return

        data = await state.get_data()
        cancel_cb = cfg.cancel_cb_fn(data)

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

        category_id = data.get("category_id") or data.get("kw_cat_id")
        if not category_id:
            await message.answer("Категория не найдена. Начните заново.", reply_markup=menu_kb())
            return

        cat_id = int(category_id)
        project_id = int(data.get("project_id") or data.get("kw_project_id") or 0)

        if cfg.upload_enriches:
            # Toolbox mode: cluster + enrich pipeline
            if not ai_orchestrator or not dataforseo_client:
                log.error(f"{log_prefix}.upload_missing_deps", category_id=cat_id)
                await message.answer("Внутренняя ошибка. Попробуйте позже.")
                return
            raw = [{"phrase": p, "volume": 0, "cpc": 0.0, "ai_suggested": False} for p in phrases]
            await _run_upload_enrich_pipeline(
                message,
                state,
                user,
                db,
                cfg=cfg,
                cat_id=cat_id,
                project_id=project_id,
                raw_phrases=raw,
                ai_orchestrator=ai_orchestrator,
                dataforseo_client=dataforseo_client,
            )
        else:
            # Pipeline mode: save as flat keywords
            keywords = [{"phrase": p, "volume": 0, "cpc": 0.0} for p in phrases]
            cat_svc = category_service_factory(db)
            saved = await cat_svc.update_keywords(cat_id, user.id, keywords)
            if not saved:
                log.error(f"{log_prefix}.keywords_upload_failed", category_id=cat_id, user_id=user.id)
                await message.answer("Не удалось сохранить фразы. Попробуйте снова.")
                return

            log.info(
                f"{log_prefix}.keywords_uploaded",
                user_id=user.id,
                category_id=cat_id,
                phrase_count=len(phrases),
            )

            await message.answer(f"Загружено {len(phrases)} фраз.")
            await cfg.on_done_msg(message, state, user, db, redis)

    router.message.register(
        wizard_upload_file,
        cfg.state_products,
        F.document,
    )

    # -----------------------------------------------------------------------
    # Geography text input
    # -----------------------------------------------------------------------

    async def wizard_geo_input(
        message: Message,
        state: FSMContext,
    ) -> None:
        """Geography text input (2-200 chars)."""
        text = (message.text or "").strip()
        data = await state.get_data()
        if len(text) < 2 or len(text) > 200:
            await message.answer(
                "Введите от 2 до 200 символов.",
                reply_markup=cfg.cancel_nav_kb_fn(data),
            )
            return

        await state.set_state(cfg.state_qty)
        geo_update: dict[str, Any] = {"kw_geography": text}
        if cfg.saved_answers:
            cat_id = data.get("kw_cat_id", 0)
            geo_update[f"kw_geography_{cat_id}"] = text
        await state.update_data(**geo_update)

        new_data = await state.get_data()
        await message.answer(
            "Сколько ключевых фраз подобрать?",
            reply_markup=cfg.qty_kb_fn(new_data),
        )

    router.message.register(
        wizard_geo_input,
        cfg.state_geo,
        F.text,
    )

    # -----------------------------------------------------------------------
    # City select (pipeline auto_mode only)
    # -----------------------------------------------------------------------

    if cfg.auto_mode:
        async def wizard_city_select(
            callback: CallbackQuery,
            state: FSMContext,
            user: User,
            db: SupabaseClient,
            project_service_factory: ProjectServiceFactory,
        ) -> None:
            """Quick city selection for auto-keywords (UX_PIPELINE SS4a)."""
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

                proj_svc = project_service_factory(db)
                await proj_svc.update_project(project_id, user.id, ProjectUpdate(company_city=city))

            if kw_mode == "auto":
                # Auto path: city selected -> go straight to confirm (100 phrases)
                quantity = 100

                await state.set_state(cfg.state_qty)
                await state.update_data(
                    kw_geography=city,
                    kw_quantity=quantity,
                )

                new_data = await state.get_data()
                await safe_edit_text(
                    msg,
                    f"Автоподбор ключевых фраз\n\n"
                    f"Тема: {html.escape(products)}\n"
                    f"География: {html.escape(city)}\n"
                    f"Количество: {quantity} фраз",
                    reply_markup=cfg.confirm_kb_fn(new_data),
                )
            else:
                # Configure path: city selected -> go to qty selection
                await state.set_state(cfg.state_qty)
                await state.update_data(kw_geography=city)

                new_data = await state.get_data()
                await safe_edit_text(
                    msg,
                    "Сколько ключевых фраз подобрать?",
                    reply_markup=cfg.qty_kb_fn(new_data),
                )

            await callback.answer()

        router.callback_query.register(
            wizard_city_select,
            cfg.state_geo,
            F.data.startswith(f"{prefix}:keywords:city:"),
        )

    # -----------------------------------------------------------------------
    # Quantity select
    # -----------------------------------------------------------------------

    # Pattern matches both "pipeline:readiness:keywords:qty_100" and "kw:5:qty_100"
    # State guard prevents false matches.
    prefix_escaped = re.escape(prefix)
    qty_pattern = rf"^{prefix_escaped}.*qty_(\d+)$"

    async def wizard_qty_select(
        callback: CallbackQuery,
        state: FSMContext,
    ) -> None:
        """Select keyword quantity and show confirmation."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        if not callback.data:
            await callback.answer()
            return

        # Extract quantity from callback_data (last segment: qty_N)
        match = re.search(r"qty_(\d+)", callback.data)
        if not match:
            await callback.answer()
            return

        quantity = int(match.group(1))
        if quantity not in (50, 100, 150, 200):
            await callback.answer("Недопустимое количество.", show_alert=True)
            return

        data = await state.get_data()
        products = data.get("kw_products", "")
        geography = data.get("kw_geography", "")

        await state.update_data(kw_quantity=quantity)
        new_data = await state.get_data()

        await safe_edit_text(
            msg,
            f"Подбор ключевых фраз\n\n"
            f"Тема: {html.escape(products)}\n"
            f"География: {html.escape(geography)}\n"
            f"Количество: {quantity} фраз",
            reply_markup=cfg.confirm_kb_fn(new_data),
        )
        await callback.answer()

    router.callback_query.register(
        wizard_qty_select,
        cfg.state_qty,
        F.data.regexp(qty_pattern),
    )

    # -----------------------------------------------------------------------
    # Confirm generation
    # -----------------------------------------------------------------------

    # Matches both ":confirm" and ":confirm_yes" under state guard
    confirm_pattern = rf"^{prefix_escaped}.*(?:confirm|confirm_yes)$"

    async def wizard_confirm(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
        ai_orchestrator: AIOrchestrator,
        dataforseo_client: DataForSEOClient,
    ) -> None:
        """Confirm keyword generation (free for user -- platform expense)."""
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return

        data = await state.get_data()
        quantity = int(data.get("kw_quantity", 100))
        products = str(data.get("kw_products", ""))
        geography = str(data.get("kw_geography", ""))
        category_id = data.get("category_id") or data.get("kw_cat_id")
        project_id = data.get("project_id") or data.get("kw_project_id")

        if not category_id or not project_id:
            await callback.answer("Данные не найдены. Начните заново.", show_alert=True)
            return

        # Save answers for future reuse (toolbox mode)
        if cfg.saved_answers:
            cat_id = int(category_id)
            await state.update_data({
                f"kw_products_{cat_id}": products,
                f"kw_geography_{cat_id}": geography,
            })

        await state.set_state(cfg.state_generating)
        await safe_edit_text(msg, "Получаю реальные фразы из DataForSEO...")
        await callback.answer()

        await run_keyword_generation(
            callback=callback,
            state=state,
            user=user,
            db=db,
            redis=redis,
            cfg=cfg,
            category_id=int(category_id),
            project_id=int(project_id),
            products=products,
            geography=geography,
            quantity=quantity,
            ai_orchestrator=ai_orchestrator,
            dataforseo_client=dataforseo_client,
        )

    router.callback_query.register(
        wizard_confirm,
        cfg.state_qty,
        F.data.regexp(confirm_pattern),
    )

    # -----------------------------------------------------------------------
    # Cancel (from geo or qty states)
    # -----------------------------------------------------------------------

    # Matches cancel callbacks under state guard
    cancel_pattern = rf"^{prefix_escaped}.*(?:cancel|gen_cancel|confirm_no)$"

    async def wizard_cancel(
        callback: CallbackQuery,
        state: FSMContext,
        user: User,
        db: SupabaseClient,
        redis: RedisClient,
    ) -> None:
        """Cancel keyword wizard -- return to caller screen."""
        await cfg.on_done(callback, state, user, db, redis)
        await callback.answer()

    router.callback_query.register(
        wizard_cancel,
        StateFilter(cfg.state_geo, cfg.state_qty),
        F.data.regexp(cancel_pattern),
    )

    # Build and return handlers dict
    handlers: dict[str, Any] = {
        "wizard_products_text": wizard_products_text,
        "wizard_upload_file": wizard_upload_file,
        "wizard_geo_input": wizard_geo_input,
        "wizard_qty_select": wizard_qty_select,
        "wizard_confirm": wizard_confirm,
        "wizard_cancel": wizard_cancel,
    }
    if cfg.auto_mode:
        handlers["wizard_city_select"] = wizard_city_select  # type: ignore[possibly-undefined]

    return handlers
