"""Keyword management: AI generation, file upload, cluster CRUD, CSV export.

Source of truth: UX_TOOLBOX.md section 9, FSM_SPEC.md (KeywordGenerationFSM),
EDGE_CASES.md E01/E03/E16/E36.

Keyword generation is FREE (no token charging).
The wizard sub-flow (products -> geo -> qty -> confirm) is delegated to
routers.shared.keyword_wizard for code sharing with the pipeline readiness flow.
"""

import csv
import html
import io
from typing import Any

import structlog
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from db.client import SupabaseClient
from db.models import Category, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    cancel_kb,
    category_card_kb,
    keywords_cluster_delete_list_kb,
    keywords_cluster_list_kb,
    keywords_confirm_kb,
    keywords_delete_all_confirm_kb,
    keywords_empty_kb,
    keywords_quantity_kb,
    keywords_saved_answers_kb,
    keywords_summary_kb,
    menu_kb,
)
from routers.shared.keyword_wizard import (
    KeywordWizardConfig,
    register_keyword_wizard,
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
    products = State()  # Q1: goods/services (3-1000 chars)
    geography = State()  # Q2: geography (2-200 chars)
    quantity = State()  # Button: 50/100/150/200 + confirm
    fetching = State()  # DataForSEO fetch (progress msg)
    clustering = State()  # AI clustering (progress msg)
    enriching = State()  # DataForSEO enrich (progress msg)
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

    return (
        f"<b>Ключевые фразы</b> — {safe_name}\n\n"
        f"Кластеров: {cluster_count}\n"
        f"Фраз: {total_phrases}\n"
        f"Общий объём: {total_volume:,}/мес"
    )


# ---------------------------------------------------------------------------
# Wizard return callbacks
# ---------------------------------------------------------------------------


async def _return_to_keywords(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    _redis: Any,
) -> None:
    """Return to keywords screen after wizard completion (callback sub-flow)."""
    data = await state.get_data()
    cat_id = int(data.get("kw_cat_id", 0))

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    text = _build_keywords_summary(category)
    clusters = category.keywords or []
    kb = keywords_summary_kb(cat_id) if clusters else keywords_empty_kb(cat_id)

    msg = safe_message(callback)
    if msg:
        await safe_edit_text(msg, text, reply_markup=kb)
    await callback.answer()


async def _return_to_keywords_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    _redis: Any,
) -> None:
    """Return to keywords screen after wizard completion (message sub-flow)."""
    data = await state.get_data()
    cat_id = int(data.get("kw_cat_id", 0))

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        return

    text = _build_keywords_summary(category)
    clusters = category.keywords or []
    kb = keywords_summary_kb(cat_id) if clusters else keywords_empty_kb(cat_id)
    await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# Register keyword wizard
# ---------------------------------------------------------------------------


def _toolbox_qty_kb(data: dict[str, Any]) -> InlineKeyboardMarkup:
    cat_id = int(data.get("kw_cat_id", 0))
    return keywords_quantity_kb(cat_id)


def _toolbox_confirm_kb(data: dict[str, Any]) -> InlineKeyboardMarkup:
    cat_id = int(data.get("kw_cat_id", 0))
    return keywords_confirm_kb(cat_id)


def _toolbox_cancel_nav_kb(data: dict[str, Any]) -> InlineKeyboardMarkup:
    cat_id = int(data.get("kw_cat_id", 0))
    return cancel_kb(f"kw:{cat_id}:gen_cancel")


def _toolbox_error_kb(data: dict[str, Any]) -> InlineKeyboardMarkup:
    cat_id = int(data.get("kw_cat_id", 0))
    return keywords_empty_kb(cat_id)


_toolbox_kw_config = KeywordWizardConfig(
    state_products=KeywordGenerationFSM.products,
    state_geo=KeywordGenerationFSM.geography,
    state_qty=KeywordGenerationFSM.quantity,
    state_generating=KeywordGenerationFSM.fetching,
    prefix="kw",
    log_prefix="toolbox.keywords",
    cancel_cb_fn=lambda data: f"kw:{data.get('kw_cat_id', 0)}:gen_cancel",
    on_done=_return_to_keywords,
    on_done_msg=_return_to_keywords_msg,
    qty_kb_fn=_toolbox_qty_kb,
    confirm_kb_fn=_toolbox_confirm_kb,
    cancel_nav_kb_fn=_toolbox_cancel_nav_kb,
    error_state=None,  # clear state on error
    error_kb_fn=_toolbox_error_kb,
    auto_mode=False,
    saved_answers=True,
    upload_enriches=True,
)

