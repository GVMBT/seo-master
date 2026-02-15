"""Router: category review generation (ReviewGenerationFSM)."""

import html

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.category import review_confirm_kb, review_existing_kb, review_quantity_kb, review_result_kb
from keyboards.inline import category_card_kb
from routers._helpers import guard_callback_message
from services.ai.orchestrator import AIOrchestrator
from services.ai.reviews import ReviewService
from services.tokens import COST_REVIEW_EACH, TokenService

log = structlog.get_logger()

router = Router(name="categories_reviews")


# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class ReviewGenerationFSM(StatesGroup):
    quantity = State()
    confirm_cost = State()
    generating = State()
    review = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_reviews(reviews: list[dict]) -> str:  # type: ignore[type-arg]
    """Format reviews list for display."""
    lines: list[str] = []
    for i, r in enumerate(reviews, 1):
        stars = "+" * r.get("rating", 5)
        author = html.escape(r.get("author", "Аноним"))
        text = html.escape(r.get("text", "")[:200])
        pros = html.escape(r.get("pros", ""))
        cons = html.escape(r.get("cons", ""))
        parts = [f"<b>{i}. {author}</b> [{stars}]", text]
        if pros:
            parts.append(f"<i>Плюсы:</i> {pros}")
        if cons:
            parts.append(f"<i>Минусы:</i> {cons}")
        lines.append("\n".join(parts))
    return "\n\n".join(lines)


