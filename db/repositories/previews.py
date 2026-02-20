"""Repository for article_previews table."""

from datetime import UTC, datetime

from db.models import ArticlePreview, ArticlePreviewCreate, ArticlePreviewUpdate
from db.repositories.base import BaseRepository

_TABLE = "article_previews"


class PreviewsRepository(BaseRepository):
    """CRUD operations for article_previews table."""

    async def create(self, data: ArticlePreviewCreate) -> ArticlePreview:
        """Create a new article preview."""
        resp = await self._table(_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return ArticlePreview(**row)

    async def get_by_id(self, preview_id: int) -> ArticlePreview | None:
        """Get preview by ID."""
        resp = await self._table(_TABLE).select("*").eq("id", preview_id).maybe_single().execute()
        row = self._single(resp)
        return ArticlePreview(**row) if row else None

    async def get_active_by_user(self, user_id: int) -> list[ArticlePreview]:
        """Get non-expired draft previews for a user."""
        now = datetime.now(tz=UTC).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("status", "draft")
            .gte("expires_at", now)
            .order("created_at", desc=True)
            .execute()
        )
        return [ArticlePreview(**row) for row in self._rows(resp)]

    async def update(self, preview_id: int, data: ArticlePreviewUpdate) -> ArticlePreview | None:
        """Partial update of preview."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return await self.get_by_id(preview_id)
        resp = await self._table(_TABLE).update(payload).eq("id", preview_id).execute()
        row = self._first(resp)
        return ArticlePreview(**row) if row else None

    async def get_active_drafts_by_project(self, project_id: int) -> list[ArticlePreview]:
        """Get non-expired draft previews for a project (E42: refund before delete)."""
        now = datetime.now(tz=UTC).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .eq("status", "draft")
            .gte("expires_at", now)
            .execute()
        )
        return [ArticlePreview(**row) for row in self._rows(resp)]

    async def get_active_drafts_by_category(self, category_id: int) -> list[ArticlePreview]:
        """Get non-expired draft previews for a category (E42: refund before delete)."""
        now = datetime.now(tz=UTC).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("category_id", category_id)
            .eq("status", "draft")
            .gte("expires_at", now)
            .execute()
        )
        return [ArticlePreview(**row) for row in self._rows(resp)]

    async def get_expired_drafts(self) -> list[ArticlePreview]:
        """Get expired draft previews for cleanup.

        Cleanup service handles: refund tokens, notify user, then mark as expired.
        """
        now = datetime.now(tz=UTC).isoformat()
        resp = await self._table(_TABLE).select("*").eq("status", "draft").lt("expires_at", now).execute()
        return [ArticlePreview(**row) for row in self._rows(resp)]

    async def mark_expired(self, preview_id: int) -> None:
        """Mark a single preview as expired (called after refund + notification)."""
        await self._table(_TABLE).update({"status": "expired"}).eq("id", preview_id).execute()

    async def atomic_mark_expired(self, preview_id: int) -> ArticlePreview | None:
        """Atomically mark preview as expired (CAS: only if status='draft').

        Returns the updated preview, or None if already expired/processed (race condition).
        """
        resp = (
            await self._table(_TABLE).update({"status": "expired"}).eq("id", preview_id).eq("status", "draft").execute()
        )
        row = self._first(resp)
        return ArticlePreview(**row) if row else None

    async def atomic_mark_published(self, preview_id: int) -> ArticlePreview | None:
        """Atomically mark preview as published (CAS: only if status='draft').

        Returns the updated preview, or None if already published/expired (E18, P0-3).
        Prevents race between publish and cleanup.
        """
        resp = (
            await self._table(_TABLE)
            .update({"status": "published"})
            .eq("id", preview_id)
            .eq("status", "draft")
            .execute()
        )
        row = self._first(resp)
        return ArticlePreview(**row) if row else None

    async def increment_regeneration(self, preview_id: int) -> int:
        """Atomically increment regeneration_count using CAS (compare-and-swap).

        Reads current count, then updates only if count hasn't changed.
        Returns new count, or 0 if preview not found.
        """
        preview = await self.get_by_id(preview_id)
        if not preview:
            return 0
        old_count = preview.regeneration_count
        new_count = old_count + 1
        resp = (
            await self._table(_TABLE)
            .update({"regeneration_count": new_count})
            .eq("id", preview_id)
            .eq("regeneration_count", old_count)
            .execute()
        )
        row = self._first(resp)
        if row:
            return new_count
        # CAS failed (concurrent update) — re-read current value
        refreshed = await self.get_by_id(preview_id)
        return refreshed.regeneration_count if refreshed else 0
