"""DataForSEO v3 client -- STUB for Phase 10.

Spec: docs/API_CONTRACTS.md section 8.2
Edge case E03: DataForSEO unavailable -> fallback to AI-generated keywords.

Actual implementation when API access is approved.
All methods return empty results (stub).

Future API endpoints:
  - keyword_suggestions: POST /v3/dataforseo_labs/google/keyword_suggestions/live
  - related_keywords: POST /v3/dataforseo_labs/google/related_keywords/live
  - enrich_keywords (bulk): POST /v3/keywords_data/google_ads/search_volume/live
  - search_intent: POST /v3/dataforseo_labs/google/search_intent/live (P2)
  - check_rank: POST /v3/serp/google/organic/live/regular (P2)
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class KeywordSuggestion:
    """A keyword suggestion from DataForSEO."""

    phrase: str
    volume: int
    cpc: float
    competition: float  # 0.0-1.0


@dataclass(frozen=True, slots=True)
class KeywordData:
    """Enriched keyword data with volume, difficulty, CPC."""

    phrase: str
    volume: int  # Monthly search volume
    difficulty: int  # 0-100
    cpc: float  # Cost per click in USD
    intent: str  # commercial, informational


class DataForSEOClient:
    """DataForSEO v3 client -- stub, actual implementation when API access approved.

    Uses Basic Auth (login:password).
    Batch: enrich -- up to 700 phrases per request.
    suggestions/related -- 1 seed per request.
    """

    def __init__(
        self,
        login: str,
        password: str,
        http_client: httpx.AsyncClient,
    ) -> None:
        self._login = login
        self._password = password
        self._http = http_client
        self._base = "https://api.dataforseo.com/v3"

    async def keyword_suggestions(
        self,
        seed: str,
        location_code: int = 2643,
        language_code: str = "ru",
        limit: int = 200,
    ) -> list[KeywordSuggestion]:
        """Get keyword suggestions for a seed phrase.

        POST /v3/dataforseo_labs/google/keyword_suggestions/live
        Cost: ~$0.01/request.

        Returns empty list (stub).
        """
        log.info(
            "dataforseo_stub_called",
            method="keyword_suggestions",
            seed=seed,
            location_code=location_code,
        )
        return []

    async def related_keywords(
        self,
        seed: str,
        location_code: int = 2643,
        language_code: str = "ru",
        limit: int = 100,
    ) -> list[KeywordSuggestion]:
        """Get related keywords for a seed phrase.

        POST /v3/dataforseo_labs/google/related_keywords/live
        Cost: ~$0.01/request.

        Returns empty list (stub).
        """
        log.info(
            "dataforseo_stub_called",
            method="related_keywords",
            seed=seed,
            location_code=location_code,
        )
        return []

    async def enrich_keywords(
        self,
        phrases: list[str],
        location_code: int = 2643,
        language_code: str = "ru",
    ) -> list[KeywordData]:
        """Enrich keywords with volume, difficulty, CPC.

        POST /v3/keywords_data/google_ads/search_volume/live
        Batch: up to 700 phrases per request.
        Cost: $0.0001/phrase.

        Returns empty list (stub).
        """
        log.info(
            "dataforseo_stub_called",
            method="enrich_keywords",
            count=len(phrases),
            location_code=location_code,
        )
        return []
