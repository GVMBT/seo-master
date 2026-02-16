"""Router: category description generation (DescriptionGenerateFSM)."""

import html

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.category import description_confirm_kb, description_existing_kb, description_result_kb
from keyboards.inline import category_card_kb
from routers._helpers import guard_callback_message
from services.ai.description import DescriptionService
from services.ai.orchestrator import AIOrchestrator
from services.tokens import COST_DESCRIPTION, TokenService

log = structlog.get_logger()

router = Router(name="categories_description")


# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class DescriptionGenerateFSM(StatesGroup):
    confirm = State()
    review = State()


# ---------------------------------------------------------------------------
# Ownership helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Entry: category:{id}:description
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):description$"))
async def cb_description_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show current description or offer to generate."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat = await CategoriesRepository(db).get_by_id(category_id)
    if not cat:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(cat.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    if cat.description:
        preview = cat.description[:500]
        text = f"<b>Описание категории «{html.escape(cat.name)}»</b>\n\n{html.escape(preview)}"
        await msg.edit_text(text, reply_markup=description_existing_kb(cat.id).as_markup())
    else:
        interrupted = await ensure_no_active_fsm(state)
        if interrupted:
            await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")
        await state.set_state(DescriptionGenerateFSM.confirm)
        await state.update_data(category_id=cat.id, project_id=project.id, regen_count=0)
        text = (
            f"Категория «{html.escape(cat.name)}» пока без описания.\n\n"
            f"Сгенерировать описание? Стоимость: {COST_DESCRIPTION} токенов."
        )
        await msg.edit_text(text, reply_markup=description_confirm_kb(cat.id, COST_DESCRIPTION).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Re-generation entry from existing description
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):description:regen$"))
async def cb_description_regen_entry(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """Re-generate description for a category that already has one."""
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

    await state.set_state(DescriptionGenerateFSM.confirm)
    await state.update_data(category_id=cat_id, project_id=project_id, regen_count=0)

    text = f"Перегенерировать описание? Стоимость: {COST_DESCRIPTION} токенов."
    await msg.edit_text(text, reply_markup=description_confirm_kb(cat_id, COST_DESCRIPTION).as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Confirm generation
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.confirm, F.data == "desc:confirm")
async def cb_description_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Charge tokens and generate description."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    cat_id = data.get("category_id")
    project_id = data.get("project_id")

    if not cat_id or not project_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_ids)

    # Check balance (E38)
    if not await token_svc.check_balance(user.id, COST_DESCRIPTION):
        await callback.answer(
            token_svc.format_insufficient_msg(COST_DESCRIPTION, user.balance),
            show_alert=True,
        )
        return

    await msg.edit_text("Генерирую описание...")
    await callback.answer()

    try:
        await token_svc.charge(user.id, COST_DESCRIPTION, "description", description="Category description")
        svc = DescriptionService(ai_orchestrator, db)
        result = await svc.generate(user.id, project_id, cat_id)
        generated_text = str(result.content) if result.content else ""
    except Exception:
        log.exception("description_generation_failed", user_id=user.id, category_id=cat_id)
        try:
            await token_svc.refund(user.id, COST_DESCRIPTION, reason="description_error")
        except Exception:
            log.exception("description_refund_failed", user_id=user.id)
        await msg.edit_text("Не удалось сгенерировать описание. Токены возвращены.")
        await state.clear()
        return

    regen_count = data.get("regen_count", 0)
    await state.set_state(DescriptionGenerateFSM.review)
    await state.update_data(generated_text=generated_text, regen_count=regen_count)

    preview = generated_text[:500]
    text = f"<b>Сгенерированное описание:</b>\n\n{html.escape(preview)}"
    await msg.edit_text(text, reply_markup=description_result_kb(cat_id, regen_count).as_markup())


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data == "desc:save")
async def cb_description_save(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Save generated description to category."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    cat_id = data.get("category_id")
    generated_text = data.get("generated_text", "")

    if not cat_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    repo = CategoriesRepository(db)
    category = await repo.update(cat_id, CategoryUpdate(description=generated_text))
    await state.clear()

    if category:
        from routers.categories.manage import _format_category_card

        await msg.edit_text(
            f"Описание сохранено!\n\n{_format_category_card(category)}",
            reply_markup=category_card_kb(category).as_markup(),
        )
    else:
        from keyboards.errors import error_not_found_kb

        await msg.edit_text("Категория не найдена.", reply_markup=error_not_found_kb().as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Regenerate
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data == "desc:regen")
async def cb_description_regen(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Re-generate description. 2 free, then paid."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    regen_count = data.get("regen_count", 0) + 1
    cat_id = data.get("category_id")
    project_id = data.get("project_id")

    if not cat_id or not project_id:
        await state.clear()
        await callback.answer("Сессия истекла.", show_alert=True)
        return

    settings = get_settings()
    token_svc = TokenService(db, settings.admin_ids)

    # 2 free regenerations, then paid
    if regen_count > 2 and not await token_svc.check_balance(user.id, COST_DESCRIPTION):
        await callback.answer(
            token_svc.format_insufficient_msg(COST_DESCRIPTION, user.balance),
            show_alert=True,
        )
        return

    await msg.edit_text("Перегенерирую описание...")
    await callback.answer()

    try:
        if regen_count > 2:
            await token_svc.charge(user.id, COST_DESCRIPTION, "description", description="Description regen (paid)")
        svc = DescriptionService(ai_orchestrator, db)
        result = await svc.generate(user.id, project_id, cat_id)
        generated_text = str(result.content) if result.content else ""
    except Exception:
        log.exception("description_regen_failed", user_id=user.id, category_id=cat_id)
        if regen_count > 2:
            try:
                await token_svc.refund(user.id, COST_DESCRIPTION, reason="description_regen_error")
            except Exception:
                log.exception("description_regen_refund_failed", user_id=user.id)
        await msg.edit_text("Не удалось перегенерировать описание.")
        return

    await state.update_data(generated_text=generated_text, regen_count=regen_count)

    preview = generated_text[:500]
    text = f"<b>Сгенерированное описание:</b>\n\n{html.escape(preview)}"
    await msg.edit_text(text, reply_markup=description_result_kb(cat_id, regen_count).as_markup())
