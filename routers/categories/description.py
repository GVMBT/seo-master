"""Category description: AI generation, manual input, delete.

Source of truth: UX_TOOLBOX.md section 10, FSM_SPEC.md (DescriptionGenerateFSM),
EDGE_CASES.md E01 (balance check).
"""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.models import Category, CategoryUpdate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    category_card_kb,
    description_confirm_kb,
    description_kb,
    description_review_kb,
)
from services.tokens import COST_DESCRIPTION, TokenService

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# FSM definition (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class DescriptionGenerateFSM(StatesGroup):
    confirm = State()  # Cost confirmation (20 tokens)
    review = State()  # Save / Regenerate / Cancel
    manual_input = State()  # Manual text input (10-2000 chars)


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


async def _show_description_screen(
    msg: Message,
    category_id: int,
    db: SupabaseClient,
) -> None:
    """Edit message with description screen (UX_TOOLBOX section 10 / 10.3)."""
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)
    if not category:
        await msg.edit_text("Категория не найдена.")
        return

    safe_name = html.escape(category.name)
    has_description = bool(category.description)

    if has_description:
        safe_desc = html.escape(category.description or "")
        text = f"<b>Описание</b> — {safe_name}\n\nТекущее описание:\n<i>{safe_desc}</i>"
    else:
        text = f"<b>Описание</b> — {safe_name}\n\nОписание не заполнено. Добавьте для лучшего качества статей."

    await msg.edit_text(
        text,
        reply_markup=description_kb(category_id, has_description=has_description),
    )


async def _generate_description_stub(
    category_name: str,
    company_name: str,
    specialization: str,
) -> str:
    """Placeholder for AI description generation.

    TODO Phase 10: wire AIOrchestrator and call DescriptionService.generate().
    """
    return (
        f"{company_name} — {specialization}. "
        f"Категория «{category_name}» включает полный спектр товаров и услуг "
        "для наших клиентов. Мы гарантируем индивидуальный подход, "
        "высокое качество и конкурентные цены."
    )


