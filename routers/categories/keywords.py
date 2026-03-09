"""Keyword management: AI generation, file upload, cluster CRUD, CSV export.

Source of truth: UX_TOOLBOX.md section 9, FSM_SPEC.md (KeywordGenerationFSM,
KeywordUploadFSM), EDGE_CASES.md E01/E03/E16/E36.
"""

import csv
import html
import io
import time
from typing import Any

import structlog
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    Message,
)

from bot.custom_emoji import EMOJI_PROGRESS
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from db.client import SupabaseClient
from db.models import Category, ProjectUpdate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    cancel_kb,
    category_card_kb,
    keywords_cluster_delete_list_kb,
    keywords_cluster_list_kb,
    keywords_delete_all_confirm_kb,
    keywords_empty_kb,
    keywords_results_kb,
    keywords_summary_kb,
    menu_kb,
)

log = structlog.get_logger()
router = Router()

# File upload limits
_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
_MAX_PHRASES = 500

# CSV formula injection chars
_CSV_INJECTION_CHARS = ("=", "+", "-", "@")


def _csv_safe(value: str) -> str:
    """Neutralize CSV formula injection by prepending a single quote."""
    if value and value[0] in _CSV_INJECTION_CHARS:
        return "'" + value
    return value


# ---------------------------------------------------------------------------
# FSM definitions (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class KeywordGenerationFSM(StatesGroup):
    geography = State()  # City input (only if project.company_city not set)
    fetching = State()  # DataForSEO fetch (progress msg)
    clustering = State()  # AI clustering (progress msg)
    enriching = State()  # DataForSEO enrich (progress msg)
    results = State()  # Show results


class KeywordUploadFSM(StatesGroup):
    file_upload = State()  # TXT file (.txt, UTF-8, ≤500 phrases, ≤1MB)
    enriching = State()  # DataForSEO enrich (progress msg)
    clustering = State()  # AI clustering (progress msg)
    results = State()  # Show results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _check_category_ownership(
    category_id: int,
    user: User,
    db: SupabaseClient,
) -> tuple[CategoriesRepository, Category | None, int | None]:
    """Load category and verify ownership. Returns (repo, category, project_id)."""
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)
    if not category:
        return cats_repo, None, None

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        return cats_repo, None, None

    return cats_repo, category, category.project_id


def _build_keywords_summary(category: Any) -> str:
    """Build keywords summary text."""
    clusters: list[dict[str, Any]] = category.keywords or []
    safe_name = html.escape(category.name)

    if not clusters:
        return f"<b>Ключевые фразы</b> — {safe_name}\n\nФразы не добавлены. Начните подбор или загрузите свои."

    total_phrases = sum(len(c.get("phrases", [])) for c in clusters)
    total_volume = sum(c.get("total_volume", 0) for c in clusters)
    cluster_count = len(clusters)

    text = (
        f"<b>Ключевые фразы</b> — {safe_name}\n\n"
        f"Кластеров: {cluster_count}\n"
        f"Фраз: {total_phrases}"
    )
    if total_volume > 0:
        text += f"\nОбщий объём: {total_volume:,}/мес"
    return text


