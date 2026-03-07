"""Serper.dev client for Google search data.

Spec: docs/API_CONTRACTS.md section 8.3
Edge case E04: Serper unavailable -> return empty result, article generated without Serper data.
Retry: C10 — retry on 429/5xx with backoff, Retry-After support.

Endpoints:
- /search — organic results + PAA + related searches (24h cache)
- /news — Google News results for freshness/trends (6h cache)
- /autocomplete — search suggestions for LSI keywords (3d cache)

Caching: Redis per-endpoint TTL.
All public methods return empty result on failure (graceful degradation).
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

log = structlog.get_logger()

_MAX_RETRY_AFTER = 60.0

SERPER_API_BASE = "https://google.serper.dev"
_SERPER_TIMEOUT = 10.0
_CACHE_TTL = 86400  # 24 hours
_NEWS_CACHE_TTL = 21600  # 6 hours (news = time-sensitive)
_AUTOCOMPLETE_CACHE_TTL = 259200  # 3 days (suggestions change slowly)


@dataclass(frozen=True, slots=True)
class SerperResult:
    """Result of a Serper search query."""

    organic: list[dict[str, Any]]  # [{title, link, snippet, position}]
    people_also_ask: list[dict[str, Any]]  # [{question, snippet, link}]
    related_searches: list[str]


@dataclass(frozen=True, slots=True)
class NewsResult:
    """Result of a Serper news search."""

    news: list[dict[str, Any]]  # [{title, link, snippet, date, source, imageUrl, position}]


def _empty_news() -> NewsResult:
    """Return an empty news result for graceful degradation."""
    return NewsResult(news=[])


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
        gl: str = "ua",
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

    async def search_news(
        self,
        query: str,
        num: int = 5,
        gl: str = "ua",
        hl: str = "ru",
        tbs: str = "qdr:m",
    ) -> NewsResult:
        """Google News search via Serper.

        POST https://google.serper.dev/news
        Body: {q, num, gl, hl, tbs}
        Cache: 6h in Redis (key: serper_news:{md5(query)})
        tbs values: qdr:d (day), qdr:w (week), qdr:m (month), qdr:y (year)

        E04: on error -> return empty result (graceful degradation).
        """
        cache_key = f"serper_news:{hashlib.md5(query.encode()).hexdigest()}"  # noqa: S324  # nosec B324
        cached = await self._try_generic_cache_get(cache_key)
        if cached is not None and isinstance(cached, list):
            log.debug("serper.news_cache_hit", query=query)
            return NewsResult(news=cached)

        try:
            result = await self._request_with_retry(
                endpoint="/news",
                payload={"q": query, "num": num, "gl": gl, "hl": hl, "tbs": tbs},
            )
            news = result.get("news", [])
            if news:
                log.info("serper.news_success", query=query, count=len(news))
                await self._try_generic_cache_set(cache_key, news, ttl=_NEWS_CACHE_TTL)
            else:
                log.debug("serper.news_empty", query=query)
            return NewsResult(news=news)
        except Exception:
            log.warning("serper.news_failed", query=query, exc_info=True)
            return _empty_news()

    async def autocomplete(
        self,
        query: str,
        gl: str = "ua",
        hl: str = "ru",
    ) -> list[str]:
        """Google Autocomplete suggestions via Serper.

        POST https://google.serper.dev/autocomplete
        Body: {q, gl, hl}
        Cache: 3d in Redis (key: serper_ac:{md5(query)})

        Returns list of suggestion strings. Empty list on failure.
        """
        cache_key = f"serper_ac:{hashlib.md5(query.encode()).hexdigest()}"  # noqa: S324  # nosec B324
        cached = await self._try_generic_cache_get(cache_key)
        if cached is not None and isinstance(cached, list):
            log.debug("serper.autocomplete_cache_hit", query=query)
            return [str(s) for s in cached]

        try:
            result = await self._request_with_retry(
                endpoint="/autocomplete",
                payload={"q": query, "gl": gl, "hl": hl},
            )
            suggestions = [str(s) for s in result.get("suggestions", []) if s]
            if suggestions:
                log.info("serper.autocomplete_success", query=query, count=len(suggestions))
                await self._try_generic_cache_set(cache_key, suggestions, ttl=_AUTOCOMPLETE_CACHE_TTL)
            else:
                log.debug("serper.autocomplete_empty", query=query)
            return suggestions
        except Exception:
            log.warning("serper.autocomplete_failed", query=query, exc_info=True)
            return []

    async def _request_with_retry(
        self,
        endpoint: str,
        payload: dict[str, Any],
        attempts: int = 2,
    ) -> dict[str, Any]:
        """Generic Serper API request with retry logic.

        Used by search_news() and autocomplete().
        Retries on 429/5xx, no retry on 401/403.
        """
        last_error: str = ""
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._http.post(
                    f"{SERPER_API_BASE}{endpoint}",
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=_SERPER_TIMEOUT,
                )
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
            except httpx.HTTPStatusError as exc:
                last_error = str(exc)
                status = exc.response.status_code
                if status in (401, 403):
                    break
                if status in (429, 500, 502, 503, 504) and attempt < attempts:
                    delay = 1.0 * (2**attempt)
                    if status == 429:
                        retry_after = exc.response.headers.get("Retry-After")
                        if retry_after:
                            with contextlib.suppress(ValueError, TypeError):
                                delay = min(float(retry_after), _MAX_RETRY_AFTER)
                    await asyncio.sleep(delay)
                    continue
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                last_error = str(exc)

        msg = f"Serper {endpoint} failed after {attempts} attempts: {last_error[:200]}"
        raise RuntimeError(msg)

    async def _search_with_retry(
        self,
        query: str,
        num: int,
        gl: str,
        hl: str,
        attempts: int,
    ) -> SerperResult:
        """Execute search with retry logic.

        Handles 429 with Retry-After header (C10).
        Retries on: timeout, connect, 429, 5xx.
        No retry on: 401/403 (auth errors).
        """
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
                if organic:
                    log.info(
                        "serper.search_success",
                        query=query,
                        organic_count=len(organic),
                        paa_count=len(people_also_ask),
                    )
                else:
                    log.warning(
                        "serper.empty_results",
                        query=query,
                        hint="Google returned 0 organic results — check gl/hl params or credits",
                    )
                return result

            except httpx.HTTPStatusError as exc:
                last_error = str(exc)
                status = exc.response.status_code
                # No retry on auth errors
                if status in (401, 403):
                    log.warning(
                        "serper.search_auth_failed",
                        query=query,
                        status=status,
                    )
                    break
                # Retry on 429 with Retry-After
                if status == 429 and attempt < attempts:
                    delay = 1.0
                    retry_after = exc.response.headers.get("Retry-After")
                    if retry_after:
                        with contextlib.suppress(ValueError, TypeError):
                            delay = min(float(retry_after), _MAX_RETRY_AFTER)
                    log.warning(
                        "http_retry",
                        operation="serper_search",
                        attempt=attempt,
                        max_retries=attempts - 1,
                        status=status,
                        delay_s=round(delay, 2),
                        error=last_error[:200],
                    )
                    await asyncio.sleep(delay)
                    continue
                # Retry on 5xx with backoff
                if status in (500, 502, 503, 504) and attempt < attempts:
                    backoff_delay = 1.0 * (2**attempt)
                    log.warning(
                        "http_retry",
                        operation="serper_search",
                        attempt=attempt,
                        max_retries=attempts - 1,
                        status=status,
                        delay_s=round(backoff_delay, 2),
                        error=last_error[:200],
                    )
                    await asyncio.sleep(backoff_delay)
                    continue
                log.warning(
                    "serper.search_attempt_failed",
                    query=query,
                    attempt=attempt,
                    error=last_error,
                )
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

    async def _try_generic_cache_get(self, key: str) -> Any:
        """Try to get generic JSON data from Redis cache. Returns None on miss."""
        try:
            if self._redis is None:
                return None
            raw = await self._redis.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception:
            log.debug("serper.cache_get_error", key=key)
            return None

    async def _try_generic_cache_set(self, key: str, data: Any, *, ttl: int) -> None:
        """Try to cache generic JSON data in Redis. Silently ignores errors."""
        try:
            if self._redis is None:
                return
            await self._redis.set(key, json.dumps(data, ensure_ascii=False), ex=ttl)
        except Exception:
            log.debug("serper.cache_set_error", key=key)
