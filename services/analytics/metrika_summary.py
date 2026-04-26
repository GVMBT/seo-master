"""Формирование текстов сводок Я.Метрики для UI бота.

Не вызывает HTTP — только форматирование уже полученных данных.
"""

from __future__ import annotations

from typing import Any


def fmt_int(n: int | float) -> str:
    """1234 → '1 234'. Для красоты."""
    n = int(n)
    s = f"{n:,}".replace(",", " ")
    return s


def fmt_duration(sec: float) -> str:
    """108.5 → '1 мин 48 сек'."""
    s = int(sec)
    m, s = divmod(s, 60)
    if m == 0:
        return f"{s} сек"
    return f"{m} мин {s} сек"


def fmt_percent(p: float) -> str:
    """45.123 → '45.1%'."""
    return f"{p:.1f}%"


def shorten_url(url: str, max_len: int = 50) -> str:
    """Обрезает URL для экрана: главная как / , длинные — c '…'."""
    if not url or url == "—":
        return "—"
    if url.startswith("http"):
        from urllib.parse import urlparse

        p = urlparse(url)
        url = p.path or "/"
        if p.query:
            url = url + "?" + p.query
    if len(url) <= max_len:
        return url
    return url[: max_len - 1] + "…"


# Локализованные имена источников трафика — Метрика отдаёт английские
TRAFFIC_SOURCE_RU = {
    "organic": "Поиск Яндекса",
    "ad": "Реклама",
    "internal": "Внутренний переход",
    "referral": "Сайты",
    "direct": "Прямые заходы",
    "social": "Соц. сети",
    "email": "Email",
    "saved": "Закладки",
    "recommend": "Рекомендации",
    "messenger": "Мессенджеры",
}


def localize_source(name: str) -> str:
    return TRAFFIC_SOURCE_RU.get(name, name or "—")


def summarize_top_pages(items: list[dict[str, Any]], limit: int = 10) -> list[str]:
    """Возвращает список строк для UI: ' — /article.html?slug=… — 45 (12)'"""
    lines: list[str] = []
    for i, it in enumerate(items[:limit], start=1):
        url = shorten_url(it.get("url") or "—")
        pv = fmt_int(it.get("pageviews") or 0)
        users = fmt_int(it.get("users") or 0)
        lines.append(f"{i}. {url} — {pv} ({users} чел.)")
    return lines


def summarize_traffic_sources(items: list[dict[str, Any]], total: int = 0) -> list[str]:
    """' — Поиск Яндекса: 245 (45.2%)'"""
    lines: list[str] = []
    for it in items:
        name = localize_source(it.get("source") or "—")
        visits = int(it.get("visits") or 0)
        if total > 0:
            pct = 100.0 * visits / total
            lines.append(f"  — {name}: {fmt_int(visits)} ({fmt_percent(pct)})")
        else:
            lines.append(f"  — {name}: {fmt_int(visits)}")
    return lines


def summarize_search_phrases(items: list[dict[str, Any]], limit: int = 10) -> list[str]:
    """' — wpc панели: 12'"""
    lines: list[str] = []
    for i, it in enumerate(items[:limit], start=1):
        phrase = it.get("phrase") or "—"
        visits = fmt_int(it.get("visits") or 0)
        lines.append(f"{i}. {phrase} — {visits}")
    return lines
