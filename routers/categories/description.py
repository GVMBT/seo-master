"""Category description: AI generation (free), manual input, delete.

Source of truth: UX_TOOLBOX.md section 10, FSM_SPEC.md (DescriptionGenerateFSM).
"""

import html
import time

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.custom_emoji import EMOJI_PROGRESS
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import CategoryServiceFactory
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import (
    cancel_kb,
    category_card_kb,
    description_kb,
    description_review_kb,
    menu_kb,
)
from services.ai.description import DescriptionService
from services.ai.orchestrator import AIOrchestrator

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# FSM definition (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class DescriptionGenerateFSM(StatesGroup):
    review = State()  # Save / Regenerate / Cancel
    manual_input = State()  # Manual text input (10-2000 chars)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _show_description_screen(
    msg: Message,
    category_id: int,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
    user_id: int,
) -> None:
    """Edit message with description screen (UX_TOOLBOX section 10 / 10.3)."""
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(category_id, user_id)
    if not category:
        await safe_edit_text(msg, "Категория не найдена.", reply_markup=menu_kb())
        return

    safe_name = html.escape(category.name)
    has_description = bool(category.description)

    if has_description:
        safe_desc = html.escape(category.description or "")
        text = f"<b>Описание</b> — {safe_name}\n\nТекущее описание:\n<i>{safe_desc}</i>"
    else:
        text = (
            f"<b>Описание</b> — {safe_name}\n\n"
            "Опишите своими словами, чем занимается ваш бизнес в этой категории. "
            "Можно тезисно, через запятую. После ввода можно улучшить текст с помощью ИИ."
        )

    await safe_edit_text(msg, 
        text,
        reply_markup=description_kb(category_id, has_description=has_description),
    )


