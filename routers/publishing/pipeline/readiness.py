"""Readiness check handlers for Article Pipeline step 4 (F5.3).

Sub-flows: keywords (auto/configure/upload), description (AI/manual),
prices (text/Excel), images (count selection).
UX: UX_PIPELINE.md §4.1 step 4, §4.4 progressive readiness.
Rules: .claude/rules/pipeline.md — inline handlers, NOT FSM delegation.
"""

from __future__ import annotations

import html

import structlog
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.config import get_settings
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from keyboards.inline import cancel_kb
from keyboards.pipeline import (
    pipeline_back_to_checklist_kb,
    pipeline_description_options_kb,
    pipeline_images_options_kb,
    pipeline_keywords_options_kb,
    pipeline_prices_options_kb,
    pipeline_readiness_kb,
)
from routers.publishing.pipeline._common import (
    ArticlePipelineFSM,
    clear_checkpoint,
    save_checkpoint,
)
from services.ai.description import DescriptionService
from services.ai.orchestrator import AIOrchestrator
from services.readiness import ReadinessReport, ReadinessService
from services.tokens import (
    COST_DESCRIPTION,
    COST_PER_IMAGE,
    TokenService,
)

log = structlog.get_logger()
router = Router()

# Limits for keyword upload (mirrors categories/keywords.py)
_MAX_KEYWORD_PHRASES = 500
_MAX_KEYWORD_FILE_SIZE = 1 * 1024 * 1024  # 1 MB

# Limits for prices (mirrors categories/prices.py)
_MAX_PRICE_ROWS = 1000
_MAX_PRICE_TEXT_LEN = 50_000
_MAX_EXCEL_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


# ---------------------------------------------------------------------------
# Checklist display helpers
# ---------------------------------------------------------------------------


def _build_checklist_text(report: ReadinessReport, fsm_data: dict) -> str:  # type: ignore[type-arg]
    """Build readiness checklist text (UX_PIPELINE.md §4.1 step 4)."""
    project_name = html.escape(fsm_data.get("project_name", ""))
    category_name = html.escape(fsm_data.get("category_name", ""))

    lines: list[str] = [
        "Статья (4/5) — Подготовка\n",
        f"Проект: {project_name}",
        f"Тема: {category_name}\n",
    ]

    # Keywords status
    if report.has_keywords:
        kw_info = f"{report.keyword_count} фраз"
        if report.cluster_count:
            kw_info = f"{report.cluster_count} кластеров ({report.keyword_count} фраз)"
        lines.append(f"Ключевые фразы — {kw_info}")
    else:
        lines.append("Ключевые фразы — не заполнены (обязательно)")

    # Description status
    if report.has_description:
        lines.append("Описание — заполнено")
    elif "description" in report.missing_items:
        lines.append("Описание — не заполнено")

    # Prices status (progressive: shown for 2+ pubs)
    if "prices" in report.missing_items:
        lines.append("Цены — не заполнены")
    elif report.has_prices:
        lines.append("Цены — заполнены")

    # Images
    img_cost = report.image_count * COST_PER_IMAGE
    lines.append(f"Изображения — {report.image_count} AI ({img_cost} ток.)")

    # Cost estimate
    lines.append(f"\nОриентировочная стоимость: ~{report.estimated_cost} ток.")

    return "\n".join(lines)


async def show_readiness_check(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Render readiness checklist (step 4) or skip to step 5 if all filled.

    Called from article.py after category selection, and after each sub-flow completes.
    """
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    if not category_id:
        await callback.message.edit_text("Категория не выбрана. Начните заново.")
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    image_count = data.get("image_count", 4)

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, image_count)

    # Skip to step 5 if all required items filled and nothing to show
    if report.all_filled and not report.missing_items:
        from routers.publishing.pipeline.generation import show_confirm

        await show_confirm(callback, state, user, redis, report, data)
        return

    text = _build_checklist_text(report, data)
    kb = pipeline_readiness_kb(report)
    await callback.message.edit_text(text, reply_markup=kb)
    await state.set_state(ArticlePipelineFSM.readiness_check)
    await state.update_data(image_count=image_count)
    await save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
    )


async def show_readiness_check_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Render readiness checklist via new message (after text/file input sub-flows)."""
    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    if not category_id:
        await message.answer("Категория не выбрана. Начните заново.")
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    image_count = data.get("image_count", 4)

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, image_count)

    if report.all_filled and not report.missing_items:
        from routers.publishing.pipeline.generation import show_confirm_msg

        await show_confirm_msg(message, state, user, redis, report, data)
        return

    text = _build_checklist_text(report, data)
    kb = pipeline_readiness_kb(report)
    await message.answer(text, reply_markup=kb)
    await state.set_state(ArticlePipelineFSM.readiness_check)
    await state.update_data(image_count=image_count)
    await save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
    )


