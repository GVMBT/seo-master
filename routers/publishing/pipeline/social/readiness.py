"""Social Pipeline readiness check — step 4 (F6.3).

Simplified readiness for social posts: keywords + description only (no prices/images).
Sub-flows: keywords (auto/configure/upload), description (AI/manual).

UX: UX_PIPELINE.md §5.4 (social readiness).
FSM: SocialPipelineFSM (28 states, FSM_SPEC.md §2.2).
Rules: .claude/rules/pipeline.md — inline handlers, NOT FSM delegation.
"""

from __future__ import annotations

import html
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.helpers import safe_message
from cache.client import RedisClient
from db.client import SupabaseClient
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
    social_readiness_kb,
)
from routers.publishing.pipeline._common import (
    SocialPipelineFSM,
    clear_checkpoint,
    save_checkpoint,
)
from services.ai.orchestrator import AIOrchestrator
from services.external.dataforseo import DataForSEOClient
from services.readiness import ReadinessReport, ReadinessService
from services.tokens import (
    TokenService,
    estimate_keywords_cost,
)

log = structlog.get_logger()
router = Router()

# Limits for keyword upload (mirrors categories/keywords.py)
_MAX_KEYWORD_PHRASES = 500
_MAX_KEYWORD_FILE_SIZE = 1 * 1024 * 1024  # 1 MB

# Callback prefix for social readiness sub-flows
_PREFIX = "pipeline:social:readiness"

# Total step count for social pipeline (displayed in step headers)
_TOTAL_STEPS = 5


# ---------------------------------------------------------------------------
# Checklist display helpers
# ---------------------------------------------------------------------------


def _build_social_checklist_text(report: ReadinessReport, fsm_data: dict[str, Any]) -> str:
    """Build social readiness checklist text (UX_PIPELINE.md §5.4).

    Simplified vs article: only keywords + description, no prices/images.
    """
    project_name = html.escape(fsm_data.get("project_name", ""))
    category_name = html.escape(fsm_data.get("category_name", ""))
    platform_type = fsm_data.get("platform_type", "")
    identifier = html.escape(fsm_data.get("connection_identifier", ""))

    platform_labels = {
        "telegram": "Телеграм",
        "vk": "ВКонтакте",
        "pinterest": "Пинтерест",
    }
    platform_label = platform_labels.get(platform_type, platform_type)

    lines: list[str] = [
        f"Пост (4/{_TOTAL_STEPS}) -- Подготовка\n",
        f"Проект: {project_name}",
        f"Платформа: {platform_label} ({identifier})",
        f"Тема: {category_name}\n",
    ]

    # Keywords status
    if report.has_keywords:
        kw_info = f"{report.keyword_count} фраз"
        if report.cluster_count:
            kw_info = f"{report.cluster_count} кластеров ({report.keyword_count} фраз)"
        lines.append(f"Ключевые фразы -- {kw_info}")
    else:
        lines.append("Ключевые фразы -- не заполнены (обязательно)")

    # Description status
    if report.has_description:
        lines.append("Описание -- заполнено")
    else:
        lines.append("Описание -- не заполнено")

    # Cost estimate
    lines.append(f"\nОриентировочная стоимость: ~{report.estimated_cost} ток.")

    return "\n".join(lines)


async def show_social_readiness_check(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    *,
    force_show: bool = False,
) -> None:
    """Render social readiness checklist (step 4) or skip to step 5 if all filled.

    Called from social.py after category selection, and after each sub-flow completes.
    When force_show=True (e.g. "back to checklist" from confirm), always show checklist.
    """
    if not safe_message(callback):
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    connection_id = data.get("connection_id")
    if not category_id:
        await callback.message.edit_text("Категория не выбрана. Начните заново.")
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, pipeline_type="social")

    # Skip to step 5 if all required items filled (unless forced back)
    if not force_show and report.all_filled and not report.missing_items:
        from routers.publishing.pipeline.social.generation import show_social_confirm

        await show_social_confirm(callback, state, user, db, redis, report, data)
        return

    text = _build_social_checklist_text(report, data)
    kb = social_readiness_kb(report)
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(SocialPipelineFSM.readiness_check)
    await save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
        connection_id=connection_id,
    )


