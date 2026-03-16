"""Repository for project_platform_settings table (per-platform content overrides)."""

from typing import Any

from db.models import ProjectPlatformSettings
from db.repositories.base import BaseRepository

_TABLE = "project_platform_settings"


class ProjectPlatformSettingsRepository(BaseRepository):
    """CRUD for per-platform content settings at project level."""

    async def get_by_project_and_platform(
        self, project_id: int, platform_type: str
    ) -> ProjectPlatformSettings | None:
        """Get platform-specific settings for a project."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .eq("platform_type", platform_type)
            .maybe_single()
            .execute()
        )
        row = self._single(resp)
        return ProjectPlatformSettings(**row) if row else None

    async def get_all_by_project(self, project_id: int) -> list[ProjectPlatformSettings]:
        """Get all platform overrides for a project."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .order("platform_type")
            .execute()
        )
        return [ProjectPlatformSettings(**row) for row in self._rows(resp)]

    async def upsert(
        self,
        project_id: int,
        platform_type: str,
        text_settings: dict[str, Any] | None = None,
        image_settings: dict[str, Any] | None = None,
    ) -> ProjectPlatformSettings:
        """Create or update platform settings. Only non-None fields are written."""
        payload: dict[str, Any] = {
            "project_id": project_id,
            "platform_type": platform_type,
        }
        if text_settings is not None:
            payload["text_settings"] = text_settings
        if image_settings is not None:
            payload["image_settings"] = image_settings

        resp = (
            await self._table(_TABLE)
            .upsert(payload, on_conflict="project_id,platform_type")
            .execute()
        )
        row = self._require_first(resp)
        return ProjectPlatformSettings(**row)

    async def delete(self, project_id: int, platform_type: str) -> bool:
        """Delete platform override (reset to defaults)."""
        resp = (
            await self._table(_TABLE)
            .delete()
            .eq("project_id", project_id)
            .eq("platform_type", platform_type)
            .execute()
        )
        return len(self._rows(resp)) > 0
