"""Project list with pagination."""

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage

from db.client import SupabaseClient
from db.models import User
from db.repositories.projects import ProjectsRepository
from keyboards.inline import project_list_empty_kb, project_list_kb

router = Router()


@router.callback_query(F.data.in_({"nav:projects", "project:list"}))
async def project_list_handler(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show project list (page 1)."""
    await _show_list(callback, user, db, page=1)


@router.callback_query(F.data.startswith("page:projects:"))
async def project_list_page(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Handle pagination for project list."""
    page_str = callback.data.split(":")[-1] if callback.data else "1"
    try:
        page = int(page_str)
    except ValueError:
        page = 1
    await _show_list(callback, user, db, page=page)


async def _show_list(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    page: int = 1,
) -> None:
    """Build and display project list."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    repo = ProjectsRepository(db)
    projects = await repo.get_by_user(user.id)

    if not projects:
        await callback.message.edit_text(
            "У вас пока нет проектов.\nСоздайте первый — это займёт 30 секунд.",
            reply_markup=project_list_empty_kb(),
        )
    else:
        kb = project_list_kb(projects, page)
        await callback.message.edit_text(
            f"Мои проекты ({len(projects)}):",
            reply_markup=kb,
        )
    await callback.answer()
