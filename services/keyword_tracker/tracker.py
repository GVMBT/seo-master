"""Хранилище ключевиков и истории позиций для Bamboodom (4I.1).

Redis ключи:
    bamboodom:keywords:list           — JSON list[str] всех отслеживаемых ключей.
    bamboodom:keywords:rank:{date}    — JSON list[{keyword, position, url}] на дату.
                                         TTL 90 дней.

Дата = ISO YYYY-MM-DD (Europe/Moscow).
Каждый запуск `run_check` записывает новую запись на сегодняшнюю дату
(перезаписывает если уже была сегодня).

Дельта к прошлой неделе считается по дате `today - 7d`. Если такой нет,
ищется ближайшая в диапазоне 5-9 дней назад.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

import structlog

from integrations.dataforseo_yandex import DataForSEOError, DataForSEOYandexClient, SerpRank

log = structlog.get_logger()

LIST_KEY = "bamboodom:keywords:list"
RANK_KEY_PREFIX = "bamboodom:keywords:rank:"
HISTORY_TTL = 90 * 24 * 3600  # 90 дней
TZ = ZoneInfo("Europe/Moscow")
DEFAULT_KEYWORDS = [
    "wpc панели",
    "wpc панели для стен",
    "стеновые wpc панели",
    "гибкая керамика",
    "гибкая керамика для фасада",
    "реечные панели",
    "реечные панели для стен",
    "алюминиевые профили для wpc",
    "отделочные панели для стен",
    "декоративные стеновые панели",
]


@dataclass
class RankEntry:
    keyword: str
    position: int | None
    url: str | None
    delta_week: int | None = None  # +5 (упал), -3 (вырос), None если не было прошлой недели


def _today_str() -> str:
    return dt.datetime.now(TZ).date().isoformat()


def _date_str(d: dt.date) -> str:
    return d.isoformat()


# --------- Storage helpers ----------


async def get_keywords(redis: Any) -> list[str]:
    """Читает список ключевиков. Если пусто — возвращает DEFAULT_KEYWORDS."""
    try:
        raw = await redis.get(LIST_KEY)
    except Exception:
        return list(DEFAULT_KEYWORDS)
    if not raw:
        return list(DEFAULT_KEYWORDS)
    try:
        data = json.loads(raw)
        if isinstance(data, list) and data:
            return [str(k) for k in data]
    except ValueError:
        pass
    return list(DEFAULT_KEYWORDS)


async def set_keywords(redis: Any, keywords: list[str]) -> None:
    cleaned = sorted({k.strip().lower() for k in keywords if k and k.strip()})
    try:
        await redis.set(LIST_KEY, json.dumps(cleaned, ensure_ascii=False))
    except Exception:
        log.warning("kw_list_set_failed", exc_info=True)


async def add_keyword(redis: Any, keyword: str) -> list[str]:
    keywords = await get_keywords(redis)
    keyword = keyword.strip().lower()
    if keyword and keyword not in keywords:
        keywords.append(keyword)
        await set_keywords(redis, keywords)
    return keywords


async def remove_keyword(redis: Any, keyword: str) -> list[str]:
    keywords = await get_keywords(redis)
    keyword = keyword.strip().lower()
    keywords = [k for k in keywords if k != keyword]
    await set_keywords(redis, keywords)
    return keywords


# --------- History ----------


async def _read_history_for_date(redis: Any, date: dt.date) -> dict[str, dict[str, Any]] | None:
    """Возвращает map {keyword: {position, url}} для даты, или None если нет."""
    try:
        raw = await redis.get(RANK_KEY_PREFIX + _date_str(date))
    except Exception:
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return {item.get("keyword") or "": item for item in data if isinstance(item, dict)}


async def _save_history(redis: Any, date: dt.date, ranks: list[SerpRank]) -> None:
    payload = [{"keyword": r.keyword, "position": r.position, "url": r.url, "title": r.title} for r in ranks]
    try:
        await redis.set(
            RANK_KEY_PREFIX + _date_str(date),
            json.dumps(payload, ensure_ascii=False),
            ex=HISTORY_TTL,
        )
    except Exception:
        log.warning("kw_rank_save_failed", exc_info=True)


async def get_last_ranks(redis: Any) -> list[RankEntry]:
    """Возвращает последний прогон с дельтой к прошлой неделе.

    Если прогона ещё не было — пустой список.
    """
    today = dt.datetime.now(TZ).date()
    # Ищем последний прогон в окне 0-7 дней
    last_map: dict[str, dict[str, Any]] | None = None
    last_date: dt.date | None = None
    for delta in range(0, 8):
        d = today - dt.timedelta(days=delta)
        cur = await _read_history_for_date(redis, d)
        if cur:
            last_map = cur
            last_date = d
            break
    if not last_map or not last_date:
        return []

    # Ищем прогон ровно неделю назад (target = last_date - 7d)
    week_ago_target = last_date - dt.timedelta(days=7)
    week_map: dict[str, dict[str, Any]] | None = None
    for delta in range(-2, 3):  # окно 5-9 дней назад от last_date
        d = week_ago_target + dt.timedelta(days=delta)
        cur = await _read_history_for_date(redis, d)
        if cur:
            week_map = cur
            break

    out: list[RankEntry] = []
    for keyword, item in last_map.items():
        pos_now = item.get("position")
        url = item.get("url")
        delta_week: int | None = None
        if week_map and keyword in week_map:
            pos_old = (week_map[keyword] or {}).get("position")
            if pos_now is not None and pos_old is not None:
                delta_week = int(pos_now) - int(pos_old)
        out.append(RankEntry(keyword=keyword, position=pos_now, url=url, delta_week=delta_week))
    out.sort(key=lambda r: (r.position is None, r.position or 999))
    return out


# --------- Run ----------


async def run_check(redis: Any) -> tuple[list[RankEntry], int]:
    """Делает прогон всех ключей через DataForSEO, сохраняет, возвращает результаты с дельтой.

    Возвращает (entries, cost_cents) где cost_cents — оценка стоимости в центах.
    Стоимость: $0.0006 за SERP запрос → 0.06 цент. Округляем до 1 цента минимум.
    """
    keywords = await get_keywords(redis)
    if not keywords:
        return [], 0
    client = DataForSEOYandexClient()
    if not client.configured:
        raise DataForSEOError(0, "DATAFORSEO_LOGIN/PASSWORD не настроены")
    today = dt.datetime.now(TZ).date()
    try:
        ranks = await client.check_serp_ranks(keywords, target_domain="bamboodom.ru", depth=100)
    except DataForSEOError:
        raise
    await _save_history(redis, today, ranks)
    entries = await get_last_ranks(redis)
    cost_cents = max(1, round(len(keywords) * 0.06))
    return entries, cost_cents
