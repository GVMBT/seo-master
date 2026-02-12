"""Repository for projects table."""

from db.models import Project, ProjectCreate, ProjectUpdate
from db.repositories.base import BaseRepository

_TABLE = "projects"


class ProjectsRepository(BaseRepository):
    """CRUD operations for projects table."""

    async def get_by_id(self, project_id: int) -> Project | None:
        """Get project by ID."""
        resp = await self._table(_TABLE).select("*").eq("id", project_id).maybe_single().execute()
        row = self._single(resp)
        return Project(**row) if row else None

    async def get_by_user(self, user_id: int) -> list[Project]:
        """Get all projects for a user, ordered by creation date (newest first)."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [Project(**row) for row in self._rows(resp)]

    async def get_count_by_user(self, user_id: int) -> int:
        """Count projects owned by user."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("user_id", user_id)
            .execute()
        )
        return self._count(resp)

    async def create(self, data: ProjectCreate) -> Project:
        """Create a new project."""
        resp = await self._table(_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return Project(**row)

    async def update(self, project_id: int, data: ProjectUpdate) -> Project | None:
        """Partial update. Returns None if project not found."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return await self.get_by_id(project_id)
        resp = await self._table(_TABLE).update(payload).eq("id", project_id).execute()
        row = self._first(resp)
        return Project(**row) if row else None

    async def delete(self, project_id: int) -> bool:
        """Delete project. Service must cancel QStash schedules BEFORE calling this (E11)."""
        resp = await self._table(_TABLE).delete().eq("id", project_id).execute()
        return len(self._rows(resp)) > 0