# ---------------------------------------------------------------------------
# 1. Show description screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:description$"))
async def show_description(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show category description (UX_TOOLBOX section 10 / 10.3)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(category_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await _show_description_screen(callback.message, category_id, db)
    await callback.answer()


# ---------------------------------------------------------------------------
# 2. Start AI generation
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^desc:\d+:generate$"))
async def start_generate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start AI description generation — show cost confirmation."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, project_id = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    settings = get_settings()
    token_service = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_service.get_balance(user.id)

    await state.set_state(DescriptionGenerateFSM.confirm)
    await state.update_data(
        last_update_time=time.time(),
        cat_id=cat_id,
        project_id=project_id,
        regeneration_count=0,
    )

    safe_name = html.escape(getattr(category, "name", ""))
    await callback.message.edit_text(
        f"Сгенерировать описание для «{safe_name}»?\nСтоимость: {COST_DESCRIPTION} токенов. Баланс: {balance}.",
        reply_markup=description_confirm_kb(cat_id, balance),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 3. Confirm generation
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.confirm, F.data == "desc:confirm:yes")
async def confirm_generate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Confirm AI generation — E01 balance check, charge, generate."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    settings = get_settings()
    token_service = TokenService(db=db, admin_ids=settings.admin_ids)

    # E01: balance check
    has_balance = await token_service.check_balance(user.id, COST_DESCRIPTION)
    if not has_balance:
        balance = await token_service.get_balance(user.id)
        msg = token_service.format_insufficient_msg(COST_DESCRIPTION, balance)
        await callback.message.edit_text(msg)
        await state.clear()
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    project_id = int(data["project_id"])

    # Charge tokens
    new_balance = await token_service.charge(
        user_id=user.id,
        amount=COST_DESCRIPTION,
        operation_type="description",
        description=f"Генерация описания (категория #{cat_id})",
    )

    # Generate description
    # TODO Phase 10: wire AIOrchestrator
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        # Refund on error
        await token_service.refund(
            user_id=user.id,
            amount=COST_DESCRIPTION,
            reason="refund",
            description=f"Возврат за описание (категория #{cat_id} не найдена)",
        )
        await state.clear()
        await callback.message.edit_text("Категория не найдена.")
        await callback.answer()
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    company_name = project.company_name if project else "Компания"
    specialization = project.specialization if project else ""

    try:
        generated_text = await _generate_description_stub(
            category_name=category.name,
            company_name=company_name,
            specialization=specialization,
        )
    except Exception:
        log.exception("description_generation_failed", cat_id=cat_id, user_id=user.id)
        await token_service.refund(
            user_id=user.id,
            amount=COST_DESCRIPTION,
            reason="refund",
            description=f"Возврат за описание (ошибка генерации, категория #{cat_id})",
        )
        await state.clear()
        await callback.message.edit_text("Ошибка генерации описания. Токены возвращены.")
        await callback.answer()
        return

    # Move to review state
    await state.set_state(DescriptionGenerateFSM.review)
    await state.update_data(
        generated_text=generated_text,
        last_update_time=time.time(),
    )

    regen_count = int(data.get("regeneration_count", 0))
    safe_text = html.escape(generated_text)
    await callback.message.edit_text(
        f"Описание сгенерировано (списано {COST_DESCRIPTION} токенов):\n\n<i>{safe_text}</i>",
        reply_markup=description_review_kb(cat_id, regen_count),
    )
    await callback.answer()
    log.info(
        "description_generated",
        cat_id=cat_id,
        user_id=user.id,
        balance=new_balance,
    )


# ---------------------------------------------------------------------------
# 4. Cancel generation (from confirm screen)
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.confirm, F.data == "desc:confirm:no")
async def cancel_generate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel generation — return to category card."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    await state.clear()

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await callback.message.edit_text("Категория не найдена.")
        await callback.answer()
        return

    safe_name = html.escape(category.name)
    await callback.message.edit_text(
        f"<b>{safe_name}</b>",
        reply_markup=category_card_kb(cat_id, category.project_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 5. Review: save
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data == "desc:review:save")
async def review_save(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Save generated description to category."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    generated_text = str(data.get("generated_text", ""))
    await state.clear()

    cats_repo = CategoriesRepository(db)
    await cats_repo.update(cat_id, CategoryUpdate(description=generated_text))

    log.info("description_saved", cat_id=cat_id, user_id=user.id)
    await _show_description_screen(callback.message, cat_id, db)
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. Review: regenerate
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data == "desc:review:regen")
async def review_regenerate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Regenerate description. First 2 are free, then charge again (FSM_SPEC 2.2)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    project_id = int(data["project_id"])
    regen_count = int(data.get("regeneration_count", 0))

    settings = get_settings()
    token_service = TokenService(db=db, admin_ids=settings.admin_ids)

    # After 2 free regenerations, charge again (E10)
    if regen_count >= 2:
        has_balance = await token_service.check_balance(user.id, COST_DESCRIPTION)
        if not has_balance:
            balance = await token_service.get_balance(user.id)
            await callback.answer(
                token_service.format_insufficient_msg(COST_DESCRIPTION, balance),
                show_alert=True,
            )
            return

        await token_service.charge(
            user_id=user.id,
            amount=COST_DESCRIPTION,
            operation_type="description",
            description=f"Перегенерация описания (категория #{cat_id}, попытка {regen_count + 1})",
        )

    # Regenerate
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await state.clear()
        await callback.message.edit_text("Категория не найдена.")
        await callback.answer()
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    company_name = project.company_name if project else "Компания"
    specialization = project.specialization if project else ""

    try:
        generated_text = await _generate_description_stub(
            category_name=category.name,
            company_name=company_name,
            specialization=specialization,
        )
    except Exception:
        log.exception("description_regen_failed", cat_id=cat_id, user_id=user.id)
        if regen_count >= 2:
            await token_service.refund(
                user_id=user.id,
                amount=COST_DESCRIPTION,
                reason="refund",
                description=f"Возврат за перегенерацию описания (категория #{cat_id})",
            )
        await callback.answer("Ошибка генерации. Попробуйте ещё раз.", show_alert=True)
        return

    regen_count += 1
    await state.update_data(
        generated_text=generated_text,
        regeneration_count=regen_count,
        last_update_time=time.time(),
    )

    safe_text = html.escape(generated_text)
    cost_note = f" (списано {COST_DESCRIPTION} токенов)" if regen_count > 2 else ""
    await callback.message.edit_text(
        f"Описание перегенерировано{cost_note}:\n\n<i>{safe_text}</i>",
        reply_markup=description_review_kb(cat_id, regen_count),
    )
    await callback.answer()
    log.info(
        "description_regenerated",
        cat_id=cat_id,
        user_id=user.id,
        regen_count=regen_count,
    )


# ---------------------------------------------------------------------------
# 7. Review: cancel
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data == "desc:review:cancel")
async def review_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Cancel review — return to category card. Tokens already spent (not refunded)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    await state.clear()

    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await callback.message.edit_text("Категория не найдена.")
        await callback.answer()
        return

    safe_name = html.escape(category.name)
    await callback.message.edit_text(
        f"<b>{safe_name}</b>",
        reply_markup=category_card_kb(cat_id, category.project_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# 8. Start manual input
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^desc:\d+:manual$"))
async def start_manual(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Start manual description input (UX_TOOLBOX section 10.2)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(DescriptionGenerateFSM.manual_input)
    await state.update_data(last_update_time=time.time(), cat_id=cat_id)

    await callback.message.edit_text("Введите описание категории (10\u20132000 символов):")
    await callback.answer()


# ---------------------------------------------------------------------------
# 9. Process manual text
# ---------------------------------------------------------------------------


@router.message(DescriptionGenerateFSM.manual_input, F.text)
async def process_manual(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Save manually entered description (10-2000 chars)."""
    text = (message.text or "").strip()

    if len(text) < 10 or len(text) > 2000:
        await message.answer("Описание: от 10 до 2000 символов.")
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    await state.clear()

    cats_repo = CategoriesRepository(db)
    await cats_repo.update(cat_id, CategoryUpdate(description=text))

    log.info("description_manual_saved", cat_id=cat_id, user_id=user.id)

    # Show updated description screen (as new message since user sent text)
    category = await cats_repo.get_by_id(cat_id)
    if not category:
        await message.answer("Категория не найдена.")
        return

    safe_name = html.escape(category.name)
    safe_desc = html.escape(text)
    await message.answer(
        f"<b>Описание</b> — {safe_name}\n\nТекущее описание:\n<i>{safe_desc}</i>",
        reply_markup=description_kb(cat_id, has_description=True),
    )


# ---------------------------------------------------------------------------
# 10. Delete description
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^desc:\d+:delete$"))
async def delete_description(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Clear category description."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    _, category, _ = await _check_category_ownership(cat_id, user, db)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # Clear description — bypass exclude_none by calling table directly
    await db.table("categories").update({"description": None}).eq("id", cat_id).execute()

    log.info("description_deleted", cat_id=cat_id, user_id=user.id)
    await _show_description_screen(callback.message, cat_id, db)
    await callback.answer()