async def show_social_readiness_check_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Render social readiness checklist via new message (after text/file input sub-flows)."""
    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    connection_id = data.get("connection_id")
    if not category_id:
        await message.answer("Категория не выбрана. Начните заново.")
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, pipeline_type="social")

    if report.all_filled and not report.missing_items:
        from routers.publishing.pipeline.social.generation import show_social_confirm_msg

        await show_social_confirm_msg(message, state, user, db, redis, report, data)
        return

    text = _build_social_checklist_text(report, data)
    kb = social_readiness_kb(report)
    await message.answer(text, reply_markup=kb)
    await state.set_state(SocialPipelineFSM.readiness_check)
    await save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
        connection_id=connection_id,
    )


# ---------------------------------------------------------------------------
# Keywords sub-flow
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:keywords",
)
async def social_readiness_keywords_menu(callback: CallbackQuery) -> None:
    """Show keyword generation options."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await callback.message.edit_text(
        "Ключевые фразы\n\nВыберите способ добавления:",
        reply_markup=pipeline_keywords_options_kb(prefix=_PREFIX),
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:keywords:auto",
)
async def social_readiness_keywords_auto(
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

    # UX_PIPELINE §4a: if no company_city -- ask city first
    if not geography:
        await state.set_state(SocialPipelineFSM.readiness_keywords_geo)
        await state.update_data(kw_products=products, kw_mode="auto")

        await callback.message.edit_text(
            "В каком городе ваш бизнес?\n<i>Для точных SEO-фраз</i>",
            reply_markup=pipeline_keywords_city_kb(prefix=_PREFIX),
        )
        await callback.answer()
        return

    quantity = 100
    cost = estimate_keywords_cost(quantity)

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    await state.set_state(SocialPipelineFSM.readiness_keywords_qty)
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
        reply_markup=pipeline_keywords_confirm_kb(cost, balance, prefix=_PREFIX),
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:keywords:configure",
)
async def social_readiness_keywords_configure(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Configure keyword generation -- full path (products -> geo -> qty -> confirm)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.set_state(SocialPipelineFSM.readiness_keywords_products)
    await state.update_data(kw_mode="configure")

    await callback.message.edit_text(
        "Какие товары или услуги продвигаете?\n"
        "<i>Например: кухни на заказ, шкафы-купе, корпусная мебель</i>\n\n"
        "От 3 до 1000 символов.",
        reply_markup=pipeline_back_to_checklist_kb(prefix=_PREFIX),
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:keywords:upload",
)
async def social_readiness_keywords_upload_start(
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
        reply_markup=pipeline_back_to_checklist_kb(prefix=_PREFIX),
    )
    await state.set_state(SocialPipelineFSM.readiness_keywords_products)
    await state.update_data(kw_mode="upload")
    await callback.answer()


@router.message(SocialPipelineFSM.readiness_keywords_products, F.document)
async def social_readiness_keywords_upload_file(
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
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    if doc.file_size and doc.file_size > _MAX_KEYWORD_FILE_SIZE:
        await message.answer(
            "Файл слишком большой (макс. 1 МБ).",
            reply_markup=cancel_kb("pipeline:social:cancel"),
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
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    if len(phrases) > _MAX_KEYWORD_PHRASES:
        await message.answer(
            f"Максимум {_MAX_KEYWORD_PHRASES} фраз. Сейчас: {len(phrases)}.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
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
        "pipeline.social.readiness.keywords_uploaded",
        user_id=user.id,
        category_id=category_id,
        phrase_count=len(phrases),
    )

    await message.answer(f"Загружено {len(phrases)} фраз.")
    await show_social_readiness_check_msg(message, state, user, db, redis)


@router.message(SocialPipelineFSM.readiness_keywords_products, F.text)
async def social_readiness_keywords_text_input(
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
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    phrases = [line.strip() for line in text.splitlines() if line.strip()]
    if not phrases:
        await message.answer(
            "Не удалось распознать фразы. Каждая фраза -- с новой строки.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    if len(phrases) > _MAX_KEYWORD_PHRASES:
        await message.answer(
            f"Максимум {_MAX_KEYWORD_PHRASES} фраз. Сейчас: {len(phrases)}.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
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
        "pipeline.social.readiness.keywords_text",
        user_id=user.id,
        category_id=category_id,
        phrase_count=len(phrases),
    )

    await message.answer(f"Сохранено {len(phrases)} фраз.")
    await show_social_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Keywords: configure sub-flow (products -> geo -> qty -> confirm -> generate)
# ---------------------------------------------------------------------------


async def _handle_configure_products(message: Message, state: FSMContext) -> None:
    """Validate products input for configure keyword path (3-1000 chars)."""
    text = (message.text or "").strip()
    if len(text) < 3 or len(text) > 1000:
        await message.answer(
            "Введите от 3 до 1000 символов.",
            reply_markup=pipeline_back_to_checklist_kb(prefix=_PREFIX),
        )
        return

    await state.set_state(SocialPipelineFSM.readiness_keywords_geo)
    await state.update_data(kw_products=text)

    await message.answer(
        "Укажите географию продвижения:\n<i>Например: Москва, Россия, СНГ</i>\n\nОт 2 до 200 символов.",
        reply_markup=pipeline_back_to_checklist_kb(prefix=_PREFIX),
    )


@router.callback_query(
    SocialPipelineFSM.readiness_keywords_geo,
    F.data.startswith(f"{_PREFIX}:keywords:city:"),
)
async def social_readiness_keywords_city_select(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Quick city selection for auto-keywords (UX_PIPELINE §4a).

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

        await state.set_state(SocialPipelineFSM.readiness_keywords_qty)
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
            reply_markup=pipeline_keywords_confirm_kb(cost, balance, prefix=_PREFIX),
        )
    else:
        # Configure path: city selected -> go to qty selection
        await state.set_state(SocialPipelineFSM.readiness_keywords_qty)
        await state.update_data(kw_geography=city)

        await callback.message.edit_text(
            "Сколько ключевых фраз подобрать?",
            reply_markup=pipeline_keywords_qty_kb(prefix=_PREFIX),
        )

    await callback.answer()


@router.message(SocialPipelineFSM.readiness_keywords_geo, F.text)
async def social_readiness_keywords_geo_input(
    message: Message,
    state: FSMContext,
) -> None:
    """Geography text input for configure keyword path (2-200 chars)."""
    text = (message.text or "").strip()
    if len(text) < 2 or len(text) > 200:
        await message.answer(
            "Введите от 2 до 200 символов.",
            reply_markup=pipeline_back_to_checklist_kb(prefix=_PREFIX),
        )
        return

    await state.set_state(SocialPipelineFSM.readiness_keywords_qty)
    await state.update_data(kw_geography=text)

    await message.answer(
        "Сколько ключевых фраз подобрать?",
        reply_markup=pipeline_keywords_qty_kb(prefix=_PREFIX),
    )


@router.callback_query(
    SocialPipelineFSM.readiness_keywords_qty,
    F.data.regexp(rf"^{_PREFIX}:keywords:qty_(\d+)$"),
)
async def social_readiness_keywords_qty_select(
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
        reply_markup=pipeline_keywords_confirm_kb(cost, balance, prefix=_PREFIX),
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_keywords_qty,
    F.data == f"{_PREFIX}:keywords:confirm",
)
async def social_readiness_keywords_confirm(
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
        description=f"Подбор ключевых фраз ({quantity} шт., social pipeline)",
    )

    await state.set_state(SocialPipelineFSM.readiness_keywords_generating)
    await callback.message.edit_text("Получаю реальные фразы из DataForSEO...")
    await callback.answer()

    await _run_pipeline_keyword_generation(
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
    )


@router.callback_query(
    StateFilter(
        SocialPipelineFSM.readiness_keywords_geo,
        SocialPipelineFSM.readiness_keywords_qty,
    ),
    F.data == f"{_PREFIX}:keywords:cancel",
)
async def social_readiness_keywords_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Cancel keyword generation -- return to readiness checklist."""
    await show_social_readiness_check(callback, state, user, db, redis)
    await callback.answer()


# ---------------------------------------------------------------------------
# Keywords: generation pipeline helper
# ---------------------------------------------------------------------------


async def _run_pipeline_keyword_generation(
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
) -> None:
    """Run keyword pipeline (delegates to _readiness_common.run_keyword_generation)."""
    from routers.publishing.pipeline._readiness_common import run_keyword_generation

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
        token_service=token_service,
        ai_orchestrator=ai_orchestrator,
        dataforseo_client=dataforseo_client,
        log_prefix="pipeline.social.readiness",
        readiness_state=SocialPipelineFSM.readiness_check,
        back_kb_prefix=_PREFIX,
        on_success=show_social_readiness_check_msg,
    )


# ---------------------------------------------------------------------------
# Description sub-flow
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:description",
)
async def social_readiness_description_menu(callback: CallbackQuery) -> None:
    """Show description options."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await callback.message.edit_text(
        "Описание компании/категории\n\nAI напишет точнее с контекстом о вашей компании.",
        reply_markup=pipeline_description_options_kb(prefix=_PREFIX),
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:description:ai",
)
async def social_readiness_description_ai(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Generate category description via AI (delegates to _readiness_common)."""
    from routers.publishing.pipeline._readiness_common import generate_description_ai

    await generate_description_ai(
        callback=callback,
        state=state,
        user=user,
        db=db,
        redis=redis,
        ai_orchestrator=ai_orchestrator,
        log_prefix="pipeline.social.readiness",
        on_success=show_social_readiness_check,
    )


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:description:manual",
)
async def social_readiness_description_manual_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start manual description input."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await callback.message.edit_text(
        "Введите описание компании/категории (10-2000 символов).\n\nЧем подробнее -- тем точнее будут посты.",
        reply_markup=pipeline_back_to_checklist_kb(prefix=_PREFIX),
    )
    await state.set_state(SocialPipelineFSM.readiness_description)
    await callback.answer()


@router.message(SocialPipelineFSM.readiness_description, F.text)
async def social_readiness_description_manual_input(
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
            reply_markup=cancel_kb("pipeline:social:cancel"),
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
        "pipeline.social.readiness.description_manual",
        user_id=user.id,
        category_id=category_id,
    )

    await message.answer("Описание сохранено.")
    await show_social_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Navigation: back to checklist, done
# ---------------------------------------------------------------------------


@router.callback_query(
    StateFilter(
        SocialPipelineFSM.readiness_keywords_products,
        SocialPipelineFSM.readiness_keywords_geo,
        SocialPipelineFSM.readiness_keywords_qty,
        SocialPipelineFSM.readiness_description,
    ),
    F.data == f"{_PREFIX}:back",
)
async def social_readiness_back_from_input(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Return to readiness checklist from text-input sub-flows (M5)."""
    await show_social_readiness_check(callback, state, user, db, redis)
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:back",
)
async def social_readiness_back(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Return to readiness checklist from any sub-flow options screen."""
    await show_social_readiness_check(callback, state, user, db, redis)
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == f"{_PREFIX}:done",
)
async def social_readiness_done(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Proceed to step 5 (confirmation). Keywords are required blocker."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    if not category_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, pipeline_type="social")

    if report.has_blockers:
        await callback.answer(
            "Добавьте ключевые фразы -- это обязательный пункт.",
            show_alert=True,
        )
        return

    from routers.publishing.pipeline.social.generation import show_social_confirm

    await show_social_confirm(callback, state, user, db, redis, report, data)
    await callback.answer()
