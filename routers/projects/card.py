"""Project card: view, delete with E11/E42 cleanup."""

import html

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.assets import edit_screen
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory, TokenServiceFactory
from bot.texts.emoji import Emoji
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import project_card_kb, project_delete_confirm_kb, project_deleted_kb
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# Project card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:card$"))
async def show_project_card(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show project card (UX_TOOLBOX.md section 3.1-3.2)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    proj_svc = project_service_factory(db)
    card_data = await proj_svc.build_card_data(project_id, user.id)
    if not card_data:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    project = card_data.project

    # Build compact card text
    safe_name = html.escape(project.name)

    if card_data.platform_types:
        platforms_str = ", ".join(p.capitalize() for p in card_data.platform_types)
    else:
        platforms_str = "не подключены"

    text = (
        f"<b>{safe_name}</b>\n"
        f"\n{Emoji.DB_CONNECT} Платформы: {platforms_str}"
        f"\n{Emoji.FUNNEL} Категорий: {len(card_data.categories)}"
        f"\n{Emoji.ANALYTICS} Публикаций: {card_data.pub_count}"
    )
    has_keywords = any(cat.keywords for cat in card_data.categories)
    kb = project_card_kb(project_id, has_keywords=has_keywords)
    await edit_screen(msg, "project_card.png", text, reply_markup=kb)
    await callback.answer()


# ---------------------------------------------------------------------------
# Stub callbacks for future phases
# ---------------------------------------------------------------------------

# project:{id}:categories — handled by routers/categories/manage.py
# project:{id}:connections — handled by routers/platforms/connections.py


# ---------------------------------------------------------------------------
# Project delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:delete$"))
async def confirm_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show delete confirmation dialog."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    proj_svc = project_service_factory(db)
    project = await proj_svc.get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    safe_name = html.escape(project.name)
    await safe_edit_text(
        msg,
        f"Удалить проект «{safe_name}»?\n\n"
        "Будут удалены все категории, подключения и расписания.\n"
        "Это действие нельзя отменить.",
        reply_markup=project_delete_confirm_kb(project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^project:\d+:delete:confirm$"))
async def execute_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
    scheduler_service: SchedulerService,
    token_service_factory: TokenServiceFactory,
) -> None:
    """Delete project with E11 cleanup: QStash cancel, E42 preview refund."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    proj_svc = project_service_factory(db)
    token_service = token_service_factory(db)

    deleted, project = await proj_svc.delete_project(project_id, user.id, scheduler_service, token_service)

    if deleted and project:
        safe_name = html.escape(project.name)
        await safe_edit_text(
            msg,
            f"Проект «{safe_name}» удалён.",
            reply_markup=project_deleted_kb(),
        )
    else:
        await safe_edit_text(
            msg,
            "\u26a0\ufe0f Не удалось удалить проект. Попробуйте позже.",
            reply_markup=project_deleted_kb(),
        )

    await callback.answer()
