"""Краулер новых страниц блога bamboodom.ru для Я.Вебмастера (v4E).

Источники URL'ов (по приоритету каноничности):

1. **`blog_list` API** — самый свежий, не зависит от регенерации sitemap.
   Сторона B вернула в 4E абсолютные `url` + пагинацию `offset/limit/total`.
2. **`sitemap_blog.xml`** — отдельный файл от стороны B (4E), регенерится
   автоматически при каждой production-публикации. Только статьи блога.

Зачем разделение на два канала:
- `blog_list` — единственный 100%-актуальный источник, отражает все
  опубликованные статьи в `data/blog.json` мгновенно.
- `sitemap_blog.xml` — резерв на случай когда `blog_list` недоступен
  (например, если api.php временно лежит). Также удобен для записи
  «канонической» истории в snapshot.

**Координация со стороной B**: их `auto_reindex_cron.php` шлёт в очередь
Я.Вебмастера URL'ы из общего `sitemap.xml` (товары + страницы сайта,
без блога). Наш бот шлёт ТОЛЬКО `/article.html?slug=*` (статьи блога).
Это разделение зон позволяет не дублировать дневную квоту (~200/сутки).

Snapshot ключ: `yandex_recrawl:bamboodom:blog_known_urls` (отдельный от
старого 4D `:known_urls` чтобы не пересекаться с историей до 4E).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import structlog

from bot.config import get_settings

log = structlog.get_logger()

DEFAULT_SITE = "https://bamboodom.ru"
DEFAULT_BLOG_SITEMAP = "https://bamboodom.ru/sitemap_blog.xml"
SNAPSHOT_REDIS_KEY = "yandex_recrawl:bamboodom:blog_known_urls"
SNAPSHOT_TTL = 60 * 60 * 24 * 90  # 90 дней; обновляется при каждом успехе

_DEFAULT_TIMEOUT = 20.0
_BLOG_LIST_LIMIT = 200  # за один вызов; при необходимости пагинируем
_BLOG_LIST_MAX_PAGES = 5  # 200 × 5 = 1000 статей max
_USER_AGENT = "BamboodomBot/1.0 (+https://bamboodom.ru) Yandex-recrawl-helper"

# Регекс для <loc>...</loc>
_RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_RE_SITEMAP_TAG = re.compile(r"<sitemap>(.*?)</sitemap>", re.IGNORECASE | re.DOTALL)

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
_DROP_QUERY_PREFIXES = ("utm_", "yclid", "gclid", "fbclid", "_openstat")
_DROP_QUERY_KEYS = {"sandbox", "preview", "draft"}


@dataclass
class CrawlResult:
    """Результат сканирования источников блога."""

    all_urls: list[str] = field(default_factory=list)
    new_urls: list[str] = field(default_factory=list)
    blog_list_count: int = 0
    sitemap_count: int = 0
    blog_list_failed: bool = False
    sitemap_failed: bool = False
    errors: list[str] = field(default_factory=list)
    total_in_blog: int | None = None  # `total` из ответа blog_list (если был)


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------


def _normalize_url(raw: str, base: str = DEFAULT_SITE) -> str | None:
    """Нормализация: абсолютный, без фрагмента, без мусорных query, lowercase host."""
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
    if netloc != base_netloc and not netloc.endswith("." + base_netloc):
        return None
    path = parsed.path or "/"
    if path.lower().endswith(_SKIP_SUFFIXES):
        return None
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
    if path != "/" and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path = path + "/"
    return urlunparse((parsed.scheme, netloc, path, "", new_query, ""))


def _is_blog_article(url: str) -> bool:
    """URL статьи блога: новый формат `/blog/<slug>` или старый `/article.html?slug=...`.

    4W layout v3 (2026-04-27): сторона B перешла на `/blog/<slug>` для
    production-статей. Старый `/article.html?slug=...` остаётся как
    rewrite-target для sandbox. Принимаем оба формата чтобы crawler
    видел и старые, и новые статьи во время переходного периода.

    Бот не должен слать в очередь Я.Вебмастера товары и общие страницы —
    их шлёт `auto_reindex_cron.php` стороны B.
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()
    # New canonical: /blog/<slug>
    if path.startswith("/blog/") and len(path) > len("/blog/"):
        return True
    # Legacy: /article.html?slug=...
    if path == "/article.html":
        return "slug=" in (parsed.query or "")
    return False


# ---------------------------------------------------------------------------
# Канал 1: blog_list API
# ---------------------------------------------------------------------------


