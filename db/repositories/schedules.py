"""Repository for platform_schedules table."""

from db.models import PlatformSchedule, PlatformScheduleCreate, PlatformScheduleUpdate
from db.repositories.base import BaseRepository

_TABLE = "platform_schedules"


class SchedulesRepository(BaseRepository):
    """CRUD operations for platform_schedules table."""

    async def get_by_id(self, schedule_id: int) -> PlatformSchedule | None:
        """Get schedule by ID."""
        resp = await self._table(_TABLE).select("*").eq("id", schedule_id).maybe_single().execute()
        row = self._single(resp)
        return PlatformSchedule(**row) if row else None

    async def get_by_category(self, category_id: int) -> list[PlatformSchedule]:
        """Get all schedules for a category."""
        resp = await self._table(_TABLE).select("*").eq("category_id", category_id).execute()
        return [PlatformSchedule(**row) for row in self._rows(resp)]

    async def get_by_connection(self, connection_id: int) -> list[PlatformSchedule]:
        """Get all schedules for a connection."""
        resp = await self._table(_TABLE).select("*").eq("connection_id", connection_id).execute()
        return [PlatformSchedule(**row) for row in self._rows(resp)]

    async def get_by_project(self, category_ids: list[int]) -> list[PlatformSchedule]:
        """Get all schedules for given category IDs.

        Required for E11: cancel QStash before CASCADE delete of project.
        Caller (service layer) must obtain category_ids via CategoriesRepository.
        """
        if not category_ids:
            return []
        resp = await self._table(_TABLE).select("*").in_("category_id", category_ids).execute()
        return [PlatformSchedule(**row) for row in self._rows(resp)]

    async def get_enabled(self) -> list[PlatformSchedule]:
        """Get all enabled schedules (for QStash sync)."""
        resp = await self._table(_TABLE).select("*").eq("enabled", True).order("created_at").execute()
        return [PlatformSchedule(**row) for row in self._rows(resp)]

    async def create(self, data: PlatformScheduleCreate) -> PlatformSchedule:
        """Create a new schedule."""
        resp = await self._table(_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return PlatformSchedule(**row)

    async def update(self, schedule_id: int, data: PlatformScheduleUpdate) -> PlatformSchedule | None:
        """Partial update."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return await self.get_by_id(schedule_id)
        resp = await self._table(_TABLE).update(payload).eq("id", schedule_id).execute()
        row = self._first(resp)
        return PlatformSchedule(**row) if row else None

    async def delete(self, schedule_id: int) -> bool:
        """Delete schedule. Service must cancel QStash schedules BEFORE calling this."""
        resp = await self._table(_TABLE).delete().eq("id", schedule_id).execute()
        return len(self._rows(resp)) > 0
