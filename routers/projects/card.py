"""Project card: view, delete with E11/E42 cleanup."""

import html

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage

from bot.config import get_settings
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from keyboards.inline import project_card_kb, project_delete_confirm_kb, project_deleted_kb
from services.scheduler import SchedulerService
from services.tokens import TokenService

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
) -> None:
    """Show project card (UX_TOOLBOX.md section 3.1-3.2)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)

    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    # Gather card data
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn_repo = ConnectionsRepository(db, cm)
    cats_repo = CategoriesRepository(db)
    pubs_repo = PublicationsRepository(db)

    platform_types = await conn_repo.get_platform_types_by_project(project_id)
    categories = await cats_repo.get_by_project(project_id)
    pub_count = await pubs_repo.get_count_by_project(project_id)

    # Build card text
    safe_name = html.escape(project.name)
    lines = [f"<b>{safe_name}</b>\n"]

    if project.website_url:
        lines.append(f"Сайт: {html.escape(project.website_url)}")

    if platform_types:
        platforms_str = ", ".join(p.capitalize() for p in platform_types)
        lines.append(f"Платформы: {platforms_str}")
    else:
        lines.append("Платформы: не подключены")

    lines.append(f"Категорий: {len(categories)}")
    lines.append(f"Публикаций: {pub_count}")

    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=project_card_kb(project_id))
    await callback.answer()


# ---------------------------------------------------------------------------
# Stub callbacks for future phases
# ---------------------------------------------------------------------------

# project:{id}:categories — handled by routers/categories/manage.py
# project:{id}:connections — handled by routers/platforms/connections.py


# project:{id}:scheduler — handled by routers/publishing/scheduler.py


# ---------------------------------------------------------------------------
# Project delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:delete$"))
async def confirm_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show delete confirmation dialog."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)

    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    safe_name = html.escape(project.name)
    await callback.message.edit_text(
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
    scheduler_service: SchedulerService,
) -> None:
    """Delete project with E11 cleanup: QStash cancel, E42 preview refund."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)

    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    settings = get_settings()

    # E11: Cancel QStash schedules BEFORE CASCADE delete
    await scheduler_service.cancel_schedules_for_project(project_id)

    # E42: Refund active previews
    previews_repo = PreviewsRepository(db)
    active_previews = await previews_repo.get_active_drafts_by_project(project_id)
    if active_previews:
        token_service = TokenService(db=db, admin_ids=settings.admin_ids)
        await token_service.refund_active_previews(
            active_previews,
            user.id,
            f"удаление проекта #{project_id}",
        )

    # Delete project (CASCADE deletes categories, connections, schedules)
    deleted = await repo.delete(project_id)

    if deleted:
        safe_name = html.escape(project.name)
        await callback.message.edit_text(
            f"Проект «{safe_name}» удалён.",
            reply_markup=project_deleted_kb(),
        )
        log.info("project_deleted", project_id=project_id, user_id=user.id)
    else:
        await callback.message.edit_text(
            "Ошибка удаления проекта.",
            reply_markup=project_deleted_kb(),
        )

    await callback.answer()