async def _fetch_blog_list(
    client: httpx.AsyncClient,
    api_base: str,
    api_key: str,
) -> tuple[list[str], int | None, list[str]]:
    """Возвращает (urls, total_in_blog, errors). С пагинацией, до _BLOG_LIST_MAX_PAGES."""
    errors: list[str] = []
    urls: list[str] = []
    total: int | None = None
    offset = 0

    for _page in range(_BLOG_LIST_MAX_PAGES):
        try:
            resp = await client.get(
                api_base,
                params={
                    "action": "blog_list",
                    "offset": offset,
                    "limit": _BLOG_LIST_LIMIT,
                },
                headers={
                    "X-Blog-Key": api_key,
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                },
                timeout=_DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"blog_list offset={offset}: {exc}")
            return urls, total, errors

        if not isinstance(data, dict) or not data.get("ok"):
            errors.append(f"blog_list offset={offset}: ok=false")
            return urls, total, errors

        if total is None:
            try:
                total = int(data.get("total", 0))
            except (TypeError, ValueError):
                total = None

        items = data.get("items") or []
        if not isinstance(items, list) or not items:
            break

        for item in items:
            if not isinstance(item, dict):
                continue
            # Для recrawl шлём только опубликованные (не drafts)
            if item.get("draft"):
                continue
            raw_url = item.get("url") or ""
            norm = _normalize_url(str(raw_url))
            if norm and _is_blog_article(norm):
                urls.append(norm)

        if len(items) < _BLOG_LIST_LIMIT:
            break
        offset += _BLOG_LIST_LIMIT

    return urls, total, errors


# ---------------------------------------------------------------------------
# Канал 2: sitemap_blog.xml
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
    """Возвращает (urls, errors). Поддерживает sitemap-индексы."""
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
    nested = _RE_SITEMAP_TAG.findall(body)
    if nested:
        for chunk in nested:
            m = _RE_LOC.search(chunk)
            if m:
                sub_urls, sub_errs = await _crawl_sitemap(
                    client, m.group(1).strip(), base, seen_sitemaps=seen_sitemaps, depth=depth + 1
                )
                urls.extend(sub_urls)
                errors.extend(sub_errs)
        return urls, errors

    for m in _RE_LOC.finditer(body):
        norm = _normalize_url(m.group(1), base=base)
        if norm and _is_blog_article(norm):
            urls.append(norm)
    return urls, errors


# ---------------------------------------------------------------------------
# Snapshot
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
    """Запись нового snapshot. Должна вызываться ПОСЛЕ успешной отправки."""
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
    """Вернёт URL'ы, которых нет в snapshot. Стабильный порядок."""
    if not snapshot:
        return []  # первый запуск
    seen: set[str] = set()
    out: list[str] = []
    for u in all_urls:
        if u in snapshot or u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


async def crawl_bamboodom(
    redis: Any,
    *,
    site: str = DEFAULT_SITE,
    sitemap_url: str = DEFAULT_BLOG_SITEMAP,
) -> CrawlResult:
    """Главный entrypoint v4E. Использует blog_list + sitemap_blog.xml.

    Возвращает CrawlResult, не отправляет ничего в Я.Вебмастер.
    Snapshot не обновляется здесь — вызывайте save_snapshot после отправки.
    """
    settings = get_settings()
    api_base = settings.bamboodom_api_base
    api_key = settings.bamboodom_blog_key.get_secret_value()

    result = CrawlResult()
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
        # Канал 1: blog_list
        if api_key and api_base:
            bl_urls, total, bl_errs = await _fetch_blog_list(client, api_base, api_key)
            if bl_errs:
                result.errors.extend(bl_errs)
                result.blog_list_failed = True
            result.blog_list_count = len(bl_urls)
            if total is not None:
                result.total_in_blog = total
        else:
            bl_urls = []
            result.blog_list_failed = True
            result.errors.append("blog_list: BAMBOODOM_BLOG_KEY/API_BASE не настроены")

        # Канал 2: sitemap_blog.xml
        sm_urls, sm_errs = await _crawl_sitemap(client, sitemap_url, site)
        if sm_errs:
            result.errors.extend(sm_errs)
            result.sitemap_failed = True
        result.sitemap_count = len(sm_urls)

    # Дедуп с приоритетом blog_list (он каноничнее)
    seen: set[str] = set()
    merged: list[str] = []
    for u in bl_urls + sm_urls:
        if u and u not in seen:
            seen.add(u)
            merged.append(u)
    result.all_urls = merged

    snapshot = await _read_snapshot(redis)
    result.new_urls = diff_against_snapshot(merged, snapshot)
    return result


async def snapshot_exists(redis: Any) -> bool:
    """Helper для UI: есть ли уже snapshot, чтобы понять «первый запуск или нет»."""
    if redis is None:
        return False
    try:
        val = await redis.get(SNAPSHOT_REDIS_KEY)
    except Exception:
        return False
    return bool(val)
