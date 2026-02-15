"""Router: ArticlePublishFSM — WordPress article publish flow.

FSM_SPEC.md: ArticlePublishFSM (5 states: confirm_cost, generating,
preview, publishing, regenerating).

Flow: category publish button -> confirm cost -> generate article ->
Telegraph preview -> publish to WordPress.
"""

from __future__ import annotations

import html
import time
from typing import TYPE_CHECKING, Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from bot.exceptions import InsufficientBalanceError
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import (
    ArticlePreview,
    ArticlePreviewCreate,
    ArticlePreviewUpdate,
    PublicationLogCreate,
    User,
)
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from keyboards.publish import (
    article_confirm_kb,
    article_preview_kb,
    insufficient_balance_kb,
    quick_wp_choice_kb,
)
from routers._helpers import guard_callback_message
from services.ai.orchestrator import AIOrchestrator
from services.ai.rate_limiter import RateLimiter
from services.preview import PreviewService
from services.storage import ImageStorage
from services.tokens import TokenService, estimate_article_cost

if TYPE_CHECKING:
    import httpx

log = structlog.get_logger()

router = Router(name="publishing_preview")


# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class ArticlePublishFSM(StatesGroup):
    confirm_cost = State()
    generating = State()
    preview = State()
    publishing = State()
    regenerating = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_article_clusters(keywords: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter keyword clusters to only article-type clusters."""
    if not keywords:
        return []
    # Cluster format has cluster_name
    if keywords[0].get("cluster_name"):
        return [c for c in keywords if c.get("cluster_type") == "article"]
    # Legacy format — all keywords are eligible
    return keywords


def _format_preview_text(preview: ArticlePreview, cost: int) -> str:
    """Format preview message for Telegram."""
    title = html.escape(preview.title or "Без заголовка")
    keyword = html.escape(preview.keyword or "")
    word_count = preview.word_count or 0
    images_count = preview.images_count or 0

    lines = [
        f"<b>{title}</b>",
        "",
        f"Ключевая фраза: {keyword}",
        f"Слов: {word_count}, изображений: {images_count}",
        f"Стоимость: {cost} токенов",
    ]

    if preview.telegraph_url:
        lines.append(f"\nПревью: {preview.telegraph_url}")
    elif preview.content_html:
        # E05: Telegraph down — show first 500 chars
        snippet = preview.content_html[:500]
        lines.append(f"\n{html.escape(snippet)}...")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):publish:wp$"))
async def cb_article_start(
    callback: CallbackQuery, user: User, db: SupabaseClient, state: FSMContext,
) -> None:
    """Start article publish flow for a category (single or auto-detected WP connection)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    # Load category + verify ownership
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # E16: category must have keywords
    if not category.keywords:
        await callback.answer(
            "В категории нет ключевых фраз. Добавьте фразы для генерации.",
            show_alert=True,
        )
        return

    # E40: must have article-type clusters
    article_clusters = _get_article_clusters(category.keywords)
    if not article_clusters:
        await callback.answer(
            "В категории нет кластеров для статей. Добавьте информационные фразы.",
            show_alert=True,
        )
        return

    # Load WP connections
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    connections = await ConnectionsRepository(db, cm).get_by_project_and_platform(
        project.id, "wordpress",
    )
    active_wp = [c for c in connections if c.status == "active"]

    if not active_wp:
        await callback.answer("Нет активных WordPress-подключений.", show_alert=True)
        return

    # E28: multiple WP connections — show choice
    if len(active_wp) > 1:
        await msg.edit_text(
            "Выберите WordPress-подключение для публикации:",
            reply_markup=quick_wp_choice_kb(active_wp, category_id).as_markup(),
        )
        await callback.answer()
        return

    # Single WP connection — proceed to confirmation
    connection = active_wp[0]
    await _show_article_confirm(
        callback, msg, user, db, state, category, project, connection.id,
    )


@router.callback_query(F.data.regexp(r"^category:(\d+):publish:wp:(\d+)$"))
async def cb_article_start_with_conn(
    callback: CallbackQuery, user: User, db: SupabaseClient, state: FSMContext,
) -> None:
    """Start article publish with a specific WP connection (E28 choice or quick publish)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[1])
    connection_id = int(parts[4])

    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # E16 + E40 checks
    if not category.keywords:
        await callback.answer(
            "В категории нет ключевых фраз.",
            show_alert=True,
        )
        return
    article_clusters = _get_article_clusters(category.keywords)
    if not article_clusters:
        await callback.answer(
            "В категории нет кластеров для статей.",
            show_alert=True,
        )
        return

    # Verify connection belongs to this project
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn = await ConnectionsRepository(db, cm).get_by_id(connection_id)
    if not conn or conn.project_id != project.id or conn.platform_type != "wordpress":
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    await _show_article_confirm(
        callback, msg, user, db, state, category, project, connection_id,
    )


async def _show_article_confirm(
    callback: CallbackQuery,
    msg: Any,
    user: User,
    db: SupabaseClient,
    state: FSMContext,
    category: Any,
    project: Any,
    connection_id: int,
) -> None:
    """Common helper to show cost confirmation screen."""
    cost = estimate_article_cost()
    token_svc = TokenService(db, get_settings().admin_id)

    has_balance = await token_svc.check_balance(user.id, cost)
    if not has_balance:
        balance = await token_svc.get_balance(user.id)
        await msg.edit_text(
            token_svc.format_insufficient_msg(cost, balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await callback.answer()
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ArticlePublishFSM.confirm_cost)
    await state.update_data(
        category_id=category.id,
        project_id=project.id,
        connection_id=connection_id,
        cost=cost,
    )

    balance = await token_svc.get_balance(user.id)
    await msg.edit_text(
        f"Сгенерировать SEO-статью?\n\n"
        f"Категория: {html.escape(category.name)}\n"
        f"Стоимость: ~{cost} токенов\n"
        f"Ваш баланс: {balance} токенов",
        reply_markup=article_confirm_kb(category.id, connection_id, cost).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: confirm_cost -> generating -> preview
# ---------------------------------------------------------------------------


@router.callback_query(ArticlePublishFSM.confirm_cost, F.data == "pub:article:confirm")
async def cb_article_confirm(
    callback: CallbackQuery, user: User, db: SupabaseClient, state: FSMContext,
    rate_limiter: RateLimiter,
    ai_orchestrator: AIOrchestrator,
    image_storage: ImageStorage,
    http_client: httpx.AsyncClient,
) -> None:
    """Confirm generation: charge tokens, generate article, show preview."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # E25: rate limit check (raises RateLimitError → global handler)
    await rate_limiter.check(user.id, "text_generation")

    data = await state.get_data()
    cost = data.get("cost", 320)
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    connection_id = data.get("connection_id")

    if not category_id or not project_id or not connection_id:
        await state.clear()
        await callback.answer("Данные сессии потеряны. Начните заново.", show_alert=True)
        return

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_id)

    # Charge tokens
    try:
        await token_svc.charge(
            user_id=user.id,
            amount=cost,
            operation_type="article_generation",
            description=f"Article for category {category_id}",
        )
    except InsufficientBalanceError:
        balance = await token_svc.get_balance(user.id)
        await msg.edit_text(
            token_svc.format_insufficient_msg(cost, balance),
            reply_markup=insufficient_balance_kb().as_markup(),
        )
        await state.clear()
        await callback.answer()
        return
    except Exception:
        log.exception("article_charge_failed", user_id=user.id)
        await msg.edit_text("Ошибка списания токенов. Попробуйте позже.")
        await state.clear()
        await callback.answer()
        return

    await state.set_state(ArticlePublishFSM.generating)
    await callback.answer()

    # Progress: picking keyword
    await msg.edit_text("Подбираю ключевую фразу...")

    # Keyword rotation
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await _refund_and_error(msg, token_svc, user.id, cost, state, "Категория не найдена.")
        return

    pub_repo = PublicationsRepository(db)
    keyword, low_pool = await pub_repo.get_rotation_keyword(
        category_id, category.keywords, content_type="article",
    )
    if not keyword:
        await _refund_and_error(msg, token_svc, user.id, cost, state, "Нет доступных ключевых фраз.")
        return

    await state.update_data(keyword=keyword)

    # Progress: generating article
    start_time = time.monotonic()
    await msg.edit_text(f"Генерирую статью по фразе: {html.escape(keyword)}...")

    # Generate article + images in parallel (real AI pipeline)
    preview_svc = PreviewService(ai_orchestrator, db, image_storage, http_client)
    previews = PreviewsRepository(db)
    try:
        article = await preview_svc.generate_article_content(
            user_id=user.id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
        )
    except Exception:
        log.exception("article_generation_failed", user_id=user.id, keyword=keyword)
        await _refund_and_error(msg, token_svc, user.id, cost, state, "Ошибка генерации статьи.")
        return

    # Create preview record with real content
    try:
        preview = await previews.create(
            ArticlePreviewCreate(
                user_id=user.id,
                project_id=project_id,
                category_id=category_id,
                connection_id=connection_id,
                title=article.title,
                keyword=keyword,
                word_count=article.word_count,
                images_count=article.images_count,
                tokens_charged=cost,
                content_html=article.content_html,
                images=article.stored_images,
            )
        )
    except Exception:
        log.exception("preview_create_failed", user_id=user.id)
        await _refund_and_error(msg, token_svc, user.id, cost, state, "Ошибка создания превью.")
        return

    await state.update_data(preview_id=preview.id)

    # Progress: creating Telegraph preview
    await msg.edit_text("Создаю превью...")

    # Try to create Telegraph page (E05: fallback if fails)
    telegraph_url: str | None = None
    telegraph_path: str | None = None
    try:
        # Import here to avoid circular/heavy imports at module level
        from services.external.telegraph import TelegraphClient

        http_client = callback.bot.session._session  # type: ignore[union-attr]
        telegraph = TelegraphClient(http_client)
        page = await telegraph.create_page(
            title=preview.title or article.title,
            html=preview.content_html or "",
        )
        if page:
            telegraph_url = page.url
            telegraph_path = page.path
    except Exception:
        log.exception("telegraph_create_failed", preview_id=preview.id)

    # Update preview with Telegraph info
    if telegraph_url:
        await previews.update(
            preview.id,
            ArticlePreviewUpdate(
                telegraph_url=telegraph_url,
                telegraph_path=telegraph_path,
            ),
        )
        preview = await previews.get_by_id(preview.id) or preview

    elapsed = int((time.monotonic() - start_time) * 1000)
    log.info(
        "article_generated",
        user_id=user.id,
        preview_id=preview.id,
        keyword=keyword,
        generation_time_ms=elapsed,
    )

    # Show preview
    await state.set_state(ArticlePublishFSM.preview)

    warning = ""
    if low_pool:
        warning = "\nДобавьте ещё фраз для разнообразия контента."

    await msg.edit_text(
        _format_preview_text(preview, cost) + warning,
        reply_markup=article_preview_kb(preview.id, preview.regeneration_count).as_markup(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# FSM: preview -> publish / regen / cancel
# ---------------------------------------------------------------------------


@router.callback_query(ArticlePublishFSM.preview, F.data == "pub:article:publish")
async def cb_article_publish(
    callback: CallbackQuery, user: User, db: SupabaseClient, state: FSMContext,
    ai_orchestrator: AIOrchestrator,
    image_storage: ImageStorage,
    http_client: httpx.AsyncClient,
) -> None:
    """Publish article to WordPress."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    # Guard: transition to publishing (E07)
    await state.set_state(ArticlePublishFSM.publishing)
    await callback.answer()

    data = await state.get_data()
    preview_id = data.get("preview_id")
    connection_id = data.get("connection_id")
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    keyword = data.get("keyword")
    cost = data.get("cost", 320)

    if not preview_id:
        await state.clear()
        await msg.edit_text("Превью не найдено. Начните заново.")
        return

    previews = PreviewsRepository(db)
    preview = await previews.get_by_id(preview_id)
    if not preview or preview.status != "draft":
        await state.clear()
        await msg.edit_text("Превью устарело. Сгенерируйте статью заново.")
        return

    await msg.edit_text("Публикую статью...")

    post_url: str | None = None
    try:
        # Load connection with credentials for WP publish
        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        conn = await ConnectionsRepository(db, cm).get_by_id(int(connection_id or 0))
        if not conn:
            await state.set_state(ArticlePublishFSM.preview)
            await msg.edit_text(
                "Подключение не найдено.",
                reply_markup=article_preview_kb(preview_id, preview.regeneration_count).as_markup(),
            )
            return

        # Publish via PreviewService (downloads images from Storage, uploads to WP)
        preview_svc = PreviewService(ai_orchestrator, db, image_storage, http_client)
        pub_result = await preview_svc.publish_to_wordpress(preview, conn)

        if not pub_result.success:
            raise RuntimeError(f"WP publish failed: {pub_result.error}")

        post_url = pub_result.post_url

        # Update preview status
        await previews.update(preview_id, ArticlePreviewUpdate(status="published"))

        # Create publication log
        pub_repo = PublicationsRepository(db)
        await pub_repo.create_log(
            PublicationLogCreate(
                user_id=user.id,
                project_id=project_id or 0,
                category_id=category_id,
                platform_type="wordpress",
                connection_id=connection_id,
                keyword=keyword,
                content_type="article",
                images_count=preview.images_count or 0,
                post_url=post_url or "",
                word_count=preview.word_count or 0,
                tokens_spent=cost,
            )
        )

        await state.clear()
        await msg.edit_text(
            f"Публикация успешна!\n\n"
            f"Ссылка: {post_url}\n"
            f"Списано: {cost} токенов",
        )
        log.info("article_published", user_id=user.id, preview_id=preview_id, post_url=post_url)

    except Exception:
        log.exception("article_publish_failed", user_id=user.id, preview_id=preview_id)
        await state.set_state(ArticlePublishFSM.preview)
        await msg.edit_text(
            "Ошибка публикации. Попробуйте ещё раз.",
            reply_markup=article_preview_kb(preview_id, preview.regeneration_count).as_markup(),
        )


@router.callback_query(ArticlePublishFSM.preview, F.data == "pub:article:regen")
async def cb_article_regen(
    callback: CallbackQuery, user: User, db: SupabaseClient, state: FSMContext,
    ai_orchestrator: AIOrchestrator,
    image_storage: ImageStorage,
    http_client: httpx.AsyncClient,
) -> None:
    """Regenerate article. First 2 are free, then charged (E10)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    data = await state.get_data()
    preview_id = data.get("preview_id")
    cost = data.get("cost", 320)

    if not preview_id:
        await state.clear()
        await callback.answer("Данные потеряны. Начните заново.", show_alert=True)
        return

    previews = PreviewsRepository(db)
    preview = await previews.get_by_id(preview_id)
    if not preview:
        await state.clear()
        await callback.answer("Превью не найдено.", show_alert=True)
        return

    settings = get_settings()
    max_free = settings.max_regenerations_free

    # E10: paid regeneration after free limit
    if preview.regeneration_count >= max_free:
        token_svc = TokenService(db, settings.admin_id)
        try:
            await token_svc.charge(
                user_id=user.id,
                amount=cost,
                operation_type="article_regeneration",
                description=f"Regen #{preview.regeneration_count + 1} for preview {preview_id}",
            )
        except InsufficientBalanceError:
            balance = await token_svc.get_balance(user.id)
            await callback.answer(
                f"Перегенерация стоит {cost} токенов, у вас {balance}.",
                show_alert=True,
            )
            return
        except Exception:
            log.exception("regen_charge_failed", user_id=user.id)
            await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)
            return

    await state.set_state(ArticlePublishFSM.regenerating)
    await callback.answer()

    await msg.edit_text("Перегенерация статьи...")

    # Increment regeneration count
    new_count = preview.regeneration_count + 1
    keyword = data.get("keyword", preview.keyword or "")

    # Re-generate via real AI pipeline
    preview_svc = PreviewService(ai_orchestrator, db, image_storage, http_client)
    try:
        article = await preview_svc.generate_article_content(
            user_id=user.id,
            project_id=data.get("project_id", 0),
            category_id=data.get("category_id", 0),
            keyword=keyword,
        )
    except Exception:
        log.exception("article_regen_failed", user_id=user.id, preview_id=preview_id)
        await state.set_state(ArticlePublishFSM.preview)
        await msg.edit_text(
            "Ошибка перегенерации.",
            reply_markup=article_preview_kb(preview_id, preview.regeneration_count).as_markup(),
        )
        return

    try:
        await previews.update(
            preview_id,
            ArticlePreviewUpdate(
                regeneration_count=new_count,
                title=article.title,
                word_count=article.word_count,
                images_count=article.images_count,
                content_html=article.content_html,
                images=article.stored_images,
            ),
        )
        updated_preview = await previews.get_by_id(preview_id)
        if not updated_preview:
            updated_preview = preview
    except Exception:
        log.exception("regen_update_failed", preview_id=preview_id)
        await state.set_state(ArticlePublishFSM.preview)
        await msg.edit_text(
            "Ошибка перегенерации.",
            reply_markup=article_preview_kb(preview_id, preview.regeneration_count).as_markup(),
        )
        return

    await state.set_state(ArticlePublishFSM.preview)
    await msg.edit_text(
        _format_preview_text(updated_preview, cost),
        reply_markup=article_preview_kb(preview_id, new_count).as_markup(),
        parse_mode="HTML",
    )
    log.info("article_regenerated", user_id=user.id, preview_id=preview_id, regen_count=new_count)


@router.callback_query(ArticlePublishFSM.preview, F.data == "pub:article:cancel")
async def cb_article_cancel(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Cancel article generation. Preview stays in DB for 24h cleanup."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    category_id = data.get("category_id")
    await state.clear()

    back_cb = f"category:{category_id}:card" if category_id else "menu:main"
    kb = InlineKeyboardBuilder()
    kb.button(text="К категории", callback_data=back_cb)

    await msg.edit_text("Генерация отменена.", reply_markup=kb.as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM guards (E07): block all callbacks during publishing/regenerating
# ---------------------------------------------------------------------------


@router.callback_query(ArticlePublishFSM.publishing)
async def cb_article_publishing_guard(callback: CallbackQuery) -> None:
    """E07: Block all callbacks while publishing is in progress."""
    await callback.answer("Публикация в процессе.", show_alert=True)


@router.callback_query(ArticlePublishFSM.regenerating)
async def cb_article_regen_guard(callback: CallbackQuery) -> None:
    """Block all callbacks while regeneration is in progress."""
    await callback.answer("Перегенерация в процессе.", show_alert=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _refund_and_error(
    msg: Any,
    token_svc: TokenService,
    user_id: int,
    amount: int,
    state: FSMContext,
    error_text: str,
) -> None:
    """Refund tokens on error and clear FSM."""
    try:
        await token_svc.refund(user_id, amount, reason="refund", description="Article generation failed")
    except Exception:
        log.exception("refund_failed_during_error", user_id=user_id, amount=amount)
    await state.clear()
    await msg.edit_text(f"Ошибка: {error_text}\nТокены возвращены.")
