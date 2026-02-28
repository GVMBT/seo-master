"""Project list with pagination."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.helpers import safe_message
from bot.service_factory import ProjectServiceFactory
from db.client import SupabaseClient
from db.models import User
from keyboards.inline import project_list_empty_kb, project_list_kb

router = Router()


@router.callback_query(F.data.in_({"nav:projects", "project:list"}))
async def project_list_handler(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show project list (page 1)."""
    await _show_list(callback, user, db, project_service_factory, page=1)


@router.callback_query(F.data.startswith("page:projects:"))
async def project_list_page(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Handle pagination for project list."""
    page_str = callback.data.split(":")[-1] if callback.data else "1"
    try:
        page = int(page_str)
    except ValueError:
        page = 1
    await _show_list(callback, user, db, project_service_factory, page=page)


async def _show_list(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    project_service_factory: ProjectServiceFactory,
    page: int = 1,
) -> None:
    """Build and display project list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    if not projects:
        await msg.edit_text(
            "\U0001f4c1 У вас пока нет проектов.\n\nСоздайте первый — это займёт 30 секунд.",
            reply_markup=project_list_empty_kb(),
        )
    else:
        kb = project_list_kb(projects, page)
        await msg.edit_text(
            f"\U0001f4c1 Мои проекты ({len(projects)}):",
            reply_markup=kb,
        )
    await callback.answer()