# ---------------------------------------------------------------------------
# Keywords sub-flow (4a)
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:keywords",
)
async def readiness_keywords_menu(callback: CallbackQuery) -> None:
    """Show keyword generation options."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Ключевые фразы\n\nВыберите способ добавления:",
        reply_markup=pipeline_keywords_options_kb(),
    )
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:keywords:auto",
)
async def readiness_keywords_auto(callback: CallbackQuery) -> None:
    """Auto keyword generation — Phase 10 stub."""
    await callback.answer(
        "Автоподбор ключевиков — скоро! Пока загрузите свои.",
        show_alert=True,
    )


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:keywords:configure",
)
async def readiness_keywords_configure(callback: CallbackQuery) -> None:
    """Configure keyword generation — Phase 10 stub."""
    await callback.answer(
        "Настройка параметров — скоро! Пока загрузите свои.",
        show_alert=True,
    )


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:keywords:upload",
)
async def readiness_keywords_upload_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start keyword upload sub-flow — prompt for TXT file."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Загрузите TXT-файл с ключевыми фразами.\n"
        "Одна фраза на строку, максимум 500 фраз, до 1 МБ.\n\n"
        "Или отправьте фразы текстом (каждая с новой строки).",
        reply_markup=pipeline_back_to_checklist_kb(),
    )
    await state.set_state(ArticlePipelineFSM.readiness_keywords_products)
    await callback.answer()


@router.message(ArticlePipelineFSM.readiness_keywords_products, F.document)
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
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    if doc.file_size and doc.file_size > _MAX_KEYWORD_FILE_SIZE:
        await message.answer(
            "Файл слишком большой (макс. 1 МБ).",
            reply_markup=cancel_kb("pipeline:article:cancel"),
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
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    if len(phrases) > _MAX_KEYWORD_PHRASES:
        await message.answer(
            f"Максимум {_MAX_KEYWORD_PHRASES} фраз. Сейчас: {len(phrases)}.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
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
        "pipeline.readiness.keywords_uploaded",
        user_id=user.id,
        category_id=category_id,
        phrase_count=len(phrases),
    )

    await message.answer(f"Загружено {len(phrases)} фраз.")
    # Return to checklist
    await show_readiness_check_msg(message, state, user, db, redis)


@router.message(ArticlePipelineFSM.readiness_keywords_products, F.text)
async def readiness_keywords_upload_text(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Process text input as keyword phrases (one per line)."""
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Отправьте TXT-файл или введите фразы текстом (каждая с новой строки).",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    phrases = [line.strip() for line in text.splitlines() if line.strip()]
    if not phrases:
        await message.answer(
            "Не удалось распознать фразы. Каждая фраза — с новой строки.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    if len(phrases) > _MAX_KEYWORD_PHRASES:
        await message.answer(
            f"Максимум {_MAX_KEYWORD_PHRASES} фраз. Сейчас: {len(phrases)}.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    if not category_id:
        await message.answer("Категория не найдена. Начните заново.")
        return

    keywords = [{"phrase": p, "volume": 0, "cpc": 0.0} for p in phrases]
    cats_repo = CategoriesRepository(db)
    await cats_repo.update_keywords(category_id, keywords)

    log.info(
        "pipeline.readiness.keywords_text",
        user_id=user.id,
        category_id=category_id,
        phrase_count=len(phrases),
    )

    await message.answer(f"Сохранено {len(phrases)} фраз.")
    await show_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Description sub-flow (4b)
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:description",
)
async def readiness_description_menu(callback: CallbackQuery) -> None:
    """Show description options."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Описание компании/категории\n\nAI напишет точнее с контекстом о вашей компании.",
        reply_markup=pipeline_description_options_kb(),
    )
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:description:ai",
)
async def readiness_description_ai(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Generate category description via AI and save to DB."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
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

    # Debit-first: charge before generation, refund on failure
    try:
        await token_svc.charge(
            user_id=user.id,
            amount=COST_DESCRIPTION,
            operation_type="description",
            description=f"Описание (pipeline, категория #{category_id})",
        )
    except Exception:
        log.exception("pipeline.readiness.description_charge_failed", user_id=user.id)
        await callback.answer("Ошибка списания токенов.", show_alert=True)
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
            "pipeline.readiness.description_ai_failed",
            user_id=user.id,
            category_id=category_id,
        )
        await callback.answer("Ошибка генерации описания. Токены возвращены.", show_alert=True)
        return

    log.info(
        "pipeline.readiness.description_generated",
        user_id=user.id,
        category_id=category_id,
        cost=COST_DESCRIPTION,
    )

    await callback.answer("Описание сгенерировано и сохранено.")
    await show_readiness_check(callback, state, user, db, redis)


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:description:manual",
)
async def readiness_description_manual_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start manual description input."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Введите описание компании/категории (10-2000 символов).\n\nЧем подробнее — тем точнее будут статьи.",
        reply_markup=pipeline_back_to_checklist_kb(),
    )
    await state.set_state(ArticlePipelineFSM.readiness_description)
    await callback.answer()


@router.message(ArticlePipelineFSM.readiness_description, F.text)
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
            reply_markup=cancel_kb("pipeline:article:cancel"),
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
        "pipeline.readiness.description_manual",
        user_id=user.id,
        category_id=category_id,
    )

    await message.answer("Описание сохранено.")
    await show_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Prices sub-flow (4c)
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:prices",
)
async def readiness_prices_menu(callback: CallbackQuery) -> None:
    """Show prices input options."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Добавить прайс-лист?\n\nВ статье будут реальные цены ваших товаров.",
        reply_markup=pipeline_prices_options_kb(),
    )
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:prices:text",
)
async def readiness_prices_text_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start prices text input sub-flow."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Введите прайс-лист текстом.\n"
        "Формат: Товар — Цена (каждый с новой строки).\n\n"
        "<i>Пример:\nКухня Прага — от 120 000 руб.\nШкаф-купе — от 45 000 руб.</i>",
        reply_markup=pipeline_back_to_checklist_kb(),
    )
    await state.set_state(ArticlePipelineFSM.readiness_prices)
    await callback.answer()


