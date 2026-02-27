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
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.helpers import safe_message
from cache.client import RedisClient
from db.models import User
from keyboards.pipeline import pipeline_exit_confirm_kb, social_exit_confirm_kb
from routers.publishing.pipeline._common import ArticlePipelineFSM, SocialPipelineFSM

log = structlog.get_logger()
router = Router()

# States where exit requires confirmation (steps 4-7).
# Excludes generating/publishing/regenerating — those have active coroutines;
# clearing FSM mid-flight causes race conditions (M4).
_ARTICLE_PROTECTED = StateFilter(
    ArticlePipelineFSM.readiness_check,
    ArticlePipelineFSM.readiness_keywords_products,
    ArticlePipelineFSM.readiness_keywords_geo,
    ArticlePipelineFSM.readiness_keywords_qty,
    ArticlePipelineFSM.readiness_keywords_generating,
    ArticlePipelineFSM.readiness_description,
    ArticlePipelineFSM.readiness_prices,
    ArticlePipelineFSM.readiness_photos,
    ArticlePipelineFSM.confirm_cost,
    ArticlePipelineFSM.preview,
)

_SOCIAL_PROTECTED = StateFilter(
    SocialPipelineFSM.readiness_check,
    SocialPipelineFSM.readiness_keywords_products,
    SocialPipelineFSM.readiness_keywords_geo,
    SocialPipelineFSM.readiness_keywords_qty,
    SocialPipelineFSM.readiness_keywords_generating,
    SocialPipelineFSM.readiness_description,
    SocialPipelineFSM.confirm_cost,
    SocialPipelineFSM.review,
    SocialPipelineFSM.cross_post_review,
)


@router.message(
    _ARTICLE_PROTECTED,
    F.text.in_({"Меню", "Отмена"}),
)
async def exit_protection_reply_article(message: Message) -> None:
    """Intercept reply keyboard 'Меню'/'Отмена' on protected article steps."""
    await message.answer(
        "Прервать публикацию?\nПрогресс сохранится на 24 часа.",
        reply_markup=pipeline_exit_confirm_kb(),
    )


@router.message(
    _SOCIAL_PROTECTED,
    F.text.in_({"Меню", "Отмена"}),
)
async def exit_protection_reply_social(message: Message) -> None:
    """Intercept reply keyboard 'Меню'/'Отмена' on protected social steps."""
    await message.answer(
        "Прервать публикацию?\nПрогресс сохранится на 24 часа.",
        reply_markup=social_exit_confirm_kb(),
    )


@router.message(
    _ARTICLE_PROTECTED,
    Command("cancel"),
)
async def exit_protection_cancel_cmd_article(message: Message) -> None:
    """Intercept /cancel command on protected article steps."""
    await message.answer(
        "Прервать публикацию?\nПрогресс сохранится на 24 часа.",
        reply_markup=pipeline_exit_confirm_kb(),
    )


@router.message(
    _SOCIAL_PROTECTED,
    Command("cancel"),
)
async def exit_protection_cancel_cmd_social(message: Message) -> None:
    """Intercept /cancel command on protected social steps."""
    await message.answer(
        "Прервать публикацию?\nПрогресс сохранится на 24 часа.",
        reply_markup=social_exit_confirm_kb(),
    )


@router.callback_query(F.data.in_({"pipeline:article:exit_confirm", "pipeline:social:exit_confirm"}))
async def exit_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,  # checkpoint intentionally retained for resume
) -> None:
    """User confirmed exit — clear FSM, keep checkpoint for resume."""
    await state.clear()
    # Checkpoint survives in Redis — user can resume from Dashboard
    msg = safe_message(callback)
    if msg:
        await msg.edit_text("Pipeline приостановлен. Можете продолжить с Dashboard.")
    await callback.answer()
    log.info("pipeline.exit_confirmed", user_id=user.id)


@router.callback_query(F.data.in_({"pipeline:article:exit_cancel", "pipeline:social:exit_cancel"}))
async def exit_cancel(callback: CallbackQuery) -> None:
    """User chose to continue — dismiss confirmation dialog."""
    msg = safe_message(callback)
    if msg:
        try:
            await msg.delete()
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound):  # fmt: skip
            log.debug("exit_cancel.delete_failed")
    await callback.answer("Продолжаем!")
