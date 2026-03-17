"""Auto-expand keyword pool when nearly exhausted.

Triggered by publish pipeline when low_pool_warning=True.
Uses existing KeywordService pipeline: DataForSEO suggestions → AI clustering → enrich.
Redis lock prevents concurrent expansions for the same category.
Zero Telegram/Aiogram dependencies.
"""

from __future__ import annotations

from typing import Any

import structlog

from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository

log = structlog.get_logger()

# Min new phrases to justify expansion (don't expand for 1-2 phrases)
_MIN_NEW_PHRASES = 5

# Redis lock TTL — prevent concurrent expansions
EXPANSION_LOCK_TTL = 3600  # 1 hour


class KeywordExpansionService:
    """Auto-expand keyword pool using existing DataForSEO + AI clustering pipeline."""

    def __init__(
        self,
        db: SupabaseClient,
        keyword_service: Any,  # services.keywords.KeywordService (avoid circular import)
        redis: Any,  # cache.redis_client.RedisClient
    ) -> None:
        self._db = db
        self._keyword_service = keyword_service
        self._redis = redis
        self._cats_repo = CategoriesRepository(db)

    async def maybe_expand(
        self,
        category_id: int,
        user_id: int,
        project_id: int,
        existing_keywords: list[dict[str, Any]],
    ) -> bool:
        """Expand keyword pool if lock is free. Returns True if expanded.

        Fire-and-forget from publish pipeline — errors are logged, not raised.
        """
        lock_key = f"keyword_expand:{category_id}"

        try:
            # Acquire Redis lock (NX = only if not exists)
            if self._redis:
                locked = await self._redis.set(lock_key, "1", ex=EXPANSION_LOCK_TTL, nx=True)
                if not locked:
                    log.info("keyword_expansion_locked", category_id=category_id)
                    return False

            return await self._do_expand(category_id, user_id, project_id, existing_keywords)

        except Exception:
            log.exception("keyword_expansion_failed", category_id=category_id)
            return False

    async def _do_expand(
        self,
        category_id: int,
        user_id: int,
        project_id: int,
        existing_keywords: list[dict[str, Any]],
    ) -> bool:
        """Run the expansion pipeline."""
        # Extract existing main_phrases as seeds for DataForSEO
        seeds: list[str] = []
        for cluster in existing_keywords:
            main = cluster.get("main_phrase", "")
            if main:
                seeds.append(main)

        if not seeds:
            log.info("keyword_expansion_no_seeds", category_id=category_id)
            return False

        # Use first 3 seeds (most popular clusters) to find new suggestions
        seed_text = ", ".join(seeds[:3])

        # Load category for geography context
        category = await self._cats_repo.get_by_id(category_id)
        if not category:
            return False

        geography = ""
        # Try to get geography from project
        from db.repositories.projects import ProjectsRepository

        project = await ProjectsRepository(self._db).get_by_id(project_id)
        if project:
            geography = project.company_city or ""

        # Step 1: Fetch raw phrases from DataForSEO using existing seeds
        raw_phrases = await self._keyword_service.fetch_raw_phrases(
            products=seed_text,
            geography=geography,
            project_id=project_id,
            user_id=user_id,
        )

        if not raw_phrases:
            # E03 fallback: generate clusters directly via AI
            new_clusters = await self._keyword_service.generate_clusters_direct(
                products=seed_text,
                geography=geography,
                project_id=project_id,
                user_id=user_id,
            )
        else:
            # Step 2: AI clustering
            new_clusters = await self._keyword_service.cluster_phrases(
                raw_phrases=raw_phrases,
                products=seed_text,
                geography=geography,
                project_id=project_id,
                user_id=user_id,
            )

            # Step 3: Enrich with volume/CPC data
            new_clusters = await self._keyword_service.enrich_clusters(new_clusters)

            # Step 4: Filter low quality
            new_clusters = self._keyword_service.filter_low_quality(new_clusters)

        if not new_clusters:
            log.info("keyword_expansion_no_new_clusters", category_id=category_id)
            return False

        # Deduplicate: remove clusters whose main_phrase already exists
        existing_phrases = {
            p.get("phrase", "").lower()
            for c in existing_keywords
            for p in c.get("phrases", [])
        }
        existing_phrases.update(c.get("main_phrase", "").lower() for c in existing_keywords)

        unique_clusters: list[dict[str, Any]] = []
        for cluster in new_clusters:
            main = cluster.get("main_phrase", "").lower()
            if main and main not in existing_phrases:
                unique_clusters.append(cluster)

        total_new_phrases = sum(len(c.get("phrases", [])) for c in unique_clusters)
        if total_new_phrases < _MIN_NEW_PHRASES:
            log.info(
                "keyword_expansion_too_few",
                category_id=category_id,
                new_phrases=total_new_phrases,
            )
            return False

        # Merge new clusters into existing keywords
        merged = existing_keywords + unique_clusters
        await self._cats_repo.update_keywords(category_id, merged)

        log.info(
            "keyword_expansion_success",
            category_id=category_id,
            new_clusters=len(unique_clusters),
            new_phrases=total_new_phrases,
            total_clusters=len(merged),
        )
        return True
