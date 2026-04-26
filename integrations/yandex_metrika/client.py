"""Async HTTP-клиент для Yandex.Metrika Stat API v1.

Базовый endpoint: GET https://api-metrika.yandex.net/stat/v1/data
Auth: header `Authorization: OAuth <token>`
Параметры:
    ids       — counter_id (строка)
    date1     — начало (YYYY-MM-DD или относительно: today, yesterday, 7daysAgo)
    date2     — конец
    metrics   — comma-separated, eg "ym:s:visits,ym:s:users"
    dimensions — comma-separated (опционально)
    filters   — фильтры (опционально)
    sort      — поле для сортировки
    limit     — топ-N (default 100)

Документация: https://yandex.ru/dev/metrika/doc/api2/api_v1/intro.html
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from bot.config import get_settings
from integrations.yandex_metrika.exceptions import (
    YandexMetrikaAuthError,
    YandexMetrikaError,
    YandexMetrikaRateLimitError,
)

log = structlog.get_logger()

_API_BASE = "https://api-metrika.yandex.net/stat/v1/data"
_DEFAULT_TIMEOUT = 15.0
_MAX_ERROR_BODY = 500


@dataclass
class YandexMetrikaClient:
    """Async wrapper над Stat API v1."""

    token: str = ""
    counter_id: str = ""
    http_client: httpx.AsyncClient | None = None
    timeout: float = _DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        settings = get_settings()
        if not self.token:
            self.token = settings.yandex_metrika_token.get_secret_value()
        if not self.counter_id:
            self.counter_id = settings.yandex_metrika_counter_id

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise YandexMetrikaAuthError("YANDEX_METRIKA_TOKEN не настроен")
        return {
            "Authorization": f"OAuth {self.token}",
            "Accept": "application/x-yametrika+json",
        }

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.counter_id:
            raise YandexMetrikaAuthError("YANDEX_METRIKA_COUNTER_ID не настроен")
        full = {"ids": self.counter_id, "accuracy": "full", **params}
        headers = self._headers()
        try:
            if self.http_client is not None:
                resp = await self.http_client.get(_API_BASE, params=full, headers=headers, timeout=self.timeout)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.get(_API_BASE, params=full, headers=headers, timeout=self.timeout)
        except httpx.TimeoutException as exc:
            raise YandexMetrikaError(f"Timeout: {exc}") from exc
        except httpx.RequestError as exc:
            raise YandexMetrikaError(f"Network error: {exc}") from exc

        if resp.status_code in (401, 403):
            raise YandexMetrikaAuthError(f"HTTP {resp.status_code}: {resp.text[:_MAX_ERROR_BODY]}")
        if resp.status_code == 429:
            try:
                ra = int(resp.headers.get("Retry-After", "60"))
            except ValueError:
                ra = 60
            raise YandexMetrikaRateLimitError(ra)
        if resp.status_code >= 400:
            raise YandexMetrikaError(f"HTTP {resp.status_code}: {resp.text[:_MAX_ERROR_BODY]}")
        try:
            return resp.json()
        except ValueError as exc:
            raise YandexMetrikaError(f"Non-JSON response: {resp.text[:_MAX_ERROR_BODY]}") from exc

    # ---- Публичные методы ---------------------------------------------

    async def get_summary(self, date1: str = "yesterday", date2: str = "yesterday") -> dict[str, Any]:
        """Базовая сводка: визиты, посетители, просмотры, отказы, время.

        date1/date2 могут быть YYYY-MM-DD или relative (today, yesterday, 7daysAgo).
        Возвращает dict {visits, users, pageviews, bounce_rate, avg_visit_duration}.
        """
        params = {
            "metrics": ("ym:s:visits,ym:s:users,ym:s:pageviews,ym:s:bounceRate,ym:s:avgVisitDurationSeconds"),
            "date1": date1,
            "date2": date2,
        }
        data = await self._get(params)
        totals = (data.get("totals") or [[0, 0, 0, 0, 0]])[0]
        return {
            "visits": int(totals[0] or 0),
            "users": int(totals[1] or 0),
            "pageviews": int(totals[2] or 0),
            "bounce_rate": float(totals[3] or 0.0),
            "avg_visit_duration": float(totals[4] or 0.0),
            "date1": date1,
            "date2": date2,
        }

    async def get_top_pages(
        self,
        date1: str = "7daysAgo",
        date2: str = "yesterday",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Топ страниц по pageviews за период.

        Возвращает список {url, pageviews, users}.
        """
        params = {
            "metrics": "ym:pv:pageviews,ym:pv:users",
            "dimensions": "ym:pv:URL",
            "date1": date1,
            "date2": date2,
            "sort": "-ym:pv:pageviews",
            "limit": limit,
        }
        data = await self._get(params)
        out: list[dict[str, Any]] = []
        for item in data.get("data") or []:
            dims = item.get("dimensions") or []
            metrics = item.get("metrics") or []
            url = (dims[0] or {}).get("name", "—") if dims else "—"
            out.append(
                {
                    "url": url,
                    "pageviews": int(metrics[0] or 0) if len(metrics) > 0 else 0,
                    "users": int(metrics[1] or 0) if len(metrics) > 1 else 0,
                }
            )
        return out

    async def get_traffic_sources(
        self,
        date1: str = "7daysAgo",
        date2: str = "yesterday",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        """Источники трафика (organic, direct, referral, ...). Возвращает {source, visits}."""
        params = {
            "metrics": "ym:s:visits",
            "dimensions": "ym:s:trafficSource",
            "date1": date1,
            "date2": date2,
            "sort": "-ym:s:visits",
            "limit": limit,
        }
        data = await self._get(params)
        out: list[dict[str, Any]] = []
        for item in data.get("data") or []:
            dims = item.get("dimensions") or []
            metrics = item.get("metrics") or []
            name = (dims[0] or {}).get("name", "—") if dims else "—"
            out.append(
                {
                    "source": name,
                    "visits": int(metrics[0] or 0) if metrics else 0,
                }
            )
        return out

    async def get_top_search_phrases(
        self,
        date1: str = "7daysAgo",
        date2: str = "yesterday",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Топ поисковых запросов из Яндекса (ym:s:searchPhrase, only organic search)."""
        params = {
            "metrics": "ym:s:visits",
            "dimensions": "ym:s:searchPhrase",
            "filters": "ym:s:trafficSource=='organic'",
            "date1": date1,
            "date2": date2,
            "sort": "-ym:s:visits",
            "limit": limit,
        }
        data = await self._get(params)
        out: list[dict[str, Any]] = []
        for item in data.get("data") or []:
            dims = item.get("dimensions") or []
            metrics = item.get("metrics") or []
            phrase = (dims[0] or {}).get("name", "—") if dims else "—"
            if not phrase or phrase == "—" or phrase.startswith("not"):
                continue
            out.append(
                {
                    "phrase": phrase,
                    "visits": int(metrics[0] or 0) if metrics else 0,
                }
            )
        return out
