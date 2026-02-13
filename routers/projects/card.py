"""Router: project card, stubs, delete (2-step)."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from db.client import SupabaseClient
from db.models import Project, User
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    project_card_kb,
    project_delete_confirm_kb,
    project_list_kb,
)
from routers._helpers import guard_callback_message

router = Router(name="projects_card")

# Platform type → display name mapping
_PLATFORM_NAMES: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Telegram",
    "vk": "VK",
    "pinterest": "Pinterest",
}


# ---------------------------------------------------------------------------
# Helpers (shared with create.py)
# ---------------------------------------------------------------------------


def _count_filled_fields(project: Project) -> int:
    """Count non-empty fields out of 15 project fields."""
    return sum(1 for _, fn in [
        ("name", project.name), ("company_name", project.company_name),
        ("specialization", project.specialization), ("website_url", project.website_url),
        ("company_city", project.company_city), ("company_address", project.company_address),
        ("company_phone", project.company_phone), ("company_email", project.company_email),
        ("company_instagram", project.company_instagram), ("company_vk", project.company_vk),
        ("company_pinterest", project.company_pinterest), ("company_telegram", project.company_telegram),
        ("experience", project.experience), ("advantages", project.advantages),
        ("description", project.description),
    ] if fn)


def _format_project_card(
    project: Project,
    category_count: int = 0,
    platform_names: list[str] | None = None,
) -> str:
    """Format project info for card display (USER_FLOWS_AND_UI_MAP.md level 2)."""
    filled = _count_filled_fields(project)
    platforms_str = ", ".join(platform_names) if platform_names else "не подключены"
    return (
        f"<b>{project.name}</b>\n"
        f"Компания: {project.company_name}\n"
        f"Специализация: {project.specialization}\n"
        f"Заполнено: {filled}/15 полей\n"
        f"Категорий: {category_count}\n"
        f"Платформы: {platforms_str}"
    )


async def _get_project_or_notify(
    project_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery
) -> Project | None:
    """Fetch project and verify ownership. Answers callback on failure."""
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Проект не найден.", show_alert=True)
        return None
    return project


# ---------------------------------------------------------------------------
# Project card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):card$"))
async def cb_project_card(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show project card with category count and platform connections."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return

    # Fetch category count and platform connections for card display (P4.5)
    from bot.config import get_settings
    from db.credential_manager import CredentialManager
    from db.repositories.categories import CategoriesRepository
    from db.repositories.connections import ConnectionsRepository

    categories = await CategoriesRepository(db).get_by_project(project_id)
    category_count = len(categories)

    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    platform_types = await ConnectionsRepository(db, cm).get_platform_types_by_project(project_id)
    platform_names = [_PLATFORM_NAMES.get(pt, pt) for pt in platform_types]

    await msg.edit_text(
        _format_project_card(project, category_count=category_count, platform_names=platform_names or None),
        reply_markup=project_card_kb(project).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Stubs (later phases)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):(scheduler|audit|timezone)$"))
async def cb_project_feature_stub(callback: CallbackQuery) -> None:
    """Stub for not-yet-implemented project features."""
    await callback.answer("В разработке.", show_alert=True)


# ---------------------------------------------------------------------------
# Delete project (2-step confirmation)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):delete$"))
async def cb_project_delete(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show delete confirmation."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return
    await msg.edit_text(
        f"Удалить проект «{project.name}»? Все категории и данные будут удалены.",
        reply_markup=project_delete_confirm_kb(project.id).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^project:(\d+):delete:confirm$"))
async def cb_project_delete_confirm(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Confirm deletion: delete project and show list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await _get_project_or_notify(project_id, user.id, db, callback)
    if not project:
        return

    # TODO Phase 9: cancel QStash schedules before CASCADE delete (E11)
    repo = ProjectsRepository(db)
    await repo.delete(project_id)

    projects = await repo.get_by_user(user.id)
    text = f"Проект удалён. Ваши проекты ({len(projects)}):" if projects else "Проект удалён. У вас нет проектов."
    await msg.edit_text(text, reply_markup=project_list_kb(projects).as_markup())
    await callback.answer("Проект удалён.")
