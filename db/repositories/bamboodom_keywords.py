"""Repository for bamboodom_keywords table (4Y, 2026-04-27).

Stores keywords collected from DataForSEO Yandex per material with AI-generated
cluster labels. Supports the auto-publishing pipeline:
- save_batch: bulk upsert from collector (dedupes on keyword+material UNIQUE)
- pick_for_publishing: deterministic next-keyword selection (round-robin
  across clusters, prefers higher search_volume within cluster)
- mark_used / mark_failed: status transitions
- list_by_material: read for UI
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from db.models import BamboodomKeyword, BamboodomKeywordCreate
from db.repositories.base import BaseRepository

log = structlog.get_logger()

_TABLE = "bamboodom_keywords"

VALID_MATERIALS = ("wpc", "flex", "reiki", "profiles")
VALID_STATUSES = ("new", "queued", "used", "failed", "skipped")

# 5E (2026-04-27): geo-expansion list. 16 Crimean cities (республика Крым +
# город федерального значения Севастополь). Used by expand_to_cities() to
# multiply base keywords into geo-targeted variants.
CRIMEA_CITIES = (
    "Симферополь", "Севастополь", "Ялта", "Феодосия", "Евпатория",
    "Керчь", "Алушта", "Судак", "Бахчисарай", "Джанкой",
    "Саки", "Армянск", "Красноперекопск", "Старый Крым", "Белогорск", "Щёлкино",
)


class BamboodomKeywordsRepository(BaseRepository):
    """CRUD for bamboodom_keywords (4Y)."""

    async def save_batch(
        self, items: list[BamboodomKeywordCreate]
    ) -> dict[str, int]:
        """Upsert keywords (UNIQUE on keyword+material).

        Returns counts: {"new": int, "updated": int, "total": int}.
        Existing rows have their search_volume / cluster updated; status not
        touched (so already-used keywords stay used).
        """
        if not items:
            return {"new": 0, "updated": 0, "total": 0}

        # First, fetch existing rows for the same (keyword, material) pairs
        # so we can decide which fields to update vs which to leave alone.
        # Supabase doesn't expose "ON CONFLICT DO UPDATE WHERE" easily, so
        # we do read-then-upsert.
        keys = list({(it.keyword, it.material) for it in items})
        existing_map: dict[tuple[str, str], BamboodomKeyword] = {}
        # Fetch in batches of 100 to avoid query length limits
        for i in range(0, len(keys), 100):
            chunk = keys[i : i + 100]
            phrases = list({k for k, _ in chunk})
            mats = list({m for _, m in chunk})
            resp = (
                await self._table(_TABLE)
                .select("*")
                .in_("keyword", phrases)
                .in_("material", mats)
                .execute()
            )
            for row in resp.data or []:
                kw = BamboodomKeyword(**row)
                existing_map[(kw.keyword, kw.material)] = kw

        # Build upsert payloads
        rows_to_upsert: list[dict] = []
        new_count = 0
        updated_count = 0
        for it in items:
            existing = existing_map.get((it.keyword, it.material))
            if existing:
                # Update only volume/competition/cluster, keep status
                payload = {
                    "id": existing.id,
                    "keyword": it.keyword,
                    "material": it.material,
                    "search_volume": it.search_volume,
                    "competition": it.competition,
                    "cluster_id": it.cluster_id if it.cluster_id is not None else existing.cluster_id,
                    "cluster_label": it.cluster_label or existing.cluster_label,
                    "status": existing.status,
                }
                rows_to_upsert.append(payload)
                updated_count += 1
            else:
                payload = {
                    "keyword": it.keyword,
                    "material": it.material,
                    "search_volume": it.search_volume,
                    "competition": it.competition,
                    "cluster_id": it.cluster_id,
                    "cluster_label": it.cluster_label,
                    "status": it.status,
                }
                rows_to_upsert.append(payload)
                new_count += 1

        # Execute upsert in batches of 200
        for i in range(0, len(rows_to_upsert), 200):
            chunk = rows_to_upsert[i : i + 200]
            await (
                self._table(_TABLE)
                .upsert(chunk, on_conflict="keyword,material")
                .execute()
            )

        log.info(
            "bbk_save_batch",
            total=len(items),
            new=new_count,
            updated=updated_count,
        )
        return {"new": new_count, "updated": updated_count, "total": len(items)}

    async def list_by_material(
        self,
        material: str,
        status: str | None = "new",
        limit: int = 100,
    ) -> list[BamboodomKeyword]:
        """List keywords for a material, optionally filtered by status."""
        q = self._table(_TABLE).select("*").eq("material", material)
        if status is not None:
            q = q.eq("status", status)
        q = q.order("search_volume", desc=True).limit(limit)
        resp = await q.execute()
        return [BamboodomKeyword(**row) for row in resp.data or []]

    async def count_by_material(
        self, material: str, status: str | None = None
    ) -> int:
        """Count keywords for material/status."""
        q = self._table(_TABLE).select("id", count="exact").eq("material", material)
        if status is not None:
            q = q.eq("status", status)
        resp = await q.execute()
        return resp.count or 0

    async def stats_summary(self) -> dict[str, dict[str, int]]:
        """Per-material summary: {material: {new: N, used: N, failed: N, total: N}}."""
        out: dict[str, dict[str, int]] = {}
        resp = await self._table(_TABLE).select("material,status").execute()
        for row in resp.data or []:
            mat = row["material"]
            st = row["status"]
            if mat not in out:
                out[mat] = {"new": 0, "used": 0, "failed": 0, "skipped": 0, "queued": 0, "total": 0}
            out[mat][st] = out[mat].get(st, 0) + 1
            out[mat]["total"] += 1
        return out

    async def expand_to_cities(
        self,
        material: str,
        cities: list[str] | tuple[str, ...] = CRIMEA_CITIES,
        top_n: int = 10,
    ) -> dict[str, int]:
        """Multiply top-N base keywords by city list, save as geo variants.

        For each of the top-N keywords (ordered by search_volume) of the
        given material with city IS NULL, insert one row per city. Existing
        (keyword, material, city) triples are skipped (no overwrite).

        Returns counts: {"new": int, "skipped": int, "total": int}.
        """
        # 1) base keywords (city IS NULL) sorted by volume.
        resp = await (
            self._table(_TABLE)
            .select("*")
            .eq("material", material)
            .is_("city", "null")
            .order("search_volume", desc=True)
            .limit(top_n)
            .execute()
        )
        base_rows = resp.data or []
        if not base_rows:
            return {"new": 0, "skipped": 0, "total": 0}

        # 2) build candidate geo-rows.
        geo_rows: list[dict] = []
        for br in base_rows:
            for city in cities:
                geo_rows.append({
                    "keyword": br["keyword"],
                    "material": br["material"],
                    "city": city,
                    "search_volume": br.get("search_volume", 0),
                    "competition": br.get("competition"),
                    "cluster_id": br.get("cluster_id"),
                    "cluster_label": br.get("cluster_label"),
                    "status": "new",
                })

        # 3) read existing (keyword, material, city) to avoid duplicates.
        keywords = list({r["keyword"] for r in geo_rows})
        existing_resp = await (
            self._table(_TABLE)
            .select("keyword, city")
            .eq("material", material)
            .in_("keyword", keywords)
            .not_.is_("city", "null")
            .execute()
        )
        existing_keys = {
            (row["keyword"], row["city"])
            for row in (existing_resp.data or [])
        }

        new_rows = [
            r for r in geo_rows
            if (r["keyword"], r["city"]) not in existing_keys
        ]
        skipped = len(geo_rows) - len(new_rows)

        # 4) insert new rows in chunks.
        for i in range(0, len(new_rows), 200):
            chunk = new_rows[i : i + 200]
            await self._table(_TABLE).insert(chunk).execute()

        log.info(
            "bbk_expand_to_cities",
            material=material,
            top_n=top_n,
            cities=len(cities),
            new=len(new_rows),
            skipped=skipped,
        )
        return {"new": len(new_rows), "skipped": skipped, "total": len(geo_rows)}

    async def pick_for_publishing(
        self,
        material: str,
        avoid_cluster_ids: list[int] | None = None,
    ) -> BamboodomKeyword | None:
        """Pick highest-volume new keyword from clusters not in avoid list.

        Used by Phase 2 auto-publisher: rotate clusters within material so
        consecutive articles aren't on the same theme. Phase 1: just returns
        highest-volume new keyword for material.
        """
        q = self._table(_TABLE).select("*").eq("material", material).eq("status", "new")
        if avoid_cluster_ids:
            q = q.not_("cluster_id", "in", f"({','.join(str(c) for c in avoid_cluster_ids)})")
        q = q.order("search_volume", desc=True).limit(1)
        resp = await q.execute()
        rows = resp.data or []
        return BamboodomKeyword(**rows[0]) if rows else None

    async def get_by_id(self, kw_id: int) -> BamboodomKeyword | None:
        """Fetch a single keyword by id."""
        resp = await self._table(_TABLE).select("*").eq("id", kw_id).maybe_single().execute()
        row = self._single(resp)
        return BamboodomKeyword(**row) if row else None

    async def mark_status(
        self,
        kw_id: int,
        status: str,
        published_slug: str | None = None,
    ) -> None:
        """Update status + optional published_slug.

        For status=used, also sets published_at and last_used_at to now.
        """
        if status not in VALID_STATUSES:
            raise ValueError(f"Invalid status: {status}")
        payload: dict = {"status": status, "last_used_at": datetime.now(timezone.utc).isoformat()}
        if status == "used":
            payload["published_at"] = datetime.now(timezone.utc).isoformat()
            if published_slug:
                payload["published_slug"] = published_slug
        await self._table(_TABLE).update(payload).eq("id", kw_id).execute()
        log.info("bbk_mark_status", kw_id=kw_id, status=status, slug=published_slug)
