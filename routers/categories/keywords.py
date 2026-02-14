"""Router: keyword management — generation FSM, upload FSM, cluster navigation."""

import io

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import Category, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.publish import (
    insufficient_balance_kb,
    keyword_confirm_kb,
    keyword_quantity_kb,
    keyword_results_kb,
    keywords_main_kb,
)
from keyboards.reply import cancel_kb, main_menu
from routers._helpers import guard_callback_message
from services.ai.rate_limiter import RateLimiter
from services.tokens import TokenService, estimate_keywords_cost

log = structlog.get_logger()

router = Router(name="categories_keywords")


# ---------------------------------------------------------------------------
# FSM definitions (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class KeywordGenerationFSM(StatesGroup):
    products = State()     # "What products/services?"
    geography = State()    # "What geography?"
    quantity = State()     # Choose 50/100/150/200
    confirm = State()      # Confirm cost
    fetching = State()     # DataForSEO
    clustering = State()   # AI clustering
    enriching = State()    # DataForSEO enrich
    results = State()      # Show results + [Save]


class KeywordUploadFSM(StatesGroup):
    file_upload = State()  # "Upload TXT file"
    enriching = State()    # DataForSEO enrich
    clustering = State()   # AI clustering
    results = State()      # Show results + [Save]


# ---------------------------------------------------------------------------
# Helper: keyword selection from cluster format
# ---------------------------------------------------------------------------


def _select_keyword_from_clusters(keywords: list[dict[str, object]]) -> str | None:
    """Pick first available main_phrase from article clusters."""
    for cluster in keywords:
        if cluster.get("cluster_type") == "article":
            val = cluster.get("main_phrase")
            return str(val) if val is not None else None
    # Legacy flat format
    if keywords and "phrase" in keywords[0]:
        val = keywords[0]["phrase"]
        return str(val) if val is not None else None
    return None


# ---------------------------------------------------------------------------
# Helper: format cluster summary
# ---------------------------------------------------------------------------


