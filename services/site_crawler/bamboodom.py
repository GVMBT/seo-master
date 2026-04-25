"""Краулер новых страниц bamboodom.ru для отправки в Яндекс Вебмастер.

Стратегия (полностью автономно, без сторонних библиотек):

1. Загружаем `https://bamboodom.ru/sitemap.xml` (а также любые вложенные
   sitemap-индексы, если они есть).
2. Извлекаем все `<loc>...</loc>`.
3. Фильтруем URL'ы по домену (`bamboodom.ru`), удаляем фрагменты и параметры
   `sandbox=`/`utm_*`, нормализуем хвост слэша.
4. Дополнительно (опционально) обходим главную и статические разделы на 1
   уровень в глубину, чтобы поймать страницы, не попавшие в sitemap.xml
   (на bamboodom бывает: сайт регенерирует sitemap раз в сутки).
5. Сравниваем с предыдущим snapshot'ом из Redis (`yandex_recrawl:bamboodom:known_urls`).
6. Возвращаем CrawlResult с total/new/all URL'ами.

Snapshot обновляется ОТДЕЛЬНЫМ вызовом `save_snapshot()` уже после успешной
отправки в Я.Вебмастер — иначе если что-то упадёт между этапами, на следующем
запуске мы потеряем «новые» URL'ы навсегда.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import structlog

log = structlog.get_logger()

DEFAULT_SITE = "https://bamboodom.ru"
DEFAULT_SITEMAP = "https://bamboodom.ru/sitemap.xml"
SNAPSHOT_REDIS_KEY = "yandex_recrawl:bamboodom:known_urls"
SNAPSHOT_TTL = 60 * 60 * 24 * 90  # 90 дней — снапшот всегда обновляется при успехе

_DEFAULT_TIMEOUT = 20.0
_MAX_PAGES_HTML = 60  # cap на HTML-обход — без жадности
_USER_AGENT = "BamboodomBot/1.0 (+https://bamboodom.ru) Yandex-recrawl-helper"

# Регекс для <loc>...</loc> и <a href="...">
_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_RE_HREF = re.compile(r'href\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
_RE_SITEMAP_TAG = re.compile(r"<sitemap>(.*?)</sitemap>", re.IGNORECASE | re.DOTALL)

# Хвосты, которые точно не нужно слать на переобход
_SKIP_SUFFIXES = (
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".svg",
    ".ico",
    ".pdf",
    ".zip",
    ".rar",
    ".mp4",
    ".mp3",
    ".css",
    ".js",
    ".xml",
)
# Параметры, которые удаляем при нормализации
_DROP_QUERY_PREFIXES = ("utm_", "yclid", "gclid", "fbclid", "_openstat")
_DROP_QUERY_KEYS = {"sandbox", "preview", "draft"}


@dataclass
class CrawlResult:
    """Результат обхода сайта."""

    all_urls: list[str] = field(default_factory=list)  # все найденные на сайте
    new_urls: list[str] = field(default_factory=list)  # которых нет в snapshot
    sitemap_count: int = 0
    html_count: int = 0
    sitemap_failed: bool = False
    html_failed: bool = False
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def _normalize_url(raw: str, base: str = DEFAULT_SITE) -> str | None:
    """Нормализация: абсолютный, без фрагмента, без мусорных query, нижний регистр домена.

    Возвращает None если URL отбракован (другой домен, файл, и т.д.).
    """
    if not raw:
        return None
    raw = raw.strip()
    if raw.startswith(("javascript:", "mailto:", "tel:", "#")):
        return None
    abs_url = urljoin(base, raw)
    parsed = urlparse(abs_url)
    if parsed.scheme not in ("http", "https"):
        return None
    netloc = parsed.netloc.lower()
    base_netloc = urlparse(base).netloc.lower()
    if not netloc:
        return None
    # Сравнение «основного» домена: bamboodom.ru должен совпадать или быть суффиксом
    if netloc != base_netloc and not netloc.endswith("." + base_netloc):
        return None
    path = parsed.path or "/"
    # Файлы — не наш кейс
    if path.lower().endswith(_SKIP_SUFFIXES):
        return None
    # Чистим query
    if parsed.query:
        kept = []
        for chunk in parsed.query.split("&"):
            if not chunk:
                continue
            key = chunk.split("=", 1)[0].lower()
            if key in _DROP_QUERY_KEYS:
                continue
            if any(key.startswith(pref) for pref in _DROP_QUERY_PREFIXES):
                continue
            kept.append(chunk)
        new_query = "&".join(kept)
    else:
        new_query = ""
    # Нормализуем хвостовой слэш для путей без расширения
    if path != "/" and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path = path + "/"
    return urlunparse((parsed.scheme, netloc, path, "", new_query, ""))


# ---------------------------------------------------------------------------
# Sitemap fetcher
# ---------------------------------------------------------------------------


async def _fetch_text(client: httpx.AsyncClient, url: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
    resp = await client.get(url, timeout=timeout, headers={"User-Agent": _USER_AGENT})
    resp.raise_for_status()
    return resp.text


async def _crawl_sitemap(
    client: httpx.AsyncClient,
    sitemap_url: str,
    base: str,
    *,
    seen_sitemaps: set[str] | None = None,
    depth: int = 0,
) -> tuple[list[str], list[str]]:
    """Возвращает (urls, errors). Поддерживает sitemap-индекс с вложенными sitemap'ами."""
    if seen_sitemaps is None:
        seen_sitemaps = set()
    if depth > 3 or sitemap_url in seen_sitemaps:
        return [], []
    seen_sitemaps.add(sitemap_url)
    errors: list[str] = []
    try:
        body = await _fetch_text(client, sitemap_url)
    except httpx.HTTPError as exc:
        errors.append(f"sitemap fetch {sitemap_url}: {exc}")
        return [], errors

    urls: list[str] = []
    # Сначала пробуем индекс — если есть <sitemap><loc>...
    nested = _RE_SITEMAP_TAG.findall(body)
    if nested:
        nested_urls = []
        for chunk in nested:
            m = _RE_LOC.search(chunk)
            if m:
                nested_urls.append(m.group(1).strip())
        for nu in nested_urls:
            sub_urls, sub_errs = await _crawl_sitemap(client, nu, base, seen_sitemaps=seen_sitemaps, depth=depth + 1)
            urls.extend(sub_urls)
            errors.extend(sub_errs)
        return urls, errors

    # Обычный sitemap — простые <loc>
    for m in _RE_LOC.finditer(body):
        norm = _normalize_url(m.group(1), base=base)
        if norm:
            urls.append(norm)
    return urls, errors