# ---------------------------------------------------------------------------
# 1. Show description screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:\d+:description$"))
async def show_description(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Show category description (UX_TOOLBOX section 10 / 10.3)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(category_id, user.id)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    await _show_description_screen(msg, category_id, db, category_service_factory, user.id)
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
    category_service_factory: CategoryServiceFactory,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Start AI description generation (free — no token charge)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.update_data(
        last_update_time=time.time(),
        cat_id=cat_id,
        project_id=category.project_id,
        regeneration_count=0,
    )

    # Show progress indicator before AI call
    await safe_edit_text(msg, f"{EMOJI_PROGRESS} Генерирую описание...")
    await callback.answer()

    # Generate description via AI
    try:
        desc_svc = DescriptionService(orchestrator=ai_orchestrator, db=db)
        result = await desc_svc.generate(
            user_id=user.id,
            project_id=category.project_id,
            category_id=cat_id,
        )
        generated_text = result.content if isinstance(result.content, str) else str(result.content)
    except Exception:
        log.exception("description_generation_failed", cat_id=cat_id, user_id=user.id)
        await state.clear()
        await safe_edit_text(msg, "\u26a0\ufe0f Ошибка генерации. Попробуйте ещё раз.", reply_markup=menu_kb())
        return

    # Move to review state
    await state.set_state(DescriptionGenerateFSM.review)
    await state.update_data(
        generated_text=generated_text,
        last_update_time=time.time(),
    )

    safe_text = html.escape(generated_text)
    await safe_edit_text(msg,
        f"Описание сгенерировано:\n\n<i>{safe_text}</i>",
        reply_markup=description_review_kb(cat_id, 0),
    )
    log.info(
        "description_generated",
        cat_id=cat_id,
        user_id=user.id,
    )


# ---------------------------------------------------------------------------
# 4. Review: save
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data.regexp(r"^desc:\d+:review_save$"))
async def review_save(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Save generated description to category."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    generated_text = str(data.get("generated_text", ""))
    await state.clear()

    cat_svc = category_service_factory(db)
    result = await cat_svc.update_description(cat_id, user.id, generated_text)
    if not result:
        await safe_edit_text(msg, "Категория не найдена.", reply_markup=menu_kb())
        await callback.answer()
        return

    log.info("description_saved", cat_id=cat_id, user_id=user.id)
    await _show_description_screen(msg, cat_id, db, category_service_factory, user.id)
    await callback.answer()


# ---------------------------------------------------------------------------
# 6. Review: regenerate
# ---------------------------------------------------------------------------


@router.callback_query(DescriptionGenerateFSM.review, F.data.regexp(r"^desc:\d+:review_regen$"))
async def review_regenerate(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    ai_orchestrator: AIOrchestrator,
) -> None:
    """Regenerate description (free — no token charge)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    project_id = int(data["project_id"])
    regen_count = int(data.get("regeneration_count", 0))

    # Show progress indicator before AI call
    await safe_edit_text(msg, f"{EMOJI_PROGRESS} Генерирую описание...")
    await callback.answer()

    # Regenerate via AI
    try:
        desc_svc = DescriptionService(orchestrator=ai_orchestrator, db=db)
        result = await desc_svc.generate(
            user_id=user.id,
            project_id=project_id,
            category_id=cat_id,
        )
        generated_text = result.content if isinstance(result.content, str) else str(result.content)
    except Exception:
        log.exception("description_regen_failed", cat_id=cat_id, user_id=user.id)
        await callback.answer("Ошибка генерации. Попробуйте ещё раз.", show_alert=True)
        return

    regen_count += 1
    await state.update_data(
        generated_text=generated_text,
        regeneration_count=regen_count,
        last_update_time=time.time(),
    )

    safe_text = html.escape(generated_text)
    await safe_edit_text(msg,
        f"Описание перегенерировано:\n\n<i>{safe_text}</i>",
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


@router.callback_query(DescriptionGenerateFSM.review, F.data.regexp(r"^desc:\d+:review_cancel$"))
async def review_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Cancel review — return to category card. Tokens already spent (not refunded)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    await state.clear()

    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)
    if not category:
        await safe_edit_text(msg, "Категория не найдена.", reply_markup=menu_kb())
        await callback.answer()
        return

    safe_name = html.escape(category.name)
    await safe_edit_text(msg, 
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
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Start manual description input (UX_TOOLBOX section 10.2)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)

    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(DescriptionGenerateFSM.manual_input)
    await state.update_data(last_update_time=time.time(), cat_id=cat_id)

    await safe_edit_text(msg, 
        "Введите описание категории (10\u20132000 символов):",
        reply_markup=cancel_kb(f"desc:{cat_id}:cancel"),
    )
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
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Save manually entered description (10-2000 chars)."""
    text = (message.text or "").strip()

    if len(text) < 10 or len(text) > 2000:
        await message.answer("Описание: от 10 до 2000 символов.")
        return

    data = await state.get_data()
    cat_id = int(data["cat_id"])
    await state.clear()

    cat_svc = category_service_factory(db)
    result = await cat_svc.update_description(cat_id, user.id, text)

    if not result:
        await message.answer("Категория не найдена.", reply_markup=menu_kb())
        return

    log.info("description_manual_saved", cat_id=cat_id, user_id=user.id)

    safe_name = html.escape(result.name)
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
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Clear category description."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_svc = category_service_factory(db)
    cleared = await cat_svc.clear_description(cat_id, user.id)

    if not cleared:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    log.info("description_deleted", cat_id=cat_id, user_id=user.id)
    await _show_description_screen(msg, cat_id, db, category_service_factory, user.id)
    await callback.answer()


# ---------------------------------------------------------------------------
# 11. Cancel handler (inline button)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^desc:\d+:cancel$"))
async def cancel_manual_inline(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    category_service_factory: CategoryServiceFactory,
) -> None:
    """Cancel manual description input via inline button — return to category card."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await state.clear()

    cat_svc = category_service_factory(db)
    category = await cat_svc.get_owned_category(cat_id, user.id)
    if category:
        safe_name = html.escape(category.name)
        await safe_edit_text(msg, 
            f"<b>{safe_name}</b>",
            reply_markup=category_card_kb(cat_id, category.project_id),
        )
        await callback.answer()
        return

    await safe_edit_text(msg, "Ввод описания отменён.", reply_markup=menu_kb())
    await callback.answer()