@router.message(ArticlePipelineFSM.readiness_prices, F.text)
async def readiness_prices_text_input(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Save prices from text input."""
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Введите прайс-лист текстом или нажмите Отмена.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    if len(text) > _MAX_PRICE_TEXT_LEN:
        await message.answer(
            "Текст слишком длинный. Максимум 50 000 символов.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) > _MAX_PRICE_ROWS:
        await message.answer(
            f"Максимум {_MAX_PRICE_ROWS} строк. Сейчас: {len(lines)}.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    if not category_id:
        await message.answer("Категория не найдена. Начните заново.")
        return

    prices_text = "\n".join(lines)
    cats_repo = CategoriesRepository(db)
    await cats_repo.update(category_id, CategoryUpdate(prices=prices_text))

    log.info(
        "pipeline.readiness.prices_text",
        user_id=user.id,
        category_id=category_id,
        lines_count=len(lines),
    )

    await message.answer(f"Сохранено {len(lines)} позиций.")
    await show_readiness_check_msg(message, state, user, db, redis)


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:prices:excel",
)
async def readiness_prices_excel_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start prices Excel upload sub-flow."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    await callback.message.edit_text(
        "Загрузите Excel-файл (.xlsx) с прайсом.\n"
        "Колонки: A — Название, B — Цена, C — Описание (опц.).\n"
        "Максимум 1000 строк, 5 МБ.",
        reply_markup=pipeline_back_to_checklist_kb(),
    )
    await state.set_state(ArticlePipelineFSM.readiness_prices)
    await callback.answer()


@router.message(ArticlePipelineFSM.readiness_prices, F.document)
async def readiness_prices_excel_file(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Process uploaded Excel file with prices."""
    doc = message.document
    if not doc:
        await message.answer("Файл не найден.")
        return

    filename = doc.file_name or ""
    if not filename.lower().endswith(".xlsx"):
        await message.answer(
            "Нужен .xlsx файл.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    if doc.file_size and doc.file_size > _MAX_EXCEL_FILE_SIZE:
        await message.answer(
            "Файл слишком большой (макс. 5 МБ).",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    file = await message.bot.download(doc)  # type: ignore[union-attr]
    if file is None:
        await message.answer("Не удалось загрузить файл.")
        return

    file_bytes = file.read()

    # Reuse Excel parsing from prices module
    from routers.categories.prices import parse_excel_rows

    result = parse_excel_rows(file_bytes)

    if isinstance(result, str):
        error_msgs = {
            "empty": "Файл пустой. Добавьте данные.",
            "too_many_rows": f"Превышен лимит: максимум {_MAX_PRICE_ROWS} строк.",
        }
        await message.answer(
            error_msgs.get(result, "Ошибка чтения файла."),
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    if not result:
        await message.answer(
            "Не удалось извлечь данные из файла.",
            reply_markup=cancel_kb("pipeline:article:cancel"),
        )
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    if not category_id:
        await message.answer("Категория не найдена. Начните заново.")
        return

    prices_text = "\n".join(result)
    cats_repo = CategoriesRepository(db)
    await cats_repo.update(category_id, CategoryUpdate(prices=prices_text))

    log.info(
        "pipeline.readiness.prices_excel",
        user_id=user.id,
        category_id=category_id,
        lines_count=len(result),
    )

    await message.answer(f"Загружено {len(result)} позиций из Excel.")
    await show_readiness_check_msg(message, state, user, db, redis)


# ---------------------------------------------------------------------------
# Images sub-flow (4d)
# ---------------------------------------------------------------------------


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:images",
)
async def readiness_images_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show image count selection."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    current_count = data.get("image_count", 4)

    await callback.message.edit_text(
        f"Изображения — сейчас: {current_count} AI\n\nВыберите количество:",
        reply_markup=pipeline_images_options_kb(current_count),
    )
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data.regexp(r"^pipeline:readiness:images:(\d+)$"),
)
async def readiness_images_select(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Handle image count selection and return to checklist."""
    if not callback.data:
        await callback.answer()
        return

    try:
        count = int(callback.data.split(":")[-1])
    except ValueError:
        await callback.answer()
        return

    allowed = {0, 1, 2, 3, 4, 6, 8, 10}
    if count not in allowed:
        log.warning("pipeline.readiness.images_invalid_count", user_id=user.id, count=count)
        await callback.answer("Некорректное количество.", show_alert=True)
        return

    await state.update_data(image_count=count)

    log.info("pipeline.readiness.images_count", user_id=user.id, count=count)
    await callback.answer(f"Изображений: {count}")
    await show_readiness_check(callback, state, user, db, redis)


# ---------------------------------------------------------------------------
# Navigation: back to checklist, done
# ---------------------------------------------------------------------------


@router.callback_query(
    StateFilter(
        ArticlePipelineFSM.readiness_keywords_products,
        ArticlePipelineFSM.readiness_description,
        ArticlePipelineFSM.readiness_prices,
    ),
    F.data == "pipeline:readiness:back",
)
async def readiness_back_from_input(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Return to readiness checklist from text-input sub-flows (M5)."""
    await show_readiness_check(callback, state, user, db, redis)
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:back",
)
async def readiness_back(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Return to readiness checklist from any sub-flow options screen."""
    await show_readiness_check(callback, state, user, db, redis)
    await callback.answer()


@router.callback_query(
    ArticlePipelineFSM.readiness_check,
    F.data == "pipeline:readiness:done",
)
async def readiness_done(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Proceed to step 5 (confirmation). Keywords are required blocker."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    if not category_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    image_count = data.get("image_count", 4)
    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, image_count)

    if report.has_blockers:
        await callback.answer(
            "Добавьте ключевые фразы — это обязательный пункт.",
            show_alert=True,
        )
        return

    from routers.publishing.pipeline.generation import show_confirm

    await show_confirm(callback, state, user, redis, report, data)
    await callback.answer()
