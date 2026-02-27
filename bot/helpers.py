"""Shared helper functions for router handlers.

S1a: safe_message() eliminates ~170 InaccessibleMessage guard blocks.
S1c: get_owned_project/category ownership check helpers.
"""

from __future__ import annotations

from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from db.client import SupabaseClient
from db.models import Category, Project
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository

# ---------------------------------------------------------------------------
# S1a: InaccessibleMessage guard helper
# ---------------------------------------------------------------------------


def safe_message(callback: CallbackQuery) -> Message | None:
    """Return callback.message if accessible, otherwise answer and return None.

    Replaces the 3-line guard pattern used in ~170 handlers:
        if not callback.message or isinstance(callback.message, InaccessibleMessage):
            await callback.answer()
            return

    Usage:
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return
    """
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return None
    return callback.message


# ---------------------------------------------------------------------------
# S1c: Ownership verification helpers
# ---------------------------------------------------------------------------


async def get_owned_project(
    db: SupabaseClient,
    project_id: int,
    user_id: int,
) -> Project | None:
    """Load project and verify ownership. Returns None if not found or not owned."""
    repo = ProjectsRepository(db)
    project = await repo.get_by_id(project_id)
    if not project or project.user_id != user_id:
        return None
    return project


async def get_owned_category(
    db: SupabaseClient,
    category_id: int,
    user_id: int,
) -> Category | None:
    """Load category and verify it belongs to a project owned by user.

    Returns None if category not found, project not found, or not owned.
    """
    cats_repo = CategoriesRepository(db)
    category = await cats_repo.get_by_id(category_id)
    if not category:
        return None
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(category.project_id)
    if not project or project.user_id != user_id:
        return None
    return category
