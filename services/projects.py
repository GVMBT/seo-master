"""Project service — ownership-verified CRUD, delete with E11/E42 cleanup.

Extracts all ProjectsRepository usage from routers into a single service layer.
Zero Telegram/Aiogram dependencies.

Source of truth: ARCHITECTURE.md section 2 ("routers -> services -> repositories").
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import Category, Project, ProjectCreate, ProjectUpdate
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from services.scheduler import SchedulerService
from services.tokens import TokenService

log = structlog.get_logger()

# H17: maximum projects per user (anti-DoS)
MAX_PROJECTS_PER_USER = 20


@dataclass(frozen=True, slots=True)
class ProjectCardData:
    """Aggregated data for project card display."""

    project: Project
    platform_types: list[str]
    categories: list[Category]
    pub_count: int


class ProjectService:
    """Ownership-verified project operations.

    Every read/write method verifies project ownership by the requesting user.
    This eliminates duplicated ownership checks across router files.
    """

    def __init__(self, db: SupabaseClient, encryption_key: str = "") -> None:
        self._db = db
        self._repo = ProjectsRepository(db)
        self._encryption_key = encryption_key

    # ------------------------------------------------------------------
    # Ownership helpers
    # ------------------------------------------------------------------

    async def get_owned_project(
        self,
        project_id: int,
        user_id: int,
    ) -> Project | None:
        """Load project and verify ownership. Returns None if not found or not owned."""
        project = await self._repo.get_by_id(project_id)
        if not project or project.user_id != user_id:
            return None
        return project

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def list_by_user(self, user_id: int) -> list[Project]:
        """List all projects for user, ordered by creation date (newest first)."""
        return await self._repo.get_by_user(user_id)

    async def build_card_data(
        self,
        project_id: int,
        user_id: int,
    ) -> ProjectCardData | None:
        """Aggregate project card data from multiple repositories.

        Returns None if project not found or not owned.
        """
        project = await self.get_owned_project(project_id, user_id)
        if not project:
            return None

        cm = CredentialManager(self._encryption_key)
        conn_repo = ConnectionsRepository(self._db, cm)
        cats_repo = CategoriesRepository(self._db)
        pubs_repo = PublicationsRepository(self._db)

        platform_types = await conn_repo.get_platform_types_by_project(project_id)
        categories = await cats_repo.get_by_project(project_id)
        pub_count = await pubs_repo.get_count_by_project(project_id)

        return ProjectCardData(
            project=project,
            platform_types=platform_types,
            categories=categories,
            pub_count=pub_count,
        )

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    async def check_project_limit(self, user_id: int) -> bool:
        """Check if user has room for more projects.

        Returns True if under limit, False if at limit.
        """
        count = await self._repo.get_count_by_user(user_id)
        return count < MAX_PROJECTS_PER_USER

    async def create_project(self, data: ProjectCreate) -> Project:
        """Create a new project."""
        return await self._repo.create(data)

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    async def update_project(
        self,
        project_id: int,
        user_id: int,
        update: ProjectUpdate,
    ) -> Project | None:
        """Update project fields for an owned project.

        Returns None if project not found, not owned, or update failed.
        """
        project = await self.get_owned_project(project_id, user_id)
        if not project:
            return None
        return await self._repo.update(project_id, update)

    # ------------------------------------------------------------------
    # Delete (E11 + E42)
    # ------------------------------------------------------------------

    async def delete_project(
        self,
        project_id: int,
        user_id: int,
        scheduler_svc: SchedulerService,
        token_svc: TokenService,
    ) -> tuple[bool, Project | None]:
        """Delete project with E11 (QStash cancel) and E42 (preview refund).

        Returns (success, deleted_project).
        """
        project = await self.get_owned_project(project_id, user_id)
        if not project:
            return False, None

        # E11: Cancel QStash schedules BEFORE CASCADE delete
        await scheduler_svc.cancel_schedules_for_project(project_id)

        # E42: Refund active previews
        previews_repo = PreviewsRepository(self._db)
        active_previews = await previews_repo.get_active_drafts_by_project(project_id)
        if active_previews:
            await token_svc.refund_active_previews(
                active_previews,
                user_id,
                f"удаление проекта #{project_id}",
            )

        # Delete project (CASCADE deletes categories, connections, schedules)
        deleted = await self._repo.delete(project_id)

        if deleted:
            log.info("project_deleted", project_id=project_id, user_id=user_id)

        return deleted, project
