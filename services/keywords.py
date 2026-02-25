"""Keyword generation service — data-first pipeline.

Pipeline: AI seed normalization → DataForSEO suggestions/related → AI clustering → enrich.
Fallback (E03): if DataForSEO unavailable → AI generates clusters directly.
Zero Telegram/Aiogram dependencies.
"""

from __future__ import annotations

import json
import math
from typing import Any

import structlog

from db.client import SupabaseClient
from db.repositories.projects import ProjectsRepository
from services.ai.orchestrator import AIOrchestrator, GenerationRequest
from services.external.dataforseo import DataForSEOClient

log = structlog.get_logger()

# DataForSEO locations: Russia (2643) is BANNED.
# Ukraine (2804) + language_code="ru" is primary, Kazakhstan (2398) is fallback.
_DEFAULT_LOCATION = 2804  # Ukraine
_FALLBACK_LOCATION = 2398  # Kazakhstan

# Schema for AI seed normalization (structured output)
SEED_NORMALIZE_SCHEMA: dict[str, Any] = {
    "name": "seed_variants",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["variants"],
        "additionalProperties": False,
    },
}

# Schema for AI clustering (structured output)
CLUSTER_SCHEMA: dict[str, Any] = {
    "name": "cluster_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "clusters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "cluster_name": {"type": "string"},
                        "cluster_type": {"type": "string"},
                        "main_phrase": {"type": "string"},
                        "phrases": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "phrase": {"type": "string"},
                                    "ai_suggested": {"type": "boolean"},
                                },
                                "required": ["phrase", "ai_suggested"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["cluster_name", "cluster_type", "main_phrase", "phrases"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["clusters"],
        "additionalProperties": False,
    },
}