_wizard_handlers = register_keyword_wizard(router, _toolbox_kw_config)


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
# 2. Start generation (with saved answers check) -- entry points
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^kw:\d+:generate$"))
async def start_generation(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start keyword generation -- check for saved answers first."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, project_id = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Check for saved answers in state or category metadata
    saved_data = await state.get_data()
    saved_products = saved_data.get(f"kw_products_{cat_id}")
    saved_geography = saved_data.get(f"kw_geography_{cat_id}")

    if saved_products and saved_geography:
        # Offer to use saved answers
        await state.set_state(KeywordGenerationFSM.products)
        await state.update_data(
            kw_cat_id=cat_id,
            kw_project_id=project_id,
        )

        await safe_edit_text(
            msg,
            f"Найдены сохранённые ответы:\n"
            f"Товары/услуги: <i>{html.escape(saved_products)}</i>\n"
            f"География: <i>{html.escape(saved_geography)}</i>\n\n"
            "Использовать или начать заново?",
            reply_markup=keywords_saved_answers_kb(cat_id),
        )
    else:
        # Start fresh
        await state.set_state(KeywordGenerationFSM.products)
        await state.update_data(
            kw_cat_id=cat_id,
            kw_project_id=project_id,
            kw_mode="configure",
        )

        await safe_edit_text(
            msg,
            "Какие товары или услуги продвигаете?\n<i>Например: кухни на заказ, шкафы-купе, корпусная мебель</i>",
            reply_markup=cancel_kb(f"kw:{cat_id}:gen_cancel"),
        )

    await callback.answer()


@router.callback_query(F.data.regexp(r"^kw:\d+:generate:new$"))
async def start_fresh_generation(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start generation from scratch, ignoring saved answers."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, project_id = await _check_category_ownership(cat_id, user, db)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await state.set_state(KeywordGenerationFSM.products)
    await state.update_data(
        kw_cat_id=cat_id,
        kw_project_id=project_id,
        kw_mode="configure",
    )

    await safe_edit_text(
        msg,
        "Какие товары или услуги продвигаете?\n<i>Например: кухни на заказ, шкафы-купе, корпусная мебель</i>",
        reply_markup=cancel_kb(f"kw:{cat_id}:gen_cancel"),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^kw:\d+:use_saved$"))
async def use_saved_answers(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Skip to quantity selection using saved answers."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["kw_cat_id"])

    # Move saved answers to active
    products = data.get(f"kw_products_{cat_id}", "")
    geography = data.get(f"kw_geography_{cat_id}", "")

    await state.set_state(KeywordGenerationFSM.quantity)
    await state.update_data(
        kw_products=products,
        kw_geography=geography,
    )

    await safe_edit_text(
        msg,
        "Сколько ключевых фраз подобрать?",
        reply_markup=keywords_quantity_kb(cat_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 8. File upload entry point
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

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(KeywordGenerationFSM.products)
    await state.update_data(
        kw_cat_id=cat_id,
        kw_project_id=project_id,
        kw_mode="upload",
    )

    await safe_edit_text(
        msg,
        "Загрузите текстовый файл (.txt) с ключевыми фразами.\n"
        "Каждая фраза на отдельной строке.\n\n"
        f"Максимум: {_MAX_PHRASES} фраз, {_MAX_FILE_SIZE // (1024 * 1024)} МБ.",
        reply_markup=cancel_kb(f"kw:{cat_id}:upl_cancel"),
    )
    await callback.answer()


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

    await safe_edit_text(
        msg,
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
    await safe_edit_text(
        msg,
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

    lines = [
        f"<b>{name}</b>",
        f"Тип: {cluster_type}" if cluster_type else "",
        f"Фраз: {len(phrases)} | Объём: {total_volume:,}/мес\n",
    ]

    for p in phrases[:50]:  # limit display
        phrase = html.escape(p.get("phrase", ""))
        vol = p.get("volume", 0)
        lines.append(f"  \u2022 {phrase} ({vol:,}/мес)")

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
# 12. Delete cluster (two-step: show list -> delete single)
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

    await safe_edit_text(
        msg,
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
    await safe_edit_text(
        msg,
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
        await safe_edit_text(
            msg,
            f"Кластер «{html.escape(removed_name)}» удалён.\n\nВыберите кластер для удаления:",
            reply_markup=keywords_cluster_delete_list_kb(clusters, cat_id, page=1),
        )
    else:
        await safe_edit_text(
            msg,
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

    await safe_edit_text(
        msg,
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
    await safe_edit_text(
        msg,
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
    """Cancel keyword generation via inline button -- return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if category:
        safe_name = html.escape(category.name)
        await safe_edit_text(
            msg,
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
    """Cancel keyword upload via inline button -- return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    _, category, _ = await _check_category_ownership(cat_id, user, db)
    if category:
        safe_name = html.escape(category.name)
        await safe_edit_text(
            msg,
            f"<b>{safe_name}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await safe_edit_text(msg, "Загрузка отменена.", reply_markup=menu_kb())
    await callback.answer()