def _format_cluster_summary(clusters: list[dict]) -> str:  # type: ignore[type-arg]
    """Format cluster summary for display."""
    lines = [f"Найдено {len(clusters)} кластеров:\n"]
    for i, c in enumerate(clusters[:10], 1):  # Show max 10
        name = c.get("cluster_name", "?")
        count = len(c.get("phrases", []))
        volume = c.get("total_volume", 0)
        lines.append(f"{i}. {name} ({count} фраз, объём: {volume})")
    if len(clusters) > 10:
        lines.append(f"... и ещё {len(clusters) - 10}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Authorization helper
# ---------------------------------------------------------------------------


async def _get_category_or_notify(
    category_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery,
) -> tuple[Category, int] | None:
    """Fetch category and verify ownership via project. Returns (category, project_id) or None."""
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    return category, project.id


# ---------------------------------------------------------------------------
# 1. Keywords main screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):keywords$"))
async def cb_keywords_main(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show keywords summary and management keyboard."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_category_or_notify(category_id, user.id, db, callback)
    if not result:
        return
    category, _ = result

    kw = category.keywords or []
    has_keywords = len(kw) > 0

    if has_keywords:
        # Count total phrases across all clusters
        total_phrases = 0
        for item in kw:
            if isinstance(item, dict) and "phrases" in item:
                total_phrases += len(item["phrases"])
            else:
                total_phrases += 1
        text = f"Ключевые фразы: {len(kw)} кластеров, {total_phrases} фраз"
    else:
        text = "Ключевые фразы ещё не добавлены.\nПодберите автоматически или загрузите свой список."

    await msg.edit_text(text, reply_markup=keywords_main_kb(category_id, has_keywords).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Start keyword generation FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):kw:generate$"))
async def cb_kw_generate_start(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Start KeywordGenerationFSM: ask about products/services."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_category_or_notify(category_id, user.id, db, callback)
    if not result:
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(KeywordGenerationFSM.products)
    await state.update_data(category_id=category_id)
    await msg.answer(
        "Какие товары/услуги предлагает ваш бизнес? (3-1000 символов)",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 3. FSM: products step
# ---------------------------------------------------------------------------


@router.message(KeywordGenerationFSM.products, F.text)
async def fsm_kw_products(message: Message, state: FSMContext) -> None:
    """Validate products input, advance to geography."""
    text = (message.text or "").strip()
    if len(text) < 3:
        await message.answer("Опишите товары/услуги подробнее (минимум 3 символа).")
        return
    if len(text) > 1000:
        await message.answer("Описание слишком длинное (максимум 1000 символов).")
        return

    await state.update_data(products=text)
    await state.set_state(KeywordGenerationFSM.geography)
    await message.answer("Какая география работы? (город, регион, страна)")


# ---------------------------------------------------------------------------
# 4. FSM: geography step
# ---------------------------------------------------------------------------


@router.message(KeywordGenerationFSM.geography, F.text)
async def fsm_kw_geography(message: Message, state: FSMContext) -> None:
    """Validate geography input, advance to quantity selection."""
    text = (message.text or "").strip()
    if len(text) < 2:
        await message.answer("Укажите географию работы (минимум 2 символа).")
        return
    if len(text) > 200:
        await message.answer("Слишком длинный текст (максимум 200 символов).")
        return

    data = await state.get_data()
    category_id = data["category_id"]
    await state.update_data(geography=text)
    await state.set_state(KeywordGenerationFSM.quantity)
    await message.answer(
        "Сколько ключевых фраз подобрать?",
        reply_markup=keyword_quantity_kb(category_id).as_markup(),
    )


# ---------------------------------------------------------------------------
# 5. FSM: quantity selection (callback)
# ---------------------------------------------------------------------------


@router.callback_query(KeywordGenerationFSM.quantity, F.data.regexp(r"^kw:qty:(\d+):(\d+)$"))
async def cb_kw_quantity(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Parse quantity, check balance, show cost confirmation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[2])
    quantity = int(parts[3])

    if quantity not in (50, 100, 150, 200):
        await callback.answer("Выберите одно из значений: 50, 100, 150, 200", show_alert=True)
        return

    cost = estimate_keywords_cost(quantity)
    settings = get_settings()
    token_svc = TokenService(db, settings.admin_id)
    has_enough = await token_svc.check_balance(user.id, cost)

    if not has_enough:
        balance = await token_svc.get_balance(user.id)
        await msg.edit_text(
            token_svc.format_insufficient_msg(cost, balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await callback.answer()
        return

    await state.update_data(quantity=quantity, cost=cost, category_id=category_id)
    await state.set_state(KeywordGenerationFSM.confirm)
    await msg.edit_text(
        f"Подобрать {quantity} ключевых фраз за {cost} токенов?",
        reply_markup=keyword_confirm_kb(category_id, cost).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. FSM: confirm and run pipeline
# ---------------------------------------------------------------------------


@router.callback_query(KeywordGenerationFSM.confirm, F.data == "kw:confirm")
async def cb_kw_confirm(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
    rate_limiter: RateLimiter,
) -> None:
    """Charge tokens and run the data-first keyword pipeline."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # E25: rate limit check (raises RateLimitError → global handler)
    await rate_limiter.check(user.id, "keyword_generation")

    data = await state.get_data()
    category_id = data["category_id"]
    cost = data["cost"]
    quantity = data["quantity"]
    products = data.get("products", "")
    geography = data.get("geography", "")

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_id)

    # Charge tokens (E01: InsufficientBalanceError handled)
    try:
        await token_svc.charge(
            user.id, cost,
            operation_type="keyword_generation",
            description=f"Keywords: {quantity} phrases, {products[:50]}",
        )
    except Exception:
        balance = await token_svc.get_balance(user.id)
        await msg.edit_text(
            token_svc.format_insufficient_msg(cost, balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await callback.answer()
        return

    # Pipeline progress messages
    try:
        await state.set_state(KeywordGenerationFSM.fetching)
        await msg.edit_text("Получаю реальные поисковые фразы из Google... (3 сек)")

        # TODO Phase 11: DataForSEO keyword_suggestions + related_keywords
        # For now, generate placeholder clusters

        await state.set_state(KeywordGenerationFSM.clustering)
        await msg.edit_text("Группирую фразы по поисковому интенту... (10 сек)")

        # TODO Phase 11: AI clustering via keywords_cluster_v3.yaml

        await state.set_state(KeywordGenerationFSM.enriching)
        await msg.edit_text("Обогащаю данные: объём, сложность, CPC... (2 сек)")

        # TODO Phase 11: DataForSEO enrich_keywords

        # Placeholder cluster result
        clusters = _build_placeholder_clusters(products, geography, quantity)

        await state.update_data(clusters=clusters)
        await state.set_state(KeywordGenerationFSM.results)

        summary = _format_cluster_summary(clusters)
        await msg.edit_text(summary, reply_markup=keyword_results_kb(category_id).as_markup())
    except Exception:
        log.exception("keyword_pipeline_failed", user_id=user.id, category_id=category_id)
        # E03 fallback: refund tokens
        try:
            await token_svc.refund(
                user.id, cost,
                reason="refund",
                description="Keyword generation failed",
            )
        except Exception:
            log.exception("keyword_refund_failed", user_id=user.id)
        await msg.edit_text(
            "Произошла ошибка при подборе фраз. Токены возвращены.",
            reply_markup=keywords_main_kb(category_id, has_keywords=False).as_markup(),
        )

    await callback.answer()


# ---------------------------------------------------------------------------
# 7. FSM: save results
# ---------------------------------------------------------------------------


@router.callback_query(KeywordGenerationFSM.results, F.data == "kw:save")
async def cb_kw_save(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Save generated clusters to category.keywords."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    clusters = data.get("clusters", [])
    category_id = data["category_id"]
    await state.clear()

    repo = CategoriesRepository(db)
    await repo.update_keywords(category_id, clusters)

    await msg.edit_text("Фразы сохранены!")
    # Show category card
    category = await repo.get_by_id(category_id)
    if category:
        from keyboards.inline import category_card_kb

        await msg.answer(
            f"Категория: {category.name}",
            reply_markup=category_card_kb(category).as_markup(),
        )

    # Restore main menu reply keyboard
    await msg.answer("Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin"))
    await callback.answer()


# ---------------------------------------------------------------------------
# 8. Start keyword upload FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):kw:upload$"))
async def cb_kw_upload_start(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Start KeywordUploadFSM: ask for TXT file."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_category_or_notify(category_id, user.id, db, callback)
    if not result:
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(KeywordUploadFSM.file_upload)
    await state.update_data(category_id=category_id)
    await msg.answer(
        "Загрузите TXT-файл с ключевыми фразами\n(по одной на строку, до 500 фраз, макс. 1 МБ)",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 9. FSM: upload file
# ---------------------------------------------------------------------------

_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB
_MAX_PHRASES = 500
_MIN_PHRASE_LEN = 2
_MAX_PHRASE_LEN = 200


@router.message(KeywordUploadFSM.file_upload, F.document)
async def fsm_kw_upload_file(
    message: Message, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Process uploaded TXT file with keywords."""
    doc = message.document
    if not doc:
        await message.answer("Ожидаю файл. Отправьте TXT-файл с ключевыми фразами.")
        return

    # Validate extension
    file_name = doc.file_name or ""
    if not file_name.lower().endswith(".txt"):
        await message.answer("Поддерживаются только TXT-файлы (.txt).")
        return

    # Validate size
    file_size = doc.file_size or 0
    if file_size > _MAX_FILE_SIZE:
        await message.answer(f"Файл слишком большой (макс. 1 МБ, ваш: {file_size // 1024} КБ).")
        return

    # Download file
    if not message.bot:
        await message.answer("Ошибка загрузки файла.")
        return

    buf = io.BytesIO()
    await message.bot.download(doc, destination=buf)
    buf.seek(0)

    # Parse content
    try:
        content = buf.read().decode("utf-8")
    except UnicodeDecodeError:
        await message.answer("Файл должен быть в кодировке UTF-8.")
        return

    # Parse phrases
    raw_lines = content.splitlines()
    phrases: list[str] = []
    for line in raw_lines:
        phrase = line.strip()
        if phrase:
            phrases.append(phrase)

    if not phrases:
        await message.answer("Файл не содержит ключевых фраз.")
        return

    if len(phrases) > _MAX_PHRASES:
        await message.answer(f"Слишком много фраз: {len(phrases)} (максимум {_MAX_PHRASES}).")
        return

    # Validate individual phrases
    invalid = []
    for i, phrase in enumerate(phrases[:5]):  # Check first 5 for user feedback
        if len(phrase) < _MIN_PHRASE_LEN or len(phrase) > _MAX_PHRASE_LEN:
            invalid.append(f"Строка {i + 1}: «{phrase[:30]}...» ({len(phrase)} символов)")
    if invalid:
        err_lines = "\n".join(invalid)
        await message.answer(
            f"Некоторые фразы не прошли валидацию (2-200 символов):\n{err_lines}"
        )
        return

    # Check all phrases length
    for phrase in phrases:
        if len(phrase) < _MIN_PHRASE_LEN or len(phrase) > _MAX_PHRASE_LEN:
            await message.answer(
                "Найдены фразы с длиной вне диапазона 2-200 символов. Исправьте файл и загрузите снова."
            )
            return

    data = await state.get_data()
    category_id = data["category_id"]

    # Progress messages
    await state.set_state(KeywordUploadFSM.enriching)
    await message.answer("Обогащаю данные: объём, сложность, CPC... (3 сек)")

    # TODO Phase 11: DataForSEO enrich_keywords for uploaded phrases

    await state.set_state(KeywordUploadFSM.clustering)
    await message.answer("Группирую фразы по поисковому интенту... (10 сек)")

    # TODO Phase 11: AI clustering via keywords_cluster_v3.yaml
    # For now, create a single cluster with all phrases
    clusters = _build_upload_clusters(phrases)

    await state.update_data(clusters=clusters)
    await state.set_state(KeywordUploadFSM.results)

    summary = _format_cluster_summary(clusters)
    await message.answer(
        summary,
        reply_markup=keyword_results_kb(category_id).as_markup(),
    )


# ---------------------------------------------------------------------------
# Save for upload FSM (reuses kw:save callback)
# ---------------------------------------------------------------------------


@router.callback_query(KeywordUploadFSM.results, F.data == "kw:save")
async def cb_kw_upload_save(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Save uploaded/clustered keywords to category.keywords."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    clusters = data.get("clusters", [])
    category_id = data["category_id"]
    await state.clear()

    repo = CategoriesRepository(db)
    await repo.update_keywords(category_id, clusters)

    await msg.edit_text("Фразы сохранены!")
    category = await repo.get_by_id(category_id)
    if category:
        from keyboards.inline import category_card_kb

        await msg.answer(
            f"Категория: {category.name}",
            reply_markup=category_card_kb(category).as_markup(),
        )

    await msg.answer("Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin"))
    await callback.answer()


# ---------------------------------------------------------------------------
# Placeholder builders (replaced by real services in Phase 11)
# ---------------------------------------------------------------------------


def _build_placeholder_clusters(
    products: str, geography: str, quantity: int,
) -> list[dict[str, object]]:
    """Build placeholder clusters for the keyword generation pipeline.

    Real implementation in Phase 11 will use DataForSEO + AI clustering.
    """
    base_phrase = products.split(",")[0].strip()[:50] if products else "услуга"
    geo = geography.strip()[:30] if geography else "Россия"

    clusters: list[dict[str, object]] = []
    per_cluster = max(quantity // 5, 5)
    for i in range(min(5, quantity // per_cluster)):
        cluster_name = f"{base_phrase} {geo}" if i == 0 else f"{base_phrase} вариант {i + 1}"
        phrases: list[dict[str, object]] = [
            {
                "phrase": f"{base_phrase} {geo} {j + 1}",
                "volume": 100 - j * 5,
                "difficulty": 30 + j,
                "cpc": 15.0,
                "intent": "informational",
                "ai_suggested": False,
            }
            for j in range(per_cluster)
        ]
        total_vol = sum(100 - j * 5 for j in range(per_cluster))
        clusters.append({
            "cluster_name": cluster_name,
            "cluster_type": "article",
            "main_phrase": f"{base_phrase} {geo}" if i == 0 else f"{base_phrase} {i + 1}",
            "total_volume": total_vol,
            "avg_difficulty": 35,
            "phrases": phrases,
        })

    return clusters


def _build_upload_clusters(phrases: list[str]) -> list[dict[str, object]]:
    """Build a single cluster from uploaded phrases.

    Real clustering will happen in Phase 11 via AI.
    """
    phrase_dicts = [
        {
            "phrase": p,
            "volume": 0,
            "difficulty": 0,
            "cpc": 0.0,
            "intent": "informational",
            "ai_suggested": False,
        }
        for p in phrases
    ]
    return [{
        "cluster_name": "Загруженные фразы",
        "cluster_type": "article",
        "main_phrase": phrases[0] if phrases else "unknown",
        "total_volume": 0,
        "avg_difficulty": 0,
        "phrases": phrase_dicts,
    }]