async def _get_cat_with_owner_check(
    category_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery
) -> tuple[int, int] | None:
    """Verify category ownership. Returns (category_id, project_id) or None."""
    cat = await CategoriesRepository(db).get_by_id(category_id)
    if not cat:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    project = await ProjectsRepository(db).get_by_id(cat.project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return None
    return cat.id, project.id


def _make_token_service(db: SupabaseClient) -> TokenService:
    """Create TokenService with admin_id from settings."""
    return TokenService(db, get_settings().admin_id)


async def _run_generation(
    ai_orchestrator: AIOrchestrator, db: SupabaseClient,
    user_id: int, project_id: int, category_id: int, quantity: int,
) -> list[dict]:  # type: ignore[type-arg]
    """Delegate review generation to ReviewService. Returns list of reviews."""
    svc = ReviewService(ai_orchestrator, db)
    result = await svc.generate(user_id, project_id, category_id, quantity)

    reviews: list[dict] = []  # type: ignore[type-arg]
    if isinstance(result.content, dict):
        reviews = result.content.get("reviews", [])
    elif isinstance(result.content, list):
        reviews = result.content
    return reviews


def _truncate_review_text(text: str, limit: int = 4000) -> str:
    """Truncate review text to Telegram message limit."""
    return text[:limit] + "..." if len(text) > limit else text


# ---------------------------------------------------------------------------
# Entry: category:{id}:reviews
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):reviews$"))
async def cb_reviews_start(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """Show existing reviews or offer to generate."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, project_id = result

    cat = await CategoriesRepository(db).get_by_id(cat_id)
    if cat and cat.reviews:
        text = f"<b>Отзывы ({len(cat.reviews)} шт.)</b>\n\n{_format_reviews(cat.reviews[:5])}"
        text = _truncate_review_text(text)
        await msg.edit_text(text, reply_markup=review_existing_kb(cat_id, len(cat.reviews)).as_markup())
    else:
        interrupted = await ensure_no_active_fsm(state)
        if interrupted:
            await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")
        await state.set_state(ReviewGenerationFSM.quantity)
        await state.update_data(category_id=cat_id, project_id=project_id)
        await msg.edit_text(
            "Сколько отзывов сгенерировать?",
            reply_markup=review_quantity_kb(cat_id).as_markup(),
        )
    await callback.answer()


# ---------------------------------------------------------------------------
# Re-generation entry from existing reviews
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):reviews:regen$"))
async def cb_reviews_regen_entry(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """Start review regeneration for a category that already has reviews."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    result = await _get_cat_with_owner_check(category_id, user.id, db, callback)
    if not result:
        return
    cat_id, project_id = result

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ReviewGenerationFSM.quantity)
    await state.update_data(category_id=cat_id, project_id=project_id, regen_count=0)
    await msg.edit_text(
        "Сколько отзывов сгенерировать?",
        reply_markup=review_quantity_kb(cat_id).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Quantity selection
# ---------------------------------------------------------------------------


@router.callback_query(ReviewGenerationFSM.quantity, F.data.regexp(r"^review:qty:(\d+):(\d+)$"))
async def cb_review_quantity(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """User selected quantity. Show cost confirmation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[2])
    quantity = int(parts[3])
    cost = quantity * COST_REVIEW_EACH

    token_svc = _make_token_service(db)

    # E38: balance check
    if not await token_svc.check_balance(user.id, cost):
        await callback.answer(
            token_svc.format_insufficient_msg(cost, user.balance),
            show_alert=True,
        )
        return

    await state.set_state(ReviewGenerationFSM.confirm_cost)
    await state.update_data(quantity=quantity, cost=cost)

    text = f"Генерация {quantity} отзывов.\nСтоимость: {cost} токенов."
    await msg.edit_text(text, reply_markup=review_confirm_kb(cat_id, cost).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Confirm & generate
# ---------------------------------------------------------------------------


@router.callback_query(ReviewGenerationFSM.confirm_cost, F.data == "review:confirm")
async def cb_review_confirm(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Charge tokens and generate reviews via ReviewService."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    cat_id = data.get("category_id")
    project_id = data.get("project_id")
    quantity = data.get("quantity", 3)
    cost = data.get("cost", quantity * COST_REVIEW_EACH)

    if not cat_id or not project_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    await state.set_state(ReviewGenerationFSM.generating)
    await msg.edit_text(f"Генерирую {quantity} отзывов...")
    await callback.answer()

    token_svc = _make_token_service(db)

    try:
        await token_svc.charge(user.id, cost, "review", description=f"{quantity} reviews")
        reviews = await _run_generation(ai_orchestrator, db, user.id, project_id, cat_id, quantity)
    except Exception:
        log.exception("review_generation_failed", user_id=user.id, category_id=cat_id)
        try:
            await token_svc.refund(user.id, cost, reason="review_error")
        except Exception:
            log.exception("review_refund_failed", user_id=user.id)
        await msg.edit_text("Не удалось сгенерировать отзывы. Токены возвращены.")
        await state.clear()
        return

    regen_count = data.get("regen_count", 0)
    await state.set_state(ReviewGenerationFSM.review)
    await state.update_data(generated_reviews=reviews, regen_count=regen_count)

    text = f"<b>Сгенерированные отзывы ({len(reviews)} шт.):</b>\n\n{_format_reviews(reviews[:5])}"
    text = _truncate_review_text(text)
    await msg.edit_text(text, reply_markup=review_result_kb(cat_id, regen_count).as_markup())


# ---------------------------------------------------------------------------
# E07: generating guard
# ---------------------------------------------------------------------------


@router.callback_query(ReviewGenerationFSM.generating)
async def cb_review_generating_guard(callback: CallbackQuery) -> None:
    """Guard: generation in progress."""
    await callback.answer("Генерация в процессе. Подождите.", show_alert=True)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


@router.callback_query(ReviewGenerationFSM.review, F.data == "review:save")
async def cb_review_save(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Save generated reviews to category via CategoriesRepository."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    cat_id = data.get("category_id")
    reviews = data.get("generated_reviews", [])

    if not cat_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    repo = CategoriesRepository(db)
    category = await repo.update_reviews(cat_id, reviews)
    await state.clear()

    if category:
        from routers.categories.manage import _format_category_card

        await msg.edit_text(
            f"Отзывы сохранены ({len(reviews)} шт.)!\n\n{_format_category_card(category)}",
            reply_markup=category_card_kb(category).as_markup(),
        )
    else:
        await msg.edit_text("Категория не найдена.")
    await callback.answer()


# ---------------------------------------------------------------------------
# Regenerate
# ---------------------------------------------------------------------------


@router.callback_query(ReviewGenerationFSM.review, F.data == "review:regen")
async def cb_review_regen(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Re-generate reviews. 2 free, then paid."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    regen_count = data.get("regen_count", 0) + 1
    cat_id = data.get("category_id")
    project_id = data.get("project_id")
    quantity = data.get("quantity", 3)
    cost = quantity * COST_REVIEW_EACH

    if not cat_id or not project_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    token_svc = _make_token_service(db)

    if regen_count > 2 and not await token_svc.check_balance(user.id, cost):
        await callback.answer(
            token_svc.format_insufficient_msg(cost, user.balance),
            show_alert=True,
        )
        return

    await state.set_state(ReviewGenerationFSM.generating)
    await msg.edit_text(f"Перегенерирую {quantity} отзывов...")
    await callback.answer()

    try:
        if regen_count > 2:
            await token_svc.charge(user.id, cost, "review", description=f"Review regen (paid, {quantity})")
        reviews = await _run_generation(ai_orchestrator, db, user.id, project_id, cat_id, quantity)
    except Exception:
        log.exception("review_regen_failed", user_id=user.id, category_id=cat_id)
        if regen_count > 2:
            try:
                await token_svc.refund(user.id, cost, reason="review_regen_error")
            except Exception:
                log.exception("review_regen_refund_failed", user_id=user.id)
        await msg.edit_text("Не удалось перегенерировать отзывы.")
        await state.set_state(ReviewGenerationFSM.review)
        return

    await state.set_state(ReviewGenerationFSM.review)
    await state.update_data(generated_reviews=reviews, regen_count=regen_count)

    text = f"<b>Сгенерированные отзывы ({len(reviews)} шт.):</b>\n\n{_format_reviews(reviews[:5])}"
    text = _truncate_review_text(text)
    await msg.edit_text(text, reply_markup=review_result_kb(cat_id, regen_count).as_markup())
