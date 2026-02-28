"""Social Pipeline readiness check -- step 4 (F6.3).

Simplified readiness for social posts: keywords + description only (no prices/images).
Sub-flows: keywords (auto/configure/upload), description (AI/manual).

UX: UX_PIPELINE.md SS5.4 (social readiness).
FSM: SocialPipelineFSM (28 states, FSM_SPEC.md SS2.2).
Rules: .claude/rules/pipeline.md -- inline handlers, NOT FSM delegation.

Common keyword/description/navigation sub-flows are registered via
register_readiness_subflows() from _readiness_common.py.
Social-specific checklist/show functions and done handler remain here.
"""

from __future__ import annotations

import html
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.helpers import safe_message
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import User
from keyboards.pipeline import social_readiness_kb
from routers.publishing.pipeline._common import (
    SocialPipelineFSM,
    clear_checkpoint,
    save_checkpoint,
)
from routers.publishing.pipeline._readiness_common import (
    ReadinessConfig,
    register_readiness_subflows,
)
from services.readiness import ReadinessReport, ReadinessService
from services.tokens import TokenService

log = structlog.get_logger()
router = Router()

# Total step count for social pipeline (displayed in step headers)
_TOTAL_STEPS = 5


# ---------------------------------------------------------------------------
# Checklist display helpers
# ---------------------------------------------------------------------------


def _build_social_checklist_text(report: ReadinessReport, fsm_data: dict[str, Any]) -> str:
    """Build social readiness checklist text (UX_PIPELINE.md SS5.4).

    Simplified vs article: only keywords + description, no prices/images.
    """
    project_name = html.escape(fsm_data.get("project_name", ""))
    category_name = html.escape(fsm_data.get("category_name", ""))
    platform_type = fsm_data.get("platform_type", "")
    identifier = html.escape(fsm_data.get("connection_identifier", ""))

    platform_labels = {
        "telegram": "Телеграм",
        "vk": "ВКонтакте",
        "pinterest": "Пинтерест",
    }
    platform_label = platform_labels.get(platform_type, platform_type)

    lines: list[str] = [
        f"Пост (4/{_TOTAL_STEPS}) -- Подготовка\n",
        f"Проект: {project_name}",
        f"Платформа: {platform_label} ({identifier})",
        f"Тема: {category_name}\n",
    ]

    # Keywords status
    if report.has_keywords:
        kw_info = f"{report.keyword_count} фраз"
        if report.cluster_count:
            kw_info = f"{report.cluster_count} кластеров ({report.keyword_count} фраз)"
        lines.append(f"\u2705 Ключевые фразы \u2014 {kw_info}")
    else:
        lines.append("\u274c Ключевые фразы (обязательно)")

    # Description status
    if report.has_description:
        lines.append("\u2705 Описание")
    else:
        lines.append("\u274c Описание")

    # Cost estimate
    lines.append(f"\nОриентировочная стоимость: ~{report.estimated_cost} ток.")

    return "\n".join(lines)


async def show_social_readiness_check(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    *,
    force_show: bool = False,
) -> None:
    """Render social readiness checklist (step 4) or skip to step 5 if all filled.

    Called from social.py after category selection, and after each sub-flow completes.
    When force_show=True (e.g. "back to checklist" from confirm), always show checklist.
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    connection_id = data.get("connection_id")
    if not category_id:
        await msg.edit_text("Категория не выбрана. Начните заново.")
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, pipeline_type="social")

    # Skip to step 5 if all required items filled (unless forced back)
    if not force_show and report.all_filled and not report.missing_items:
        from routers.publishing.pipeline.social.generation import show_social_confirm

        await show_social_confirm(callback, state, user, db, redis, report, data)
        return

    text = _build_social_checklist_text(report, data)
    kb = social_readiness_kb(report)
    await msg.edit_text(text, reply_markup=kb)
    await state.set_state(SocialPipelineFSM.readiness_check)
    await save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
        connection_id=connection_id,
    )


async def show_social_readiness_check_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Render social readiness checklist via new message (after text/file input sub-flows)."""
    data = await state.get_data()
    category_id = data.get("category_id")
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    connection_id = data.get("connection_id")
    if not category_id:
        await message.answer("Категория не выбрана. Начните заново.")
        await state.clear()
        await clear_checkpoint(redis, user.id)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, pipeline_type="social")

    if report.all_filled and not report.missing_items:
        from routers.publishing.pipeline.social.generation import show_social_confirm_msg

        await show_social_confirm_msg(message, state, user, db, redis, report, data)
        return

    text = _build_social_checklist_text(report, data)
    kb = social_readiness_kb(report)
    await message.answer(text, reply_markup=kb)
    await state.set_state(SocialPipelineFSM.readiness_check)
    await save_checkpoint(
        redis,
        user.id,
        current_step="readiness_check",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
        category_id=category_id,
        connection_id=connection_id,
    )


# ---------------------------------------------------------------------------
# Register shared sub-flows (keywords, description, navigation)
# ---------------------------------------------------------------------------

_social_config = ReadinessConfig(
    fsm_class=SocialPipelineFSM,
    prefix="pipeline:social:readiness",
    cancel_cb="pipeline:social:cancel",
    log_prefix="pipeline.social.readiness",
    show_check=show_social_readiness_check,
    show_check_msg=show_social_readiness_check_msg,
    description_hint="посты",
    charge_suffix="social pipeline",
)

_handlers = register_readiness_subflows(router, _social_config)


# ---------------------------------------------------------------------------
# Done (step 5 transition) -- social-specific
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.readiness_check,
    F.data == "pipeline:social:readiness:done",
)
async def social_readiness_done(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Proceed to step 5 (confirmation). Keywords are required blocker."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    category_id = data.get("category_id")
    if not category_id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    balance = await token_svc.get_balance(user.id)

    svc = ReadinessService(db)
    report = await svc.check(user.id, category_id, balance, pipeline_type="social")

    if report.has_blockers:
        await callback.answer(
            "Добавьте ключевые фразы -- это обязательный пункт.",
            show_alert=True,
        )
        return

    from routers.publishing.pipeline.social.generation import show_social_confirm

    await show_social_confirm(callback, state, user, db, redis, report, data)
    await callback.answer()
