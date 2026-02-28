"""Category service — ownership-verified CRUD, delete with E24/E42 cleanup.

Extracts all CategoriesRepository + ProjectsRepository usage from routers
into a single service layer. Zero Telegram/Aiogram dependencies.

Source of truth: ARCHITECTURE.md section 2 ("routers -> services -> repositories").
"""

from __future__ import annotations

from typing import Any

import structlog

from db.client import SupabaseClient
from db.models import Category, CategoryCreate, CategoryUpdate
from db.repositories.categories import CategoriesRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.schedules import SchedulesRepository
from services.scheduler import SchedulerService
from services.tokens import TokenService

log = structlog.get_logger()

# H17: maximum categories per project (anti-DoS)
MAX_CATEGORIES_PER_PROJECT = 50


class CategoryService:
    """Ownership-verified category operations.

    Every read/write method verifies that the category belongs to a project
    owned by the requesting user. This eliminates duplicated ownership checks
    across 4+ router files.
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._cats_repo = CategoriesRepository(db)
        self._projects_repo = ProjectsRepository(db)

    # ------------------------------------------------------------------
    # Ownership helpers
    # ------------------------------------------------------------------

    async def get_owned_category(
        self,
        category_id: int,
        user_id: int,
    ) -> Category | None:
        """Load category and verify it belongs to a project owned by user.

        Returns None if not found or not owned.
        """
        category = await self._cats_repo.get_by_id(category_id)
        if not category:
            return None
        project = await self._projects_repo.get_by_id(category.project_id)
        if not project or project.user_id != user_id:
            return None
        return category

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_by_project(
        self,
        project_id: int,
        user_id: int,
    ) -> list[Category] | None:
        """List categories for an owned project. Returns None if project not owned."""
        project = await self._projects_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            return None
        return await self._cats_repo.get_by_project(project_id)

    async def get_delete_impact(
        self,
        category_id: int,
        user_id: int,
    ) -> tuple[Category, int] | None:
        """Get category and active schedule count for delete confirmation.

        Returns (category, active_schedule_count) or None if not owned.
        """
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return None
        sched_repo = SchedulesRepository(self._db)
        schedules = await sched_repo.get_by_category(category_id)
        active_count = sum(1 for s in schedules if s.enabled)
        return category, active_count

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def create_category(
        self,
        project_id: int,
        user_id: int,
        name: str,
    ) -> Category | None:
        """Create category with H17 limit check. Returns None if project not owned."""
        project = await self._projects_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            return None

        return await self._cats_repo.create(CategoryCreate(project_id=project_id, name=name))

    async def check_category_limit(
        self,
        project_id: int,
        user_id: int,
    ) -> bool | None:
        """Check if project has room for more categories.

        Returns True if under limit, False if at limit, None if project not owned.
        """
        project = await self._projects_repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            return None
        count = await self._cats_repo.get_count_by_project(project_id)
        return count < MAX_CATEGORIES_PER_PROJECT

    # ------------------------------------------------------------------
    # Delete (E24 + E42)
    # ------------------------------------------------------------------

    async def delete_category(
        self,
        category_id: int,
        user_id: int,
        scheduler_svc: SchedulerService,
        token_svc: TokenService,
    ) -> tuple[bool, Category | None, list[Category]]:
        """Delete category with E24 (QStash cancel) and E42 (preview refund).

        Returns (success, deleted_category, remaining_categories).
        """
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return False, None, []

        project_id = category.project_id

        # E24: Cancel QStash schedules BEFORE CASCADE delete
        await scheduler_svc.cancel_schedules_for_category(category_id)

        # E42: Refund active previews
        previews_repo = PreviewsRepository(self._db)
        active_previews = await previews_repo.get_active_drafts_by_category(category_id)
        if active_previews:
            await token_svc.refund_active_previews(
                active_previews,
                user_id,
                f"удаление категории #{category_id}",
            )

        # Delete category (CASCADE deletes schedules, overrides)
        deleted = await self._cats_repo.delete(category_id)

        remaining: list[Category] = []
        if deleted:
            remaining = await self._cats_repo.get_by_project(project_id)
            log.info("category_deleted", category_id=category_id, user_id=user_id)

        return deleted, category, remaining

    # ------------------------------------------------------------------
    # Update operations
    # ------------------------------------------------------------------

    async def update_text_settings(
        self,
        category_id: int,
        user_id: int,
        text_settings: dict[str, Any],
    ) -> Category | None:
        """Update text_settings for an owned category."""
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return None
        return await self._cats_repo.update(category_id, CategoryUpdate(text_settings=text_settings))

    async def update_image_settings(
        self,
        category_id: int,
        user_id: int,
        image_settings: dict[str, Any],
    ) -> Category | None:
        """Update image_settings for an owned category."""
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return None
        return await self._cats_repo.update(category_id, CategoryUpdate(image_settings=image_settings))

    async def update_prices(
        self,
        category_id: int,
        user_id: int,
        prices: str,
    ) -> Category | None:
        """Update prices for an owned category."""
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return None
        return await self._cats_repo.update(category_id, CategoryUpdate(prices=prices))

    async def clear_prices(
        self,
        category_id: int,
        user_id: int,
    ) -> bool:
        """Clear prices (set to NULL) for an owned category."""
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return False
        await self._cats_repo.clear_prices(category_id)
        return True

    async def update_description(
        self,
        category_id: int,
        user_id: int,
        description: str,
    ) -> Category | None:
        """Update description for an owned category."""
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return None
        return await self._cats_repo.update(category_id, CategoryUpdate(description=description))

    async def clear_description(
        self,
        category_id: int,
        user_id: int,
    ) -> bool:
        """Clear description (set to NULL) for an owned category."""
        category = await self.get_owned_category(category_id, user_id)
        if not category:
            return False
        await self._cats_repo.clear_description(category_id)
        return True
