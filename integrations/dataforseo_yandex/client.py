"""DataForSEO v3 — Яндекс SERP + Keywords Data.

Используется ТОЛЬКО разделом Bamboodom Аналитика для трекинга позиций
по ключевикам и keyword research (4I).

В отличие от Google-эндпоинтов из services/external/dataforseo.py,
для Яндекса DataForSEO разрешает location_code=2643 (Russia) и
language_code='ru' — это нативное окружение для bamboodom.

Эндпоинты:
- POST /v3/serp/yandex/organic/live/advanced — реальная выдача Яндекса.
  Возвращает упорядоченный список items с rank_absolute, url, domain.
  Стоимость: $0.0006 за запрос (1000 ключевиков = $0.6).

- POST /v3/keywords_data/yandex/search_volume/live — частотность из
  Wordstat. До 1000 ключей за запрос. Стоимость: $0.05 за запрос.

- POST /v3/keywords_data/yandex/keywords_for_keywords/live — расширение
  посевных ключей похожими (для keyword research). Стоимость: $0.075.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from bot.config import get_settings

log = structlog.get_logger()

_API_BASE = "https://api.dataforseo.com/v3"
_DEFAULT_LOCATION = 2643  # Russia
_DEFAULT_LANGUAGE = "ru"
_DEFAULT_TIMEOUT = 30.0
_MAX_RETRIES = 2
_RETRY_DELAYS = (0.5, 1.0, 2.0)


@dataclass(frozen=True, slots=True)
class SerpRank:
    """Позиция домена в выдаче Яндекса по конкретному запросу."""

    keyword: str
    position: int | None  # None если не в топ-100
    url: str | None
    title: str | None
    found_in_top: int = 100  # глубина проверки


@dataclass(frozen=True, slots=True)
class YandexKeywordVolume:
    """Частотность из Wordstat."""

    phrase: str
    volume: int
    competition: float | None  # 0.0-1.0 если есть данные


class DataForSEOError(Exception):
    """Raised when DataForSEO API returns an error."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        self.message = message
        super().__init__(f"DataForSEO error {status_code}: {message}")