class KeywordService:
    """Data-first keyword pipeline (API_CONTRACTS.md §8)."""

    def __init__(
        self,
        orchestrator: AIOrchestrator,
        dataforseo: DataForSEOClient,
        db: SupabaseClient,
    ) -> None:
        self._orchestrator = orchestrator
        self._dataforseo = dataforseo
        self._db = db

    async def _normalize_seeds_ai(
        self,
        products: str,
        geography: str,
        language: str = "ru",
    ) -> list[str]:
        """Ask AI to rephrase user input into Google Keyword Planner-friendly seeds.

        Called BEFORE DataForSEO to convert jargon/abbreviations into search-friendly
        phrases. Cost: ~$0.001 (budget model, ~100 tokens).
        Uses generate_without_rate_limit — system call, not user-facing.
        Returns 3-5 seed variants or empty list on failure.
        """
        try:
            result = await self._orchestrator.generate_without_rate_limit(
                GenerationRequest(
                    task="seed_normalize",
                    context={
                        "products": products,
                        "geography": geography,
                        "language": language,
                    },
                    user_id=0,  # system call, no user charge
                    response_schema=SEED_NORMALIZE_SCHEMA,
                    max_retries=1,
                )
            )
        except Exception:
            log.warning("ai_seed_normalization_failed", products=products)
            return []

        if isinstance(result.content, dict):
            variants = result.content.get("variants", [])
            return [str(v)[:100] for v in variants[:5] if v]
        return []

    async def fetch_raw_phrases(
        self,
        products: str,
        geography: str,
        quantity: int,
        project_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Step 1: AI normalize seeds → DataForSEO suggestions + related.

        Strategy:
        1. Parse seed phrases from products (comma-separated)
        2. AI normalizes seeds into Google Keyword Planner-friendly phrases
        3. Single DataForSEO pass with AI-normalized seeds (Ukraine → Kazakhstan)
        4. If DataForSEO still returns 0 → caller uses AI fallback (E03)
        """
        original_seeds = [s.strip()[:100] for s in products.split(",") if s.strip()]
        if not original_seeds:
            original_seeds = [products.strip()[:100]]

        # AI normalizes jargon/abbreviations into search-friendly phrases
        ai_seeds = await self._normalize_seeds_ai(products, geography)

        # Combine: AI-normalized seeds first (higher quality), then originals as backup
        seeds: list[str] = []
        seen_lower: set[str] = set()
        for seed in [*ai_seeds, *original_seeds]:
            lower = seed.lower()
            if lower not in seen_lower:
                seen_lower.add(lower)
                seeds.append(seed)

        log.info(
            "keyword_seeds_prepared",
            original=original_seeds,
            ai_normalized=ai_seeds,
            combined=seeds[:5],
        )

        raw: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Single DataForSEO pass: try seeds with Ukraine, then Kazakhstan
        locations = [_DEFAULT_LOCATION, _FALLBACK_LOCATION]
        for location in locations:
            for seed in seeds[:5]:  # max 5 seeds
                suggestions = await self._dataforseo.keyword_suggestions(
                    seed, location_code=location, limit=quantity,
                )
                related = await self._dataforseo.related_keywords(
                    seed, location_code=location, limit=min(quantity, 100),
                )

                for kw in [*suggestions, *related]:
                    phrase_lower = kw.phrase.lower()
                    if phrase_lower not in seen:
                        seen.add(phrase_lower)
                        raw.append(
                            {
                                "phrase": kw.phrase,
                                "volume": kw.volume,
                                "cpc": kw.cpc,
                                "ai_suggested": False,
                            }
                        )

            if raw:
                log.info("dataforseo_found", count=len(raw), location=location)
                break
            log.info("dataforseo_empty_location", location=location, seeds=seeds[:5])

        # E03 fallback: DataForSEO returned nothing even with AI-normalized seeds
        if not raw:
            log.info("dataforseo_empty_fallback_to_ai", seeds=seeds[:5])

        return raw[:quantity]

    async def cluster_phrases(
        self,
        raw_phrases: list[dict[str, Any]],
        products: str,
        geography: str,
        quantity: int,
        project_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Step 2: AI clustering via keywords_cluster_v3 prompt."""
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        company_name = (project.company_name or "") if project else ""
        specialization = (project.specialization or "") if project else ""

        context = {
            "raw_count": len(raw_phrases),
            "raw_keywords_json": json.dumps(raw_phrases, ensure_ascii=False),
            "extra_count": math.ceil(quantity * 0.15),
            "products": products,
            "geography": geography,
            "company_name": company_name,
            "specialization": specialization,
            "language": "ru",
        }

        result = await self._orchestrator.generate(
            GenerationRequest(
                task="keywords",
                context=context,
                user_id=user_id,
                response_schema=CLUSTER_SCHEMA,
            )
        )

        clusters: list[dict[str, Any]] = []
        if isinstance(result.content, dict):
            clusters = result.content.get("clusters", [])

        # Assign default metrics if missing
        for cluster in clusters:
            total_vol = 0
            for p in cluster.get("phrases", []):
                if "volume" not in p:
                    p["volume"] = 0
                    p["difficulty"] = 0
                    p["cpc"] = 0.0
                if "intent" not in p:
                    p["intent"] = "informational"
                total_vol += p.get("volume", 0)
            cluster.setdefault("total_volume", total_vol)
            cluster.setdefault("avg_difficulty", 0)

        return clusters

    async def enrich_clusters(
        self,
        clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Step 3: DataForSEO enrich with volume/CPC/difficulty."""
        # Collect all unique phrases
        all_phrases: list[str] = []
        for cluster in clusters:
            for p in cluster.get("phrases", []):
                phrase = p.get("phrase", "")
                if phrase:
                    all_phrases.append(phrase)

        if not all_phrases:
            return clusters

        enriched = await self._dataforseo.enrich_keywords(all_phrases)

        # Build lookup from enriched data
        lookup: dict[str, dict[str, Any]] = {}
        for kd in enriched:
            lookup[kd.phrase.lower()] = {
                "volume": kd.volume,
                "difficulty": kd.difficulty,
                "cpc": kd.cpc,
                "intent": kd.intent,
            }

        # Apply enriched data
        for cluster in clusters:
            total_vol = 0
            total_diff = 0
            count = 0
            for p in cluster.get("phrases", []):
                phrase_lower = p.get("phrase", "").lower()
                if phrase_lower in lookup:
                    data = lookup[phrase_lower]
                    p["volume"] = data["volume"]
                    p["difficulty"] = data["difficulty"]
                    p["cpc"] = data["cpc"]
                    p["intent"] = data["intent"]
                total_vol += p.get("volume", 0)
                total_diff += p.get("difficulty", 0)
                count += 1
            cluster["total_volume"] = total_vol
            cluster["avg_difficulty"] = total_diff // max(count, 1)

        return clusters

    def filter_low_quality(
        self,
        clusters: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Remove AI-suggested phrases confirmed as zero-volume by DataForSEO.

        Keeps DataForSEO-sourced phrases (ai_suggested=False) even with volume=0,
        since they represent real (if rare) searches. Only removes AI-invented
        phrases that DataForSEO confirms nobody searches for.
        """
        filtered_total = 0
        result: list[dict[str, Any]] = []

        for cluster in clusters:
            original_count = len(cluster.get("phrases", []))
            kept: list[dict[str, Any]] = [
                p for p in cluster.get("phrases", [])
                if not (p.get("ai_suggested") and p.get("volume", 0) == 0)
            ]
            filtered_total += original_count - len(kept)

            if not kept:
                continue

            cluster["phrases"] = kept
            # Recalculate aggregates
            total_vol = sum(p.get("volume", 0) for p in kept)
            total_diff = sum(p.get("difficulty", 0) for p in kept)
            cluster["total_volume"] = total_vol
            cluster["avg_difficulty"] = total_diff // max(len(kept), 1)
            # Update main_phrase if it was removed
            main = cluster.get("main_phrase", "")
            kept_phrases = {p["phrase"].lower() for p in kept}
            if main.lower() not in kept_phrases:
                best = max(kept, key=lambda p: p.get("volume", 0))
                cluster["main_phrase"] = best["phrase"]

            result.append(cluster)

        if filtered_total:
            log.info(
                "keywords_filtered_low_quality",
                removed=filtered_total,
                clusters_before=len(clusters),
                clusters_after=len(result),
            )

        return result

    async def generate_clusters_direct(
        self,
        products: str,
        geography: str,
        quantity: int,
        project_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """AI-only path: generate clusters directly in ONE call (E03 fallback).

        Used when DataForSEO returns 0 results. Instead of two sequential AI
        calls (fallback_phrases → cluster), this generates clustered keywords
        in a single request. ~60-90s instead of ~300s.
        """
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        company_name = (project.company_name or "") if project else ""
        specialization = (project.specialization or "") if project else ""

        context = {
            "raw_count": 0,
            "raw_keywords_json": "[]",
            "extra_count": min(quantity, 50),
            "products": products,
            "geography": geography,
            "company_name": company_name,
            "specialization": specialization,
            "language": "ru",
        }

        result = await self._orchestrator.generate(
            GenerationRequest(
                task="keywords",
                context=context,
                user_id=user_id,
                response_schema=CLUSTER_SCHEMA,
            )
        )

        clusters: list[dict[str, Any]] = []
        if isinstance(result.content, dict):
            clusters = result.content.get("clusters", [])

        # Mark all phrases as AI-suggested, assign defaults
        for cluster in clusters:
            total_vol = 0
            for p in cluster.get("phrases", []):
                p.setdefault("ai_suggested", True)
                p.setdefault("volume", 0)
                p.setdefault("difficulty", 0)
                p.setdefault("cpc", 0.0)
                p.setdefault("intent", "informational")
                total_vol += p.get("volume", 0)
            cluster.setdefault("total_volume", total_vol)
            cluster.setdefault("avg_difficulty", 0)

        return clusters
