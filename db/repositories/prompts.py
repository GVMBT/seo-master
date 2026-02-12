"""Repository for prompt_versions table."""

from db.models import PromptVersion, PromptVersionCreate, PromptVersionUpdate
from db.repositories.base import BaseRepository

_TABLE = "prompt_versions"


class PromptsRepository(BaseRepository):
    """CRUD operations for prompt_versions table."""

    async def get_active(self, task_type: str) -> PromptVersion | None:
        """Get the active prompt version for a task type."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("task_type", task_type)
            .eq("is_active", True)
            .maybe_single()
            .execute()
        )
        row = self._single(resp)
        return PromptVersion(**row) if row else None

    async def get_by_task_and_version(self, task_type: str, version: str) -> PromptVersion | None:
        """Get a specific prompt version."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("task_type", task_type)
            .eq("version", version)
            .maybe_single()
            .execute()
        )
        row = self._single(resp)
        return PromptVersion(**row) if row else None

    async def upsert(self, data: PromptVersionCreate) -> PromptVersion:
        """Create or update prompt version (UNIQUE on task_type + version)."""
        resp = (
            await self._table(_TABLE)
            .upsert(data.model_dump(), on_conflict="task_type,version")
            .execute()
        )
        row = self._require_first(resp)
        return PromptVersion(**row)

    async def update_stats(
        self, prompt_id: int, data: PromptVersionUpdate
    ) -> PromptVersion | None:
        """Update prompt stats (success_rate, avg_quality, is_active)."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return None
        resp = await self._table(_TABLE).update(payload).eq("id", prompt_id).execute()
        row = self._first(resp)
        return PromptVersion(**row) if row else None
