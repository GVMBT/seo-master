"""DataForSEO v3 client — production implementation.

Spec: docs/API_CONTRACTS.md section 8.2
Edge case E03: DataForSEO unavailable -> fallback to AI-generated keywords.

API endpoints:
  - keyword_suggestions: POST /v3/dataforseo_labs/google/keyword_suggestions/live
  - related_keywords: POST /v3/dataforseo_labs/google/related_keywords/live
  - enrich_keywords (bulk): POST /v3/keywords_data/google_ads/search_volume/live
  - search_intent: POST /v3/dataforseo_labs/google/search_intent/live (P2)
  - check_rank: POST /v3/serp/google/organic/live/regular (P2)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

# Max keywords per search_volume batch (API limit is 1000, we use 700 for safety)
_ENRICH_BATCH_SIZE = 700

# Max retries on transient errors
_MAX_RETRIES = 2
_RETRY_DELAYS = (0.5, 1.0, 2.0)  # seconds, exponential backoff


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


class DataForSEOError(Exception):
    """Raised when DataForSEO API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"DataForSEO error {status_code}: {message}")


class DataForSEOClient:
    """DataForSEO v3 client — production implementation.

    Uses Basic Auth (login:password).
    Batch: enrich — up to 700 phrases per request.
    suggestions/related — 1 seed per request.
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
        self._configured = bool(login and password)

    async def _request(
        self,
        endpoint: str,
        payload: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Send POST request to DataForSEO with Basic Auth and retry logic."""
        url = f"{self._base}/{endpoint}"

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await self._http.post(
                    url,
                    json=payload,
                    auth=(self._login, self._password),
                    timeout=30.0,
                )
                resp.raise_for_status()
                data: dict[str, Any] = resp.json()

                # Check top-level status
                status_code = data.get("status_code", 0)
                if status_code != 20000:
                    msg = data.get("status_message", "Unknown error")
                    raise DataForSEOError(status_code, msg)

                return data

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                log.warning(
                    "dataforseo_retry",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                continue
            except DataForSEOError:
                raise
            except httpx.HTTPStatusError as exc:
                raise DataForSEOError(
                    exc.response.status_code,
                    f"HTTP {exc.response.status_code}",
                ) from exc

        raise DataForSEOError(0, f"All {_MAX_RETRIES + 1} attempts failed: {last_exc}")

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
        """
        if not self._configured:
            log.warning("dataforseo_not_configured", method="keyword_suggestions")
            return []

        log.info(
            "dataforseo_keyword_suggestions",
            seed=seed,
            location_code=location_code,
            limit=limit,
        )

        payload = [
            {
                "keyword": seed,
                "location_code": location_code,
                "language_code": language_code,
                "limit": min(limit, 1000),
                "include_seed_keyword": True,
                "order_by": ["keyword_info.search_volume,desc"],
            }
        ]

        try:
            data = await self._request(
                "dataforseo_labs/google/keyword_suggestions/live",
                payload,
            )
        except (DataForSEOError, httpx.HTTPError) as exc:
            log.error("dataforseo_suggestions_failed", seed=seed, error=str(exc))
            return []

        return self._parse_suggestions(data)

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
        """
        if not self._configured:
            log.warning("dataforseo_not_configured", method="related_keywords")
            return []

        log.info(
            "dataforseo_related_keywords",
            seed=seed,
            location_code=location_code,
            limit=limit,
        )

        payload = [
            {
                "keyword": seed,
                "location_code": location_code,
                "language_code": language_code,
                "limit": min(limit, 1000),
                "depth": 2,
                "order_by": ["keyword_data.keyword_info.search_volume,desc"],
            }
        ]

        try:
            data = await self._request(
                "dataforseo_labs/google/related_keywords/live",
                payload,
            )
        except (DataForSEOError, httpx.HTTPError) as exc:
            log.error("dataforseo_related_failed", seed=seed, error=str(exc))
            return []

        return self._parse_related(data)

    async def enrich_keywords(
        self,
        phrases: list[str],
        location_code: int = 2643,
        language_code: str = "ru",
    ) -> list[KeywordData]:
        """Enrich keywords with volume, difficulty, CPC.

        POST /v3/keywords_data/google_ads/search_volume/live
        Batch: up to 700 phrases per request (we chunk if more).
        Cost: $0.0001/phrase.
        """
        if not self._configured:
            log.warning("dataforseo_not_configured", method="enrich_keywords")
            return []

        if not phrases:
            return []

        log.info(
            "dataforseo_enrich_keywords",
            count=len(phrases),
            location_code=location_code,
        )

        results: list[KeywordData] = []

        # Chunk into batches of _ENRICH_BATCH_SIZE
        for i in range(0, len(phrases), _ENRICH_BATCH_SIZE):
            batch = phrases[i : i + _ENRICH_BATCH_SIZE]
            payload = [
                {
                    "keywords": batch,
                    "location_code": location_code,
                    "language_code": language_code,
                    "sort_by": "search_volume",
                }
            ]

            try:
                data = await self._request(
                    "keywords_data/google_ads/search_volume/live",
                    payload,
                )
                results.extend(self._parse_enrich(data))
            except (DataForSEOError, httpx.HTTPError) as exc:
                log.error(
                    "dataforseo_enrich_failed",
                    batch_start=i,
                    batch_size=len(batch),
                    error=str(exc),
                )
                # Partial failure is OK — continue with next batch

        return results

    # ------------------------------------------------------------------
    # Response parsers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_suggestions(data: dict[str, Any]) -> list[KeywordSuggestion]:
        """Parse keyword_suggestions/live response."""
        results: list[KeywordSuggestion] = []
        tasks = data.get("tasks", [])
        if not tasks:
            return results

        task = tasks[0]
        if task.get("status_code") != 20000:
            log.warning("dataforseo_task_error", status=task.get("status_code"))
            return results

        for result_block in task.get("result", []) or []:
            for item in result_block.get("items", []) or []:
                kw_info = item.get("keyword_info", {}) or {}
                phrase = item.get("keyword", "")
                if not phrase:
                    continue
                results.append(
                    KeywordSuggestion(
                        phrase=phrase,
                        volume=kw_info.get("search_volume") or 0,
                        cpc=kw_info.get("cpc") or 0.0,
                        competition=kw_info.get("competition") or 0.0,
                    )
                )

        log.info("dataforseo_suggestions_parsed", count=len(results))
        return results

    @staticmethod
    def _parse_related(data: dict[str, Any]) -> list[KeywordSuggestion]:
        """Parse related_keywords/live response.

        Related keywords have a different structure:
        items[].keyword_data.keyword_info vs items[].keyword_info
        """
        results: list[KeywordSuggestion] = []
        tasks = data.get("tasks", [])
        if not tasks:
            return results

        task = tasks[0]
        if task.get("status_code") != 20000:
            log.warning("dataforseo_task_error", status=task.get("status_code"))
            return results

        for result_block in task.get("result", []) or []:
            for item in result_block.get("items", []) or []:
                kw_data = item.get("keyword_data", {}) or {}
                kw_info = kw_data.get("keyword_info", {}) or {}
                phrase = kw_data.get("keyword", "")
                if not phrase:
                    continue
                results.append(
                    KeywordSuggestion(
                        phrase=phrase,
                        volume=kw_info.get("search_volume") or 0,
                        cpc=kw_info.get("cpc") or 0.0,
                        competition=kw_info.get("competition") or 0.0,
                    )
                )

        log.info("dataforseo_related_parsed", count=len(results))
        return results

    @staticmethod
    def _parse_enrich(data: dict[str, Any]) -> list[KeywordData]:
        """Parse search_volume/live response.

        Response: tasks[0].result[] — flat list of keyword objects.
        competition is a string (LOW/MEDIUM/HIGH), competition_index is 0-100.
        """
        results: list[KeywordData] = []
        tasks = data.get("tasks", [])
        if not tasks:
            return results

        task = tasks[0]
        if task.get("status_code") != 20000:
            log.warning("dataforseo_task_error", status=task.get("status_code"))
            return results

        for item in task.get("result", []) or []:
            phrase = item.get("keyword", "")
            if not phrase:
                continue

            # Map competition level to intent heuristic
            competition = (item.get("competition") or "").upper()
            intent = "commercial" if competition == "HIGH" else "informational"

            results.append(
                KeywordData(
                    phrase=phrase,
                    volume=item.get("search_volume") or 0,
                    difficulty=item.get("competition_index") or 0,
                    cpc=item.get("cpc") or 0.0,
                    intent=intent,
                )
            )

        log.info("dataforseo_enrich_parsed", count=len(results))
        return results
