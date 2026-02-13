"""Router: project list + pagination."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from db.client import SupabaseClient
from db.models import User
from db.repositories.projects import ProjectsRepository
from keyboards.inline import project_list_kb
from routers._helpers import guard_callback_message

router = Router(name="projects_list")


@router.callback_query(F.data == "projects:list")
async def cb_project_list(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show paginated project list (page 0)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    projects = await ProjectsRepository(db).get_by_user(user.id)
    if not projects:
        text = "У вас пока нет проектов. Создайте первый проект, чтобы начать."
    else:
        text = f"Ваши проекты ({len(projects)}):"
    await msg.edit_text(text, reply_markup=project_list_kb(projects).as_markup())
    await callback.answer()


@router.callback_query(F.data.startswith("page:projects:"))
async def cb_project_page(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Handle project list pagination."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    page = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    projects = await ProjectsRepository(db).get_by_user(user.id)
    text = f"Ваши проекты ({len(projects)}):"
    await msg.edit_text(text, reply_markup=project_list_kb(projects, page=page).as_markup())
    await callback.answer()