class DataForSEOYandexClient:
    """DataForSEO Yandex API клиент. Async, Basic Auth, retry на 429/5xx."""

    def __init__(
        self,
        login: str = "",
        password: str = "",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        s = get_settings()
        self._login = login or s.dataforseo_login or ""
        self._password = password or (s.dataforseo_password.get_secret_value() if s.dataforseo_password else "")
        self._http = http_client
        self._configured = bool(self._login and self._password)

    @property
    def configured(self) -> bool:
        return self._configured

    async def _request(self, endpoint: str, payload: list[dict[str, Any]]) -> dict[str, Any]:
        if not self._configured:
            raise DataForSEOError(0, "DATAFORSEO_LOGIN/PASSWORD не настроены")
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                if self._http is not None:
                    resp = await self._http.post(
                        f"{_API_BASE}{endpoint}",
                        json=payload,
                        auth=(self._login, self._password),
                        timeout=_DEFAULT_TIMEOUT,
                    )
                else:
                    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
                        resp = await client.post(
                            f"{_API_BASE}{endpoint}",
                            json=payload,
                            auth=(self._login, self._password),
                            timeout=_DEFAULT_TIMEOUT,
                        )
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(_RETRY_DELAYS[attempt])
                    continue
                raise DataForSEOError(0, f"network: {exc}") from exc

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < _MAX_RETRIES:
                    delay = _RETRY_DELAYS[attempt]
                    try:
                        ra = float(resp.headers.get("Retry-After") or 0)
                        if ra > 0:
                            delay = min(ra, 60.0)
                    except ValueError:
                        pass
                    await asyncio.sleep(delay)
                    continue
                raise DataForSEOError(resp.status_code, resp.text[:300])

            if resp.status_code >= 400:
                raise DataForSEOError(resp.status_code, resp.text[:300])

            try:
                return resp.json()
            except ValueError as exc:
                raise DataForSEOError(0, f"non-JSON: {resp.text[:200]}") from exc

        raise DataForSEOError(0, f"exhausted retries: {last_exc!r}")

    # ---- Public methods ----------------------------------------------

    async def check_serp_ranks(
        self,
        keywords: list[str],
        target_domain: str = "bamboodom.ru",
        depth: int = 100,
    ) -> list[SerpRank]:
        """Проверить позиции домена в Яндекс-выдаче по списку ключей.

        Делает один параллельный запрос на каждый ключ (DataForSEO API
        принимает массив tasks, но возвращает результат тоже массивом).
        Не делать >50 ключей за раз — может растянуться по времени и стоимости.
        """
        if not keywords:
            return []
        payload = [
            {
                "language_code": _DEFAULT_LANGUAGE,
                "location_code": _DEFAULT_LOCATION,
                "keyword": kw,
                "depth": depth,
                "device": "desktop",
            }
            for kw in keywords
        ]
        data = await self._request("/serp/yandex/organic/live/advanced", payload)
        tasks = data.get("tasks") or []
        out: list[SerpRank] = []
        target = target_domain.lower()
        for task in tasks:
            kw_in = (task.get("data") or {}).get("keyword") or ""
            results = task.get("result") or []
            position: int | None = None
            url: str | None = None
            title: str | None = None
            for res in results:
                for item in res.get("items") or []:
                    if item.get("type") != "organic":
                        continue
                    domain = (item.get("domain") or "").lower()
                    if domain == target or domain.endswith("." + target):
                        position = int(item.get("rank_absolute") or item.get("rank_group") or 0) or None
                        url = item.get("url") or ""
                        title = item.get("title") or ""
                        break
                if position is not None:
                    break
            out.append(SerpRank(keyword=kw_in, position=position, url=url, title=title, found_in_top=depth))
        return out

    async def keyword_volumes(self, keywords: list[str]) -> list[YandexKeywordVolume]:
        """Частотность из Яндекс.Wordstat. До 1000 ключей за один вызов."""
        if not keywords:
            return []
        payload = [
            {
                "language_code": _DEFAULT_LANGUAGE,
                "location_code": _DEFAULT_LOCATION,
                "keywords": keywords[:1000],
            }
        ]
        data = await self._request("/keywords_data/yandex/search_volume/live", payload)
        tasks = data.get("tasks") or []
        out: list[YandexKeywordVolume] = []
        for task in tasks:
            for item in task.get("result") or []:
                phrase = item.get("keyword") or ""
                vol = int(item.get("search_volume") or 0)
                comp = item.get("competition")
                if comp is not None:
                    try:
                        comp = float(comp)
                    except TypeError, ValueError:
                        comp = None
                out.append(YandexKeywordVolume(phrase=phrase, volume=vol, competition=comp))
        return out

    async def keywords_for_seed(
        self,
        seed: str,
        limit: int = 50,
    ) -> list[YandexKeywordVolume]:
        """Расширение посевного ключа похожими через keywords_for_keywords."""
        payload = [
            {
                "language_code": _DEFAULT_LANGUAGE,
                "location_code": _DEFAULT_LOCATION,
                "keywords": [seed],
                "limit": limit,
            }
        ]
        data = await self._request("/keywords_data/yandex/keywords_for_keywords/live", payload)
        tasks = data.get("tasks") or []
        out: list[YandexKeywordVolume] = []
        for task in tasks:
            for item in task.get("result") or []:
                phrase = item.get("keyword") or ""
                vol = int(item.get("search_volume") or 0)
                comp = item.get("competition")
                if comp is not None:
                    try:
                        comp = float(comp)
                    except TypeError, ValueError:
                        comp = None
                out.append(YandexKeywordVolume(phrase=phrase, volume=vol, competition=comp))
        return out
