"""Exit protection for Article Pipeline steps 4-7 (UX_PIPELINE §8.5, F5.5).

Intercepts "Меню", "Отмена" reply buttons and /cancel command during
protected pipeline states (readiness check through preview).  Shows a
confirmation dialog instead of immediately leaving the pipeline.

The checkpoint in Redis survives — if the user confirms exit, FSM is
cleared but they can resume from Dashboard within 24 hours (E49).
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from cache.client import RedisClient
from db.models import User
from keyboards.pipeline import pipeline_exit_confirm_kb
from routers.publishing.pipeline._common import ArticlePipelineFSM

log = structlog.get_logger()
router = Router()

# States where exit requires confirmation (steps 4-7)
_PROTECTED_STATES = StateFilter(
    ArticlePipelineFSM.readiness_check,
    ArticlePipelineFSM.readiness_keywords_products,
    ArticlePipelineFSM.readiness_keywords_geo,
    ArticlePipelineFSM.readiness_keywords_qty,
    ArticlePipelineFSM.readiness_keywords_generating,
    ArticlePipelineFSM.readiness_description,
    ArticlePipelineFSM.readiness_prices,
    ArticlePipelineFSM.readiness_photos,
    ArticlePipelineFSM.confirm_cost,
    ArticlePipelineFSM.generating,
    ArticlePipelineFSM.preview,
    ArticlePipelineFSM.publishing,
    ArticlePipelineFSM.regenerating,
)


@router.message(
    _PROTECTED_STATES,
    F.text.in_({"Меню", "Отмена"}),
)
async def exit_protection_reply(message: Message) -> None:
    """Intercept reply keyboard 'Меню'/'Отмена' on protected steps."""
    await message.answer(
        "Прервать публикацию?\nПрогресс сохранится на 24 часа.",
        reply_markup=pipeline_exit_confirm_kb(),
    )


@router.message(
    _PROTECTED_STATES,
    Command("cancel"),
)
async def exit_protection_cancel_cmd(message: Message) -> None:
    """Intercept /cancel command on protected steps."""
    await message.answer(
        "Прервать публикацию?\nПрогресс сохранится на 24 часа.",
        reply_markup=pipeline_exit_confirm_kb(),
    )


@router.callback_query(F.data == "pipeline:article:exit_confirm")
async def exit_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
) -> None:
    """User confirmed exit — clear FSM, keep checkpoint for resume."""
    await state.clear()
    # Checkpoint survives in Redis — user can resume from Dashboard
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        await callback.message.edit_text("Pipeline приостановлен. Можете продолжить с Dashboard.")
    await callback.answer()
    log.info("pipeline.exit_confirmed", user_id=user.id)


@router.callback_query(F.data == "pipeline:article:exit_cancel")
async def exit_cancel(callback: CallbackQuery) -> None:
    """User chose to continue — dismiss confirmation dialog."""
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        try:
            await callback.message.delete()
        except Exception:
            log.debug("exit_cancel.delete_failed")
    await callback.answer("Продолжаем!")