# ---------------------------------------------------------------------------
# 1. Show keywords screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:keywords$"))
async def show_keywords(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show keywords summary or empty screen (UX_TOOLBOX section 9)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(category_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    text = _build_keywords_summary(category)
    clusters: list[dict[str, Any]] = category.keywords or []
    kb = keywords_summary_kb(category_id) if clusters else keywords_empty_kb(category_id)

    await safe_edit_text(msg, text, reply_markup=kb)
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Start generation (with saved answers check)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:generate$"))
async def start_generation(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
    ai_orchestrator: Any,
    dataforseo_client: Any,
) -> None:
    """Start keyword generation — auto-fill from category/project, no questions."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, project_id = await _check_category_ownership(cat_id, user, db)

    if not category or project_id is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Auto-fill products from category description/name
    products = category.description or category.name

    # Auto-fill geography from project
    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)
    geography = project.company_city if project and project.company_city else None

    if not geography:
        # Only question: city (if not set on project)
        await state.set_state(KeywordGenerationFSM.geography)
        await state.update_data(
            last_update_time=time.time(),
            kw_cat_id=cat_id,
            kw_project_id=project_id,
            kw_products=products,
        )
        await safe_edit_text(
            msg,
            "В каком городе ваш бизнес?\n<i>Для точных SEO-фраз</i>",
            reply_markup=cancel_kb(f"kw:{cat_id}:gen_cancel"),
        )
        await callback.answer()
        return

    # Everything available — start pipeline immediately
    await callback.answer()
    await _run_generation_pipeline(
        msg, state, user, db,
        cat_id=cat_id, project_id=project_id,
        products=products, geography=geography,
        ai_orchestrator=ai_orchestrator,
        dataforseo_client=dataforseo_client,
    )


# ---------------------------------------------------------------------------
# 3. Geography input (only asked if project.company_city is not set)
# ---------------------------------------------------------------------------


@router.message(KeywordGenerationFSM.geography, F.text)
async def process_geography(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
    ai_orchestrator: Any,
    dataforseo_client: Any,
) -> None:
    """Validate geography, save to project, start pipeline immediately."""
    text = (message.text or "").strip()

    if len(text) < 2 or len(text) > 200:
        await message.answer("Введите от 2 до 200 символов.")
        return

    data = await state.get_data()
    cat_id = int(data["kw_cat_id"])
    project_id = int(data["kw_project_id"])
    products = str(data.get("kw_products", ""))

    # Save city to project for future use
    proj_svc = project_service_factory(db)
    await proj_svc.update_project(project_id, user.id, ProjectUpdate(company_city=text))

    # Start pipeline immediately
    await _run_generation_pipeline(
        message, state, user, db,
        cat_id=cat_id, project_id=project_id,
        products=products, geography=text,
        ai_orchestrator=ai_orchestrator,
        dataforseo_client=dataforseo_client,
    )


# ---------------------------------------------------------------------------
# 4. Generation pipeline (internal)
# ---------------------------------------------------------------------------


async def _run_generation_pipeline(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    *,
    cat_id: int,
    project_id: int,
    products: str,
    geography: str,
    ai_orchestrator: Any,
    dataforseo_client: Any,
) -> None:
    """Run keyword pipeline: fetch → cluster → enrich → save (free, no token charge)."""
    from services.keywords import KeywordService

    try:
        kw_service = KeywordService(
            orchestrator=ai_orchestrator,
            dataforseo=dataforseo_client,
            db=db,
        )

        # Step 1: Fetch raw phrases from DataForSEO (all available, no limit)
        await state.set_state(KeywordGenerationFSM.fetching)
        await safe_edit_text(msg, "Получаю реальные фразы из DataForSEO...")

        raw_phrases = await kw_service.fetch_raw_phrases(
            products=products,
            geography=geography,
            project_id=project_id,
            user_id=user.id,
        )

        # Step 2: AI clustering
        await state.set_state(KeywordGenerationFSM.clustering)
        if raw_phrases:
            await safe_edit_text(msg, f"Получено {len(raw_phrases)} фраз. Группирую по интенту...")
            clusters = await kw_service.cluster_phrases(
                raw_phrases=raw_phrases,
                products=products,
                geography=geography,
                project_id=project_id,
                user_id=user.id,
            )
        else:
            await safe_edit_text(msg, f"{EMOJI_PROGRESS} Генерирую ключевые фразы...")
            clusters = await kw_service.generate_clusters_direct(
                products=products,
                geography=geography,
                project_id=project_id,
                user_id=user.id,
            )

        # Step 3: Enrich with metrics
        await state.set_state(KeywordGenerationFSM.enriching)
        await safe_edit_text(msg, f"Создано {len(clusters)} кластеров. Обогащаю данными...")

        enriched = await kw_service.enrich_clusters(clusters)

        # Filter AI-invented zero-volume junk
        enriched = kw_service.filter_low_quality(enriched)

        # Save to category (MERGE with existing)
        cats_repo = CategoriesRepository(db)
        category = await cats_repo.get_by_id(cat_id)
        existing: list[dict[str, Any]] = (category.keywords if category else []) or []
        merged = existing + enriched
        await cats_repo.update_keywords(cat_id, merged)

        # Show results
        await state.set_state(KeywordGenerationFSM.results)

        total_phrases = sum(len(c.get("phrases", [])) for c in enriched)
        total_volume = sum(c.get("total_volume", 0) for c in enriched)

        result_text = (
            f"Готово! Добавлено:\n"
            f"Кластеров: {len(enriched)}\n"
            f"Фраз: {total_phrases}"
        )
        if total_volume > 0:
            result_text += f"\nОбщий объём: {total_volume:,}/мес"

        await safe_edit_text(msg, result_text, reply_markup=keywords_results_kb(cat_id))
        await state.clear()

        log.info(
            "keyword_generation_complete",
            cat_id=cat_id,
            user_id=user.id,
            clusters=len(enriched),
            phrases=total_phrases,
        )

    except Exception:
        log.exception("keyword_pipeline_failed", cat_id=cat_id, user_id=user.id)
        await state.clear()
        await safe_edit_text(msg, 
            "Ошибка при подборе фраз. Попробуйте позже.",
            reply_markup=keywords_empty_kb(cat_id),
        )


# ---------------------------------------------------------------------------
# 8. File upload flow
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:upload$"))
async def start_upload(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start keyword file upload (UX_TOOLBOX section 9.6)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, project_id = await _check_category_ownership(cat_id, user, db)

    if not category or project_id is None:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(KeywordUploadFSM.file_upload)
    await state.update_data(
        last_update_time=time.time(),
        kw_cat_id=cat_id,
        kw_project_id=project_id,
    )

    await safe_edit_text(msg, 
        "Загрузите текстовый файл (.txt) с ключевыми фразами.\n"
        "Каждая фраза на отдельной строке.\n\n"
        f"Максимум: {_MAX_PHRASES} фраз, {_MAX_FILE_SIZE // (1024 * 1024)} МБ.",
        reply_markup=cancel_kb(f"kw:{cat_id}:upl_cancel"),
    )
    await callback.answer()


@router.message(KeywordUploadFSM.file_upload, F.text)
async def handle_text_in_upload(
    message: Message,
    state: FSMContext,
) -> None:
    """Handle text message while waiting for file upload."""
    text = (message.text or "").strip()
    if text == "Отмена":
        await state.clear()
        await message.answer("Загрузка отменена.", reply_markup=menu_kb())
        return

    await message.answer("Ожидается файл .txt. Для отмены напишите «Отмена».")


@router.message(KeywordUploadFSM.file_upload, F.document)
async def process_file(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    ai_orchestrator: Any,
    dataforseo_client: Any,
) -> None:
    """Process uploaded TXT file with keywords."""
    doc = message.document
    if not doc:
        await message.answer("Файл не найден. Загрузите .txt файл.")
        return

    # Validate extension
    filename = doc.file_name or ""
    if not filename.lower().endswith(".txt"):
        await message.answer("Неверный формат. Загрузите файл с расширением .txt.")
        return

    # Validate size
    if doc.file_size and doc.file_size > _MAX_FILE_SIZE:
        await message.answer(f"Файл слишком большой. Максимум {_MAX_FILE_SIZE // (1024 * 1024)} МБ.")
        return

    # Download
    bot = message.bot
    if not bot:
        await message.answer("Внутренняя ошибка.")
        return

    file_bytes_io = await bot.download(doc)
    if not file_bytes_io:
        await message.answer("Не удалось скачать файл.")
        return

    raw_bytes = file_bytes_io.read()

    # Decode UTF-8
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        await message.answer("Файл должен быть в кодировке UTF-8.")
        await state.clear()
        return

    # Parse phrases
    phrases = [line.strip() for line in content.splitlines() if line.strip()]

    if not phrases:
        await message.answer("Файл пуст или не содержит фраз.")
        return

    if len(phrases) > _MAX_PHRASES:
        await message.answer(f"Максимум {_MAX_PHRASES} фраз. В файле: {len(phrases)}.")
        return

    data = await state.get_data()
    cat_id = int(data["kw_cat_id"])
    project_id = int(data["kw_project_id"])

    # Build raw phrases list (no volume data — will be enriched)
    raw_phrases = [{"phrase": p, "volume": 0, "cpc": 0.0, "ai_suggested": False} for p in phrases]

    # Run pipeline: cluster → enrich → save
    await _run_upload_pipeline(
        message,
        state,
        user,
        db,
        cat_id=cat_id,
        project_id=project_id,
        raw_phrases=raw_phrases,
        ai_orchestrator=ai_orchestrator,
        dataforseo_client=dataforseo_client,
    )


async def _run_upload_pipeline(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    *,
    cat_id: int,
    project_id: int,
    raw_phrases: list[dict[str, Any]],
    ai_orchestrator: Any,
    dataforseo_client: Any,
) -> None:
    """Upload pipeline: cluster → enrich → save (no charge — upload is free)."""
    from services.keywords import KeywordService

    try:
        kw_service = KeywordService(
            orchestrator=ai_orchestrator,
            dataforseo=dataforseo_client,
            db=db,
        )

        # Step 1: Cluster
        await state.set_state(KeywordUploadFSM.clustering)
        progress_msg = await msg.answer(f"Загружено {len(raw_phrases)} фраз. Группирую по интенту...")

        clusters = await kw_service.cluster_phrases(
            raw_phrases=raw_phrases,
            products="",
            geography="",
            project_id=project_id,
            user_id=user.id,
        )

        # Step 2: Enrich
        await state.set_state(KeywordUploadFSM.enriching)
        await safe_edit_text(progress_msg, f"Создано {len(clusters)} кластеров. Обогащаю данными...")

        enriched = await kw_service.enrich_clusters(clusters)

        # Save (MERGE with existing)
        cats_repo = CategoriesRepository(db)
        category = await cats_repo.get_by_id(cat_id)
        existing: list[dict[str, Any]] = (category.keywords if category else []) or []
        merged = existing + enriched
        await cats_repo.update_keywords(cat_id, merged)

        # Show results
        await state.set_state(KeywordUploadFSM.results)

        total_phrases = sum(len(c.get("phrases", [])) for c in enriched)
        total_volume = sum(c.get("total_volume", 0) for c in enriched)

        await safe_edit_text(progress_msg, 
            f"Готово! Загружено:\nКластеров: {len(enriched)}\nФраз: {total_phrases}\nОбщий объём: {total_volume:,}/мес",
            reply_markup=keywords_results_kb(cat_id),
        )
        await state.clear()

        log.info(
            "keyword_upload_complete",
            cat_id=cat_id,
            user_id=user.id,
            clusters=len(enriched),
        )

    except Exception:
        log.exception("keyword_upload_failed", cat_id=cat_id, user_id=user.id)
        await state.clear()
        await msg.answer(
            "Ошибка при обработке файла. Попробуйте позже.",
            reply_markup=keywords_empty_kb(cat_id),
        )


# ---------------------------------------------------------------------------
# 9. Cluster list (paginated)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:clusters$"))
async def show_cluster_list(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show paginated cluster list (UX_TOOLBOX section 9.3)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    if not clusters:
        await callback.answer("Нет кластеров.", show_alert=True)
        return

    await safe_edit_text(msg, 
        f"Кластеры ({len(clusters)}):",
        reply_markup=keywords_cluster_list_kb(clusters, cat_id, page=1),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^page:clusters:\d+:\d+$"))
async def paginate_clusters(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Paginate cluster list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[2])
    page = int(parts[3])

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    await safe_edit_text(msg, 
        f"Кластеры ({len(clusters)}):",
        reply_markup=keywords_cluster_list_kb(clusters, cat_id, page=page),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 10. Cluster detail
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:cluster:\d+:\d+$"))
async def show_cluster_detail(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show phrases in a cluster as text (UX_TOOLBOX section 9.4)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[2])
    idx = int(parts[3])

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    if idx < 0 or idx >= len(clusters):
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    cluster = clusters[idx]
    name = html.escape(cluster.get("cluster_name", f"Cluster {idx}"))
    cluster_type = cluster.get("cluster_type", "")
    phrases = cluster.get("phrases", [])
    total_volume = cluster.get("total_volume", 0)

    header = f"Фраз: {len(phrases)}"
    if total_volume > 0:
        header += f" | Объём: {total_volume:,}/мес"

    lines = [
        f"<b>{name}</b>",
        f"Тип: {cluster_type}" if cluster_type else "",
        f"{header}\n",
    ]

    for p in phrases[:50]:  # limit display
        phrase = html.escape(p.get("phrase", ""))
        vol = p.get("volume", 0)
        if vol > 0:
            lines.append(f"  \u2022 {phrase} ({vol:,}/мес)")
        else:
            lines.append(f"  \u2022 {phrase}")

    if len(phrases) > 50:
        lines.append(f"\n  ... ещё {len(phrases) - 50}")

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    back_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="К кластерам", callback_data=f"kw:{cat_id}:clusters")],
            [InlineKeyboardButton(text="К ключевым фразам", callback_data=f"category:{cat_id}:keywords")],
        ]
    )

    text = "\n".join(ln for ln in lines if ln)
    # Trim to 4096 chars (Telegram limit)
    if len(text) > 4000:
        text = text[:4000] + "\n..."

    await safe_edit_text(msg, text, reply_markup=back_kb)
    await callback.answer()


# ---------------------------------------------------------------------------
# 11. CSV download
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:download$"))
async def download_csv(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Export all keywords as CSV file (UX_TOOLBOX section 9.2)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    if not clusters:
        await callback.answer("Нет фраз для экспорта.", show_alert=True)
        return

    # Generate CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Кластер", "Тип", "Фраза", "Объём", "Сложность", "CPC", "Интент"])

    for cluster in clusters:
        c_name = _csv_safe(cluster.get("cluster_name", ""))
        c_type = _csv_safe(cluster.get("cluster_type", ""))
        for p in cluster.get("phrases", []):
            writer.writerow(
                [
                    c_name,
                    c_type,
                    _csv_safe(p.get("phrase", "")),
                    p.get("volume", 0),
                    p.get("difficulty", 0),
                    p.get("cpc", 0),
                    _csv_safe(p.get("intent", "")),
                ]
            )

    csv_bytes = output.getvalue().encode("utf-8-sig")  # BOM for Excel compat
    doc = BufferedInputFile(csv_bytes, filename=f"keywords_cat_{cat_id}.csv")

    bot: Bot | None = msg.bot
    if bot:
        await bot.send_document(
            chat_id=callback.from_user.id,
            document=doc,
            caption=f"Ключевые фразы — {html.escape(category.name)}",
        )

    await callback.answer()


# ---------------------------------------------------------------------------
# 12. Delete cluster (two-step: show list → delete single)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:delete_cluster$"))
async def show_delete_cluster_list(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show cluster list with [X] buttons for deletion (UX_TOOLBOX section 9.7)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    if not clusters:
        await callback.answer("Нет кластеров для удаления.", show_alert=True)
        return

    await safe_edit_text(msg, 
        "Выберите кластер для удаления:",
        reply_markup=keywords_cluster_delete_list_kb(clusters, cat_id, page=1),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^page:del_clusters:\d+:\d+$"))
async def paginate_delete_clusters(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Paginate delete cluster list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[2])
    page = int(parts[3])

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    await safe_edit_text(msg, 
        "Выберите кластер для удаления:",
        reply_markup=keywords_cluster_delete_list_kb(clusters, cat_id, page=page),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^kw:\d+:del_cluster:\d+$"))
async def delete_single_cluster(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Remove a single cluster by index."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    idx = int(parts[3])

    cats_repo, category, _ = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = list(category.keywords or [])
    if idx < 0 or idx >= len(clusters):
        await callback.answer("Кластер не найден.", show_alert=True)
        return

    removed_name = clusters[idx].get("cluster_name", f"Cluster {idx}")
    clusters.pop(idx)
    await cats_repo.update_keywords(cat_id, clusters)

    log.info("cluster_deleted", cat_id=cat_id, cluster=removed_name, user_id=user.id)

    if clusters:
        await safe_edit_text(msg, 
            f"Кластер «{html.escape(removed_name)}» удалён.\n\nВыберите кластер для удаления:",
            reply_markup=keywords_cluster_delete_list_kb(clusters, cat_id, page=1),
        )
    else:
        await safe_edit_text(msg, 
            f"Кластер «{html.escape(removed_name)}» удалён. Фразы закончились.",
            reply_markup=keywords_empty_kb(cat_id),
        )

    await callback.answer()


# ---------------------------------------------------------------------------
# 13. Delete all keywords
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:delete_all$"))
async def delete_all_ask(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show delete-all confirmation (UX_TOOLBOX section 9.7)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    clusters: list[dict[str, Any]] = category.keywords or []
    total = sum(len(c.get("phrases", [])) for c in clusters)

    await safe_edit_text(msg, 
        f"Удалить все ключевые фразы ({total} фраз, {len(clusters)} кластеров)?\nЭто действие необратимо.",
        reply_markup=keywords_delete_all_confirm_kb(cat_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^kw:\d+:delete_all:yes$"))
async def delete_all_confirm(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Delete all keywords."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cats_repo, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await cats_repo.update_keywords(cat_id, [])

    log.info("keywords_deleted_all", cat_id=cat_id, user_id=user.id)

    safe_name = html.escape(category.name)
    await safe_edit_text(msg, 
        f"<b>Ключевые фразы</b> — {safe_name}\n\nВсе фразы удалены.",
        reply_markup=keywords_empty_kb(cat_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 14. Cancel handlers (inline button)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:gen_cancel$"))
async def cancel_generation_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel keyword generation via inline button — return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if category:
        safe_name = html.escape(category.name)
        await safe_edit_text(msg, 
            f"<b>{safe_name}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await safe_edit_text(msg, "Подбор фраз отменён.", reply_markup=menu_kb())
    await callback.answer()


@router.callback_query(F.data.regexp(r"^kw:\d+:upl_cancel$"))
async def cancel_upload_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel keyword upload via inline button — return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if category:
        safe_name = html.escape(category.name)
        await safe_edit_text(msg, 
            f"<b>{safe_name}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await safe_edit_text(msg, "Загрузка отменена.", reply_markup=menu_kb())
    await callback.answer()
