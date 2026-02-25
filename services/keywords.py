"""Keyword generation service — data-first pipeline.

Pipeline: DataForSEO suggestions/related → AI clustering → DataForSEO enrich.
Fallback (E03): if DataForSEO unavailable → AI generates phrases → cluster → enrich.
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

# Schema for AI keyword generation fallback
KEYWORDS_FALLBACK_SCHEMA: dict[str, Any] = {
    "name": "keywords_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "phrase": {"type": "string"},
                        "intent": {"type": "string"},
                    },
                    "required": ["phrase", "intent"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["keywords"],
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

    async def fetch_raw_phrases(
        self,
        products: str,
        geography: str,
        quantity: int,
        project_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """Step 1: DataForSEO suggestions + related. Fallback to AI if empty (E03).

        Strategy:
        1. Try each seed phrase from products (comma-separated)
        2. If Ukraine (2804) returns 0, retry with Kazakhstan (2398)
        3. If all DataForSEO attempts fail → AI fallback
        """
        seeds = [s.strip()[:100] for s in products.split(",") if s.strip()]
        if not seeds:
            seeds = [products.strip()[:100]]

        raw: list[dict[str, Any]] = []
        seen: set[str] = set()

        # Try seeds with default location, then fallback location
        locations = [_DEFAULT_LOCATION, _FALLBACK_LOCATION]
        for location in locations:
            for seed in seeds[:3]:  # max 3 seeds to avoid excessive API calls
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
            log.info("dataforseo_empty_location", location=location, seeds=seeds[:3])

        # E03 fallback: DataForSEO returned nothing → AI generates phrases
        if not raw:
            log.info("dataforseo_empty_fallback_to_ai", seeds=seeds[:3])
            raw = await self._ai_fallback_phrases(
                products,
                geography,
                quantity,
                project_id,
                user_id,
            )

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

    async def _ai_fallback_phrases(
        self,
        products: str,
        geography: str,
        quantity: int,
        project_id: int,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """AI fallback when DataForSEO is empty (E03).

        Uses separate 'keywords_fallback' prompt (v2-style) that generates
        phrases from scratch, unlike 'keywords' (v3) which clusters DataForSEO data.
        """
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        company_name = (project.company_name or "") if project else ""
        specialization = (project.specialization or "") if project else ""

        result = await self._orchestrator.generate(
            GenerationRequest(
                task="keywords_fallback",
                context={
                    "quantity": quantity,
                    "products": products,
                    "geography": geography,
                    "company_name": company_name,
                    "specialization": specialization,
                    "language": "ru",
                },
                user_id=user_id,
                response_schema=KEYWORDS_FALLBACK_SCHEMA,
            )
        )

        phrases: list[dict[str, Any]] = []
        if isinstance(result.content, dict):
            for kw in result.content.get("keywords", []):
                phrases.append(
                    {
                        "phrase": kw.get("phrase", ""),
                        "volume": 0,
                        "cpc": 0.0,
                        "ai_suggested": True,
                        "intent": kw.get("intent", "informational"),
                    }
                )

        return phrases
