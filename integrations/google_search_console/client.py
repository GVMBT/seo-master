"""Google Search Console Search Analytics API client (4G).

API endpoint: POST https://searchconsole.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query

Auth: Bearer access_token (получаем через refresh_token из Redis).
Quota: 1200 requests/min/user.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from bot.config import get_settings
from integrations.google_search_console.oauth import refresh_access_token

log = structlog.get_logger()

_API_BASE = "https://searchconsole.googleapis.com/webmasters/v3"
GSC_REFRESH_REDIS_KEY = "bamboodom:gsc:refresh"
GSC_ACCESS_REDIS_KEY = "bamboodom:gsc:access"


class GSCError(Exception):
    """GSC API error."""


class GoogleTokenError(Exception):
    """Ошибка с токеном (нет refresh / refresh failed)."""


@dataclass
class GSCQuery:
    keys: list[str]
    clicks: int
    impressions: int
    ctr: float
    position: float


class GoogleSearchConsoleClient:
    """GSC клиент. Получает access_token из Redis, рефрешит при необходимости."""

    def __init__(self, redis: Any, site_url: str = "https://bamboodom.ru/") -> None:
        self.redis = redis
        self.site_url = site_url
        s = get_settings()
        self._client_id = s.google_oauth_client_id
        self._client_secret = s.google_oauth_client_secret.get_secret_value()

    async def _get_refresh_token(self) -> str:
        raw = await self.redis.get(GSC_REFRESH_REDIS_KEY)
        if not raw:
            raise GoogleTokenError("Refresh-токен не найден. Нажмите «Авторизовать GSC» в боте.")
        return str(raw)

    async def _get_access_token(self) -> str:
        # Кэш в Redis (~50 мин)
        try:
            raw = await self.redis.get(GSC_ACCESS_REDIS_KEY)
        except Exception:
            raw = None
        if raw:
            try:
                payload = json.loads(raw)
                if payload.get("expires_at", 0) - time.time() > 60:
                    return str(payload["access_token"])
            except (ValueError, KeyError, TypeError):
                pass

        rt = await self._get_refresh_token()
        try:
            tok = await refresh_access_token(rt, self._client_id, self._client_secret)
        except Exception as exc:
            raise GoogleTokenError(f"Не удалось обновить токен: {exc}") from exc

        access_token = tok.get("access_token") or ""
        expires_in = int(tok.get("expires_in") or 3600)
        if not access_token:
            raise GoogleTokenError(f"Google не вернул access_token: {tok}")
        # Сохраняем access (TTL чуть меньше expires_in)
        cache_payload = {
            "access_token": access_token,
            "expires_at": time.time() + expires_in - 60,
        }
        with contextlib.suppress(Exception):
            await self.redis.set(
                GSC_ACCESS_REDIS_KEY,
                json.dumps(cache_payload),
                ex=max(60, expires_in - 60),
            )
        return access_token

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20.0,
            )
        if resp.status_code in (401, 403):
            raise GSCError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise GSCError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    async def _get(self, path: str) -> dict[str, Any]:
        token = await self._get_access_token()
        url = f"{_API_BASE}{path}"
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20.0,
            )
        if resp.status_code >= 400:
            raise GSCError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    # ---- Public API --------------------------------------------------

    async def list_sites(self) -> list[dict[str, Any]]:
        data = await self._get("/sites")
        return data.get("siteEntry") or []

    async def search_analytics_query(
        self,
        date1: str,
        date2: str,
        dimensions: list[str] | None = None,
        row_limit: int = 25,
    ) -> list[GSCQuery]:
        """POST /sites/{siteUrl}/searchAnalytics/query.

        dimensions: list из {date, country, device, page, query, searchAppearance}.
        Пустые dimensions = только totals.
        """
        body: dict[str, Any] = {
            "startDate": date1,
            "endDate": date2,
            "rowLimit": row_limit,
        }
        if dimensions:
            body["dimensions"] = dimensions

        site = quote(self.site_url, safe="")
        path = f"/sites/{site}/searchAnalytics/query"
        data = await self._post(path, body)
        rows = data.get("rows") or []
        out: list[GSCQuery] = []
        for r in rows:
            out.append(
                GSCQuery(
                    keys=r.get("keys") or [],
                    clicks=int(r.get("clicks") or 0),
                    impressions=int(r.get("impressions") or 0),
                    ctr=float(r.get("ctr") or 0.0),
                    position=float(r.get("position") or 0.0),
                )
            )
        return out

    async def top_queries(self, days: int = 28, limit: int = 25) -> list[GSCQuery]:
        """Топ запросов по impressions за последние N дней."""
        date2 = (dt.date.today() - dt.timedelta(days=2)).isoformat()  # GSC отстаёт ~2 дня
        date1 = (dt.date.today() - dt.timedelta(days=days + 2)).isoformat()
        return await self.search_analytics_query(date1, date2, ["query"], row_limit=limit)

    async def top_pages(self, days: int = 28, limit: int = 25) -> list[GSCQuery]:
        date2 = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        date1 = (dt.date.today() - dt.timedelta(days=days + 2)).isoformat()
        return await self.search_analytics_query(date1, date2, ["page"], row_limit=limit)

    async def totals(self, days: int = 28) -> GSCQuery:
        date2 = (dt.date.today() - dt.timedelta(days=2)).isoformat()
        date1 = (dt.date.today() - dt.timedelta(days=days + 2)).isoformat()
        rows = await self.search_analytics_query(date1, date2, [], row_limit=1)
        if not rows:
            return GSCQuery(keys=[], clicks=0, impressions=0, ctr=0.0, position=0.0)
        return rows[0]
