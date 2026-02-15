"""Serper.dev client for Google search data.

Spec: docs/API_CONTRACTS.md section 8.3
Edge case E04: Serper unavailable -> return empty result, article generated without Serper data.

Caching: 24h in Redis (key: serper:{md5(query)}).
All public methods return empty result on failure (graceful degradation).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

SERPER_API_BASE = "https://google.serper.dev"
_SERPER_TIMEOUT = 10.0
_CACHE_TTL = 86400  # 24 hours


@dataclass(frozen=True, slots=True)
class SerperResult:
    """Result of a Serper search query."""

    organic: list[dict[str, Any]]  # [{title, link, snippet, position}]
    people_also_ask: list[dict[str, Any]]  # [{question, snippet, link}]
    related_searches: list[str]


def _empty_result() -> SerperResult:
    """Return an empty search result for graceful degradation."""
    return SerperResult(organic=[], people_also_ask=[], related_searches=[])


def _cache_key(query: str) -> str:
    """Build Redis cache key from query string."""
    query_hash = hashlib.md5(query.encode()).hexdigest()  # noqa: S324  # nosec B324 — cache key, not security
    return f"serper:{query_hash}"


class SerperClient:
    """Client for Serper.dev Google Search API.

    Uses shared httpx.AsyncClient (never creates its own).
    Results are cached in Redis for 24 hours.
    Cost: ~$0.001 per query.
    """

    def __init__(
        self,
        api_key: str,
        http_client: httpx.AsyncClient,
        redis: Any,
    ) -> None:
        self._api_key = api_key
        self._http = http_client
        self._redis = redis

    async def search(
        self,
        query: str,
        num: int = 10,
        gl: str = "ru",
        hl: str = "ru",
    ) -> SerperResult:
        """Google search via Serper.

        POST https://google.serper.dev/search
        Headers: X-API-KEY
        Body: {q, num, gl, hl}
        Cache: 24h in Redis (key: serper:{md5(query)})

        E04: on error -> return empty result (graceful degradation).
        Retry: 2 attempts. On unavailability -> empty result.
        """
        # Check Redis cache first
        key = _cache_key(query)
        cached = await self._try_cache_get(key)
        if cached is not None:
            log.debug("serper.cache_hit", query=query)
            return cached

        # Make API request with retry (2 attempts)
        result = await self._search_with_retry(query, num, gl, hl, attempts=2)

        # Cache successful result
        if result.organic:
            await self._try_cache_set(key, result)

        return result

    async def _search_with_retry(
        self,
        query: str,
        num: int,
        gl: str,
        hl: str,
        attempts: int,
    ) -> SerperResult:
        """Execute search with retry logic."""
        last_error: str = ""

        for attempt in range(1, attempts + 1):
            try:
                resp = await self._http.post(
                    f"{SERPER_API_BASE}/search",
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json={"q": query, "num": num, "gl": gl, "hl": hl},
                    timeout=_SERPER_TIMEOUT,
                )
                resp.raise_for_status()
                body = resp.json()

                organic = body.get("organic", [])
                paa_raw = body.get("peopleAlsoAsk", [])
                related_raw = body.get("relatedSearches", [])

                # PAA returns objects {question, snippet, link}
                people_also_ask: list[dict[str, Any]] = []
                for item in paa_raw:
                    if isinstance(item, dict):
                        people_also_ask.append(item)
                    elif isinstance(item, str):
                        people_also_ask.append({"question": item})

                related_searches: list[str] = []
                for item in related_raw:
                    if isinstance(item, dict):
                        related_searches.append(item.get("query", ""))
                    elif isinstance(item, str):
                        related_searches.append(item)

                result = SerperResult(
                    organic=organic,
                    people_also_ask=people_also_ask,
                    related_searches=[s for s in related_searches if s],
                )
                log.info(
                    "serper.search_success",
                    query=query,
                    organic_count=len(organic),
                    paa_count=len(people_also_ask),
                )
                return result

            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = str(exc)
                log.warning(
                    "serper.search_attempt_failed",
                    query=query,
                    attempt=attempt,
                    error=last_error,
                )

        # E04: all attempts failed -> return empty result
        log.warning(
            "serper.search_failed_all_attempts",
            query=query,
            attempts=attempts,
            last_error=last_error,
        )
        return _empty_result()

    async def _try_cache_get(self, key: str) -> SerperResult | None:
        """Try to get cached result from Redis. Returns None on miss or error."""
        try:
            if self._redis is None:
                return None
            raw = await self._redis.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            return SerperResult(
                organic=data.get("organic", []),
                people_also_ask=data.get("people_also_ask", []),
                related_searches=data.get("related_searches", []),
            )
        except Exception:
            log.debug("serper.cache_get_error", key=key)
            return None

    async def _try_cache_set(self, key: str, result: SerperResult) -> None:
        """Try to cache result in Redis. Silently ignores errors."""
        try:
            if self._redis is None:
                return
            data = json.dumps(
                {
                    "organic": result.organic,
                    "people_also_ask": result.people_also_ask,
                    "related_searches": result.related_searches,
                }
            )
            await self._redis.set(key, data, ex=_CACHE_TTL)
        except Exception:
            log.debug("serper.cache_set_error", key=key)
