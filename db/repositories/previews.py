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

    async def get_expired_drafts(self) -> list[ArticlePreview]:
        """Get expired draft previews for cleanup.

        Cleanup service handles: refund tokens, notify user, then mark as expired.
        """
        now = datetime.now(tz=UTC).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("status", "draft")
            .lt("expires_at", now)
            .execute()
        )
        return [ArticlePreview(**row) for row in self._rows(resp)]

    async def mark_expired(self, preview_id: int) -> None:
        """Mark a single preview as expired (called after refund + notification)."""
        await self._table(_TABLE).update({"status": "expired"}).eq("id", preview_id).execute()
