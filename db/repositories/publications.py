"""Repository for publication_logs table with keyword rotation logic."""

from datetime import UTC, datetime, timedelta
from typing import Any

from db.models import PublicationLog, PublicationLogCreate
from db.repositories.base import BaseRepository

_TABLE = "publication_logs"
_COOLDOWN_DAYS = 7
_MIN_POOL_SIZE = 3


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

    async def get_recently_used_keywords(
        self,
        category_id: int,
        days: int = _COOLDOWN_DAYS,
        content_type: str | None = None,
    ) -> list[str]:
        """Get keywords used in the last N days for a category.

        Uses covering index idx_pub_logs_rotation.
        When content_type is provided, cooldown is per content_type (§6.1):
        articles and social posts have independent cooldowns.
        """
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        query = (
            self._table(_TABLE)
            .select("keyword")
            .eq("category_id", category_id)
            .eq("status", "success")
            .gte("created_at", cutoff)
            .not_.is_("keyword", "null")
        )
        if content_type:
            query = query.eq("content_type", content_type)
        resp = await query.execute()
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
        self,
        category_id: int,
        keywords: list[dict[str, Any]],
        content_type: str = "article",
    ) -> tuple[str | None, bool]:
        """Select next keyword using rotation algorithm.

        Supports both cluster format and legacy flat format (API_CONTRACTS.md §6).

        Cluster format: [{cluster_name, cluster_type, main_phrase, total_volume, avg_difficulty, phrases}]
          - Filter cluster_type: "article" for articles, ("article","social") for social posts (§6.1)
          - Sort: total_volume DESC, avg_difficulty ASC
          - Pick: main_phrase
          - Cooldown: 7 days on main_phrase (stored as publication_logs.keyword)

        Legacy format: [{phrase, volume, difficulty, intent, cpc}]
          - Sort: volume DESC, difficulty ASC
          - Pick: phrase

        Returns: (keyword_phrase, low_pool_warning). None if empty pool.
        """
        if not keywords:
            return None, True

        is_cluster = bool(keywords[0].get("cluster_name"))

        if is_cluster:
            return await self._rotate_clusters(category_id, keywords, content_type)
        return await self._rotate_legacy(category_id, keywords, content_type)

    async def _rotate_clusters(
        self,
        category_id: int,
        clusters: list[dict[str, Any]],
        content_type: str,
    ) -> tuple[str | None, bool]:
        """Cluster-based rotation (API_CONTRACTS.md §6).

        Articles: filter cluster_type="article" only (§6 step 2).
        Social posts: ALL cluster_types eligible (§6.1 — no filter).
        Cooldown: per content_type (§6.1 — articles and social posts independent).
        """
        # Filter by cluster_type
        if content_type == "article":
            pool = [c for c in clusters if c.get("cluster_type") == "article"]
        else:
            # Social posts: ALL clusters are eligible (§6.1)
            pool = list(clusters)

        if not pool:
            return None, True

        low_pool_warning = len(pool) < _MIN_POOL_SIZE

        # Sort by total_volume DESC, avg_difficulty ASC
        sorted_clusters = sorted(
            pool,
            key=lambda c: (-c.get("total_volume", 0), c.get("avg_difficulty", 0)),
        )

        # Cooldown is per content_type (§6.1)
        used = set(await self.get_recently_used_keywords(category_id, content_type=content_type))

        # Pick first available cluster (main_phrase not on cooldown)
        for cluster in sorted_clusters:
            main = cluster.get("main_phrase", "")
            if main and main not in used:
                return main, low_pool_warning

        # All on cooldown -> LRU fallback (E22)
        lru = await self.get_lru_keyword(category_id)
        if lru:
            return lru, low_pool_warning

        # Fallback: first cluster's main_phrase
        first = sorted_clusters[0].get("main_phrase", "") if sorted_clusters else None
        return first or None, low_pool_warning

    async def _rotate_legacy(
        self,
        category_id: int,
        keywords: list[dict[str, Any]],
        content_type: str = "article",
    ) -> tuple[str | None, bool]:
        """Legacy flat-keyword rotation (E36 fallback)."""
        low_pool_warning = len(keywords) < _MIN_POOL_SIZE

        # Sort by volume DESC, difficulty ASC
        sorted_kw = sorted(
            keywords,
            key=lambda k: (-k.get("volume", 0), k.get("difficulty", 0)),
        )

        # Cooldown is per content_type (§6.1)
        used = set(await self.get_recently_used_keywords(category_id, content_type=content_type))

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

    async def count_recent(self, days: int = 7) -> int:
        """Count successful publications in the last N days (admin stats)."""
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("status", "success")
            .gte("created_at", cutoff)
            .execute()
        )
        return self._count(resp)

    async def delete_old_logs(self, cutoff_iso: str) -> int:
        """Delete publication logs created before cutoff date.

        Returns the number of deleted rows.
        """
        resp = await self._table(_TABLE).delete().lt("created_at", cutoff_iso).execute()
        return len(self._rows(resp))

    async def get_count_by_project(self, project_id: int) -> int:
        """Count successful publications for a project."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("project_id", project_id)
            .eq("status", "success")
            .execute()
        )
        return self._count(resp)

    async def get_stats_by_users_batch(self, user_ids: list[int]) -> dict[int, int]:
        """Get total successful publication counts for multiple users in one query (H24: batch).

        Returns dict mapping user_id -> total_publications count.
        """
        if not user_ids:
            return {}
        resp = await self._table(_TABLE).select("user_id").in_("user_id", user_ids).eq("status", "success").execute()
        rows: list[dict[str, Any]] = self._rows(resp)
        counts: dict[int, int] = {}
        for row in rows:
            uid = int(row["user_id"])
            counts[uid] = counts.get(uid, 0) + 1
        return counts

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
            await self._table(_TABLE).select("tokens_spent").eq("user_id", user_id).eq("status", "success").execute()
        )
        rows: list[dict[str, Any]] = self._rows(resp_tokens)
        total_tokens = sum(row.get("tokens_spent", 0) for row in rows)

        return {"total_publications": total, "total_tokens_spent": total_tokens}