# ---------------------------------------------------------------------------
# Optional HTML crawler — depth=1 от главной
# ---------------------------------------------------------------------------


async def _crawl_html(
    client: httpx.AsyncClient,
    site: str,
    *,
    max_pages: int = _MAX_PAGES_HTML,
) -> tuple[list[str], list[str]]:
    """Грубый обход HTML на глубину 1: тянем главную, парсим href, собираем уникальные."""
    errors: list[str] = []
    discovered: list[str] = []
    seen: set[str] = set()
    try:
        body = await _fetch_text(client, site)
    except httpx.HTTPError as exc:
        errors.append(f"html fetch {site}: {exc}")
        return discovered, errors
    # Сама главная уходит в discovered первой
    home = _normalize_url(site)
    if home:
        discovered.append(home)
        seen.add(home)
    for m in _RE_HREF.finditer(body):
        if len(discovered) >= max_pages:
            break
        norm = _normalize_url(m.group(1), base=site)
        if norm and norm not in seen:
            discovered.append(norm)
            seen.add(norm)
    return discovered, errors


# ---------------------------------------------------------------------------
# Snapshot in Redis
# ---------------------------------------------------------------------------


async def _read_snapshot(redis: Any) -> set[str]:
    if redis is None:
        return set()
    try:
        raw = await redis.get(SNAPSHOT_REDIS_KEY)
    except Exception:
        log.warning("yw_snapshot_read_failed", exc_info=True)
        return set()
    if not raw:
        return set()
    try:
        data = json.loads(raw)
    except ValueError:
        return set()
    if not isinstance(data, list):
        return set()
    return {str(u) for u in data}


async def save_snapshot(redis: Any, urls: list[str]) -> None:
    """Записать новый snapshot. Должно вызываться ПОСЛЕ успешной отправки."""
    if redis is None:
        return
    try:
        await redis.set(
            SNAPSHOT_REDIS_KEY,
            json.dumps(sorted(set(urls)), ensure_ascii=False),
            ex=SNAPSHOT_TTL,
        )
    except Exception:
        log.warning("yw_snapshot_write_failed", exc_info=True)


def diff_against_snapshot(all_urls: list[str], snapshot: set[str]) -> list[str]:
    """Вернёт URL'ы, которых нет в snapshot. Стабильный порядок (как в all_urls)."""
    if not snapshot:
        # Первый запуск — ничего не считаем «новым», иначе зальём в очередь весь сайт
        return []
    seen = set()
    out: list[str] = []
    for u in all_urls:
        if u in snapshot or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def crawl_bamboodom(
    redis: Any,
    *,
    site: str = DEFAULT_SITE,
    sitemap_url: str = DEFAULT_SITEMAP,
    use_html: bool = True,
) -> CrawlResult:
    """Главный entrypoint.

    redis — RedisClient или None. Без Redis всё равно отработает, но diff будет пустым.
    """
    result = CrawlResult()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
        sm_urls, sm_errs = await _crawl_sitemap(client, sitemap_url, site)
        if sm_errs:
            result.errors.extend(sm_errs)
            result.sitemap_failed = True
        result.sitemap_count = len(sm_urls)

        html_urls: list[str] = []
        if use_html:
            html_urls, html_errs = await _crawl_html(client, site)
            if html_errs:
                result.errors.extend(html_errs)
                result.html_failed = True
            result.html_count = len(html_urls)

    # Дедуп с сохранением порядка (sitemap впереди — он каноничнее)
    seen: set[str] = set()
    merged: list[str] = []
    for u in sm_urls + html_urls:
        if u and u not in seen:
            seen.add(u)
            merged.append(u)
    result.all_urls = merged

    snapshot = await _read_snapshot(redis)
    result.new_urls = diff_against_snapshot(merged, snapshot)
    return result
