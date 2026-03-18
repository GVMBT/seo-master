"""Project card: view, delete with E11/E42 cleanup."""

import html

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.assets import edit_screen
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory, TokenServiceFactory
from bot.texts.emoji import E
from bot.texts.screens import Screen
from bot.texts.strings import (
    PLATFORMS_NOT_CONNECTED,
    PROJECT_CARD_HINT,
    PROJECT_DELETE_ERROR,
    PROJECT_DELETE_ITEMS,
    PROJECT_DELETE_TITLE,
    PROJECT_DELETE_WARNING,
    PROJECT_DELETED,
    PROJECT_NOT_FOUND,
)
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import project_card_kb, project_delete_confirm_kb, project_deleted_kb
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()

# Platform type -> (emoji constant, display name)
_PLATFORM_E: dict[str, tuple[str, str]] = {
    "wordpress": (E.WORDPRESS, "WordPress"),
    "telegram": (E.TELEGRAM, "Telegram"),
    "vk": (E.VK, "ВКонтакте"),
    "pinterest": (E.PINTEREST, "Pinterest"),
}


def _build_platform_lines(platform_types: list[str]) -> list[str]:
    """Build vertical platform list with per-platform emoji."""
    if not platform_types:
        return [f"{E.LINK} " + PLATFORMS_NOT_CONNECTED]
    lines: list[str] = []
    for pt in platform_types:
        emoji, name = _PLATFORM_E.get(pt, (E.LINK, pt.capitalize()))
        lines.append(f"{emoji} {name}")
    return lines


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
        await callback.answer(PROJECT_NOT_FOUND, show_alert=True)
        return

    project = card_data.project

    # Build compact card text via Screen builder
    safe_name = html.escape(project.name)
    s = Screen(E.ROCKET, safe_name)
    if project.website_url:
        s.line(f"{E.WORDPRESS} {html.escape(project.website_url)}")
    s.blank()

    # Platform list: vertical with per-platform emoji
    platform_lines = _build_platform_lines(card_data.platform_types)
    for pl in platform_lines:
        s.line(pl)
    s.blank()

    s.field(E.FOLDER, "Категорий", len(card_data.categories))
    s.field(E.ANALYTICS, "Публикаций", card_data.pub_count)
    s.hint(PROJECT_CARD_HINT)
    text = s.build()
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
        await callback.answer(PROJECT_NOT_FOUND, show_alert=True)
        return

    safe_name = html.escape(project.name)
    s = (
        Screen(E.WARNING, PROJECT_DELETE_TITLE)
        .blank()
        .line(f"Удалить проект \u00ab{safe_name}\u00bb?")
        .blank()
        .line("Будут удалены:")
    )
    for item in PROJECT_DELETE_ITEMS:
        s.line(f"\u2022 {item}")
    text = s.hint(PROJECT_DELETE_WARNING).build()
    await safe_edit_text(
        msg,
        text,
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
        await safe_edit_text(msg,
            PROJECT_DELETED.format(name=safe_name),
            reply_markup=project_deleted_kb(),
        )
    else:
        await safe_edit_text(msg,
            f"{E.WARNING} " + PROJECT_DELETE_ERROR,
            reply_markup=project_deleted_kb(),
        )

    await callback.answer()
