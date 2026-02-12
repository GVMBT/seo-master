"""Repository for publication_logs table with keyword rotation logic."""

from datetime import UTC, datetime, timedelta
from typing import Any

from db.models import PublicationLog, PublicationLogCreate
from db.repositories.base import BaseRepository

_TABLE = "publication_logs"
_COOLDOWN_DAYS = 7
_MIN_POOL_SIZE = 5


class PublicationsRepository(BaseRepository):
    """CRUD + keyword rotation for publication_logs."""

    async def create_log(self, data: PublicationLogCreate) -> PublicationLog:
        """Create a publication log entry."""
        resp = await self._table(_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return PublicationLog(**row)

    async def get_by_user(self, user_id: int, limit: int = 20, offset: int = 0) -> list[PublicationLog]:
        """Get publication logs for a user, newest first."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return [PublicationLog(**row) for row in self._rows(resp)]

    async def get_by_project(self, project_id: int, limit: int = 20, offset: int = 0) -> list[PublicationLog]:
        """Get publication logs for a project, newest first."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return [PublicationLog(**row) for row in self._rows(resp)]

    async def get_recently_used_keywords(self, category_id: int, days: int = _COOLDOWN_DAYS) -> list[str]:
        """Get keywords used in the last N days for a category.

        Uses covering index idx_pub_logs_rotation.
        """
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("keyword")
            .eq("category_id", category_id)
            .eq("status", "success")
            .gte("created_at", cutoff)
            .not_.is_("keyword", "null")
            .execute()
        )
        rows: list[dict[str, Any]] = self._rows(resp)
        return [row["keyword"] for row in rows if row.get("keyword")]

    async def get_lru_keyword(self, category_id: int) -> str | None:
        """Get the least recently used keyword (oldest created_at) for LRU fallback."""
        resp = (
            await self._table(_TABLE)
            .select("keyword")
            .eq("category_id", category_id)
            .eq("status", "success")
            .not_.is_("keyword", "null")
            .order("created_at")
            .limit(1)
            .execute()
        )
        rows: list[dict[str, Any]] = self._rows(resp)
        return rows[0]["keyword"] if rows else None

    async def get_rotation_keyword(
        self, category_id: int, keywords: list[dict]
    ) -> tuple[str | None, bool]:
        """Select next keyword using rotation algorithm.

        Algorithm (API_CONTRACTS.md section 6):
        1. Sort keywords by volume DESC, difficulty ASC
        2. Exclude keywords used in last 7 days
        3. Pick first available
        4. All on cooldown -> LRU (oldest created_at)
        5. <5 keywords -> return warning flag

        Returns: (keyword_phrase, low_pool_warning). None if empty pool.
        """
        if not keywords:
            return None, True

        low_pool_warning = len(keywords) < _MIN_POOL_SIZE

        # Sort by volume DESC, difficulty ASC
        sorted_kw = sorted(
            keywords,
            key=lambda k: (-k.get("volume", 0), k.get("difficulty", 0)),
        )

        # Get recently used keywords
        used = set(await self.get_recently_used_keywords(category_id))

        # Pick first available (not on cooldown)
        for kw in sorted_kw:
            phrase = kw.get("phrase", "")
            if phrase and phrase not in used:
                return phrase, low_pool_warning

        # All on cooldown -> LRU fallback (E22)
        lru = await self.get_lru_keyword(category_id)
        if lru:
            return lru, low_pool_warning

        # Fallback: first keyword from sorted list
        first_phrase = sorted_kw[0].get("phrase", "") if sorted_kw else None
        return first_phrase or None, low_pool_warning

    async def get_stats_by_user(self, user_id: int) -> dict[str, int]:
        """Get aggregated publication stats for a user."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("user_id", user_id)
            .eq("status", "success")
            .execute()
        )
        total = self._count(resp)

        resp_tokens = (
            await self._table(_TABLE)
            .select("tokens_spent")
            .eq("user_id", user_id)
            .eq("status", "success")
            .execute()
        )
        rows: list[dict[str, Any]] = self._rows(resp_tokens)
        total_tokens = sum(row.get("tokens_spent", 0) for row in rows)

        return {"total_publications": total, "total_tokens_spent": total_tokens}
