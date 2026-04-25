"""Bamboodom rich-catalog client (Session 4B.1.8).

Wraps `GET /api.php?action=blog_article_index_full` — endpoint shipped by side B
on 2026-04-25 specifically to give us a full description-bearing catalog so AI
stops extrapolating intermediate article codes and writes meaningful product
mentions tied to series/texture_type/name.

Why a separate module (not in `integrations/bamboodom/`):
- Keeps `integrations/bamboodom/` (restricted zone, Session 1A) untouched.
- Module-level cache is enough — the bot runs as a single Railway dyno, and
  side B asked for a 1-hour refresh cadence. No Redis needed for this surface.
- Self-contained httpx GET; no dependence on `BamboodomClient._request` private
  internals or its caching layout.

Lighting category (466 ERDU items) is fetched and cached but **filtered out**
of the prompt-facing payload. We are not writing articles about lighting yet
(per Alex, 2026-04-25). When we do, drop the `_PROMPT_CATEGORIES` filter.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx
import structlog

from bot.config import get_settings

log = structlog.get_logger()

_ENDPOINT_ACTION = "blog_article_index_full"
_DEFAULT_TIMEOUT = 30.0  # ~1 MB JSON; generous timeout for first cold fetch
_CACHE_TTL = 3600.0  # 1 hour, per side B directive

# Categories shown to AI in the prompt. `lighting` is fetched and cached but
# excluded here — Alex confirmed (2026-04-25) we are not writing articles about
# ERDU lighting yet, and the 466 items would just bloat the prompt by ~50 KB.
_PROMPT_CATEGORIES: tuple[str, ...] = ("wpc", "flex", "reiki", "profiles")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CatalogItem:
    """One article record — preserves all category-specific extras as `extra`."""

    code: str
    category: str  # wpc | flex | reiki | profiles | lighting
    name: str
    url: str
    cover_img: str
    description: str
    suitable_for: list[str]
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, raw: dict[str, Any]) -> CatalogItem:
        """Coerce one server item dict into a CatalogItem.

        Unknown / new fields are stored verbatim in `extra` so we forward-comp
        with whatever side B adds later (a new `tags` or `swatch_color` field
        will not crash us).
        """
        known = {"code", "category", "name", "url", "cover_img", "description", "suitable_for"}
        extras = {k: v for k, v in raw.items() if k not in known}
        return cls(
            code=str(raw.get("code", "")).strip(),
            category=str(raw.get("category", "")).strip(),
            name=str(raw.get("name", "")).strip(),
            url=str(raw.get("url", "")).strip(),
            cover_img=str(raw.get("cover_img", "")).strip(),
            description=str(raw.get("description", "")).strip(),
            suitable_for=[str(s) for s in (raw.get("suitable_for") or []) if isinstance(s, (str, int))],
            extra=extras,
        )


@dataclass(slots=True)
class CatalogPayload:
    """Full server response, parsed into our shapes."""

    version: str
    cache_key: str
    total: int
    by_category: dict[str, int]
    items: list[CatalogItem]
    updated_at: str | None = None
    fetched_at: str | None = None

    def items_for_prompt(self) -> list[CatalogItem]:
        """Items AI sees in the prompt (lighting filtered out per 4B.1.8 scope)."""
        return [it for it in self.items if it.category in _PROMPT_CATEGORIES]

    def items_by_category(self, *, prompt_only: bool = True) -> dict[str, list[CatalogItem]]:
        pool: Iterable[CatalogItem] = self.items_for_prompt() if prompt_only else self.items
        out: dict[str, list[CatalogItem]] = {}
        for it in pool:
            out.setdefault(it.category, []).append(it)
        return out


# ---------------------------------------------------------------------------
# Cache (module-level — single-process bot, fine to keep in memory)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _CacheSlot:
    payload: CatalogPayload
    fetched_at_ts: float


_cache: dict[str, _CacheSlot] = {}
_cache_lock = asyncio.Lock()


def _cache_key(category: str | None, has_description: bool) -> str:
    cat = category or "_all"
    flag = "1" if has_description else "0"
    return f"{cat}:hd={flag}"


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------


class CatalogFetchError(Exception):
    """Raised when we can't load the catalog and have no usable cache."""


async def _http_fetch(
    *,
    api_base: str,
    api_key: str,
    category: str | None,
    has_description: bool,
    http_client: httpx.AsyncClient | None,
    timeout: float,
) -> dict[str, Any]:
    params: dict[str, Any] = {"action": _ENDPOINT_ACTION}
    if category:
        params["category"] = category
    if has_description:
        params["has_description"] = "1"

    headers = {
        "X-Blog-Key": api_key,
        "Accept": "application/json",
    }

    async def _do(client: httpx.AsyncClient) -> httpx.Response:
        return await client.get(api_base, params=params, headers=headers, timeout=timeout)

    try:
        if http_client is not None:
            resp = await _do(http_client)
        else:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await _do(client)
    except httpx.TimeoutException as exc:
        raise CatalogFetchError(f"timeout fetching catalog: {exc}") from exc
    except httpx.RequestError as exc:
        raise CatalogFetchError(f"network error fetching catalog: {exc}") from exc

    if resp.status_code >= 400:
        raise CatalogFetchError(f"HTTP {resp.status_code} on catalog: {resp.text[:300]}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise CatalogFetchError(f"non-JSON catalog response: {resp.text[:300]}") from exc
    if not isinstance(data, dict) or not data.get("ok"):
        raise CatalogFetchError(f"unexpected catalog shape: {str(data)[:300]}")
    return data


def _parse_payload(raw: dict[str, Any]) -> CatalogPayload:
    items_raw = raw.get("items") or []
    if not isinstance(items_raw, list):
        raise CatalogFetchError(f"items is {type(items_raw).__name__}, expected list")

    items = [CatalogItem.from_payload(it) for it in items_raw if isinstance(it, dict)]
    by_cat = raw.get("by_category") or {}
    if not isinstance(by_cat, dict):
        by_cat = {}

    return CatalogPayload(
        version=str(raw.get("version", "")),
        cache_key=str(raw.get("cache_key", "")),
        total=int(raw.get("total", len(items))),
        by_category={str(k): int(v) for k, v in by_cat.items() if isinstance(v, (int, float))},
        items=items,
        updated_at=raw.get("updated_at"),
        fetched_at=raw.get("fetched_at"),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_catalog(
    *,
    category: str | None = None,
    has_description: bool = False,
    force_refresh: bool = False,
    http_client: httpx.AsyncClient | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> tuple[CatalogPayload, bool]:
    """Get the full bamboodom article catalog. Returns (payload, was_cache_hit).

    Cache: module-level dict keyed by `(category, has_description)`. TTL 1 hour
    (server refreshes hourly; our cadence matches). On fetch failure, returns
    stale cache if available; only raises CatalogFetchError on cold-start
    network errors.
    """
    settings = get_settings()
    base = api_base or settings.bamboodom_api_base
    key = api_key or settings.bamboodom_blog_key.get_secret_value()
    slot_key = _cache_key(category, has_description)

    if not force_refresh:
        slot = _cache.get(slot_key)
        if slot is not None and (time.monotonic() - slot.fetched_at_ts) < _CACHE_TTL:
            log.debug(
                "bamboodom_catalog_cache_hit",
                slot=slot_key,
                age_s=round(time.monotonic() - slot.fetched_at_ts, 1),
                cache_key=slot.payload.cache_key,
                items=len(slot.payload.items),
            )
            return slot.payload, True

    async with _cache_lock:
        # Re-check after acquiring lock — another coroutine may have refreshed.
        if not force_refresh:
            slot = _cache.get(slot_key)
            if slot is not None and (time.monotonic() - slot.fetched_at_ts) < _CACHE_TTL:
                return slot.payload, True

        try:
            raw = await _http_fetch(
                api_base=base,
                api_key=key,
                category=category,
                has_description=has_description,
                http_client=http_client,
                timeout=timeout,
            )
            payload = _parse_payload(raw)
            _cache[slot_key] = _CacheSlot(payload=payload, fetched_at_ts=time.monotonic())
            log.info(
                "bamboodom_catalog_refreshed",
                slot=slot_key,
                cache_key=payload.cache_key,
                total=payload.total,
                items_loaded=len(payload.items),
                by_category=payload.by_category,
            )
            return payload, False
        except CatalogFetchError as exc:
            # Fall back to stale cache if we have any — better stale than dead.
            stale = _cache.get(slot_key)
            if stale is not None:
                log.warning(
                    "bamboodom_catalog_fetch_failed_using_stale",
                    slot=slot_key,
                    age_s=round(time.monotonic() - stale.fetched_at_ts, 1),
                    error=str(exc),
                )
                return stale.payload, True
            raise


# ---------------------------------------------------------------------------
# Prompt formatting — turns CatalogPayload into the markdown chunk the prompt
# template injects via <<articles_catalog>>.
# ---------------------------------------------------------------------------


def format_catalog_for_prompt(
    payload: CatalogPayload,
    *,
    primary_material: str,
    max_items_per_category: int | None = None,
) -> str:
    """Render the catalog as a structured markdown block for AI consumption.

    Layout: primary_material first ("Основная категория"), the rest alphabetical
    ("Сопутствующие"). Within each category, items are grouped by series/texture
    where that helps; otherwise sorted by code. Each line is short and machine-
    parseable so AI can scan visually without needing prose.

    `max_items_per_category` is a safety knob — None = unlimited. Set to e.g.
    300 if a future deploy explodes the catalog past Sonnet's context budget.
    """
    grouped = payload.items_by_category(prompt_only=True)
    if not grouped:
        return "(каталог временно недоступен)"

    order: list[str] = []
    if primary_material in grouped:
        order.append(primary_material)
    for cat in _PROMPT_CATEGORIES:
        if cat != primary_material and cat in grouped:
            order.append(cat)

    out_blocks: list[str] = []
    for cat in order:
        items = grouped[cat]
        if max_items_per_category is not None and len(items) > max_items_per_category:
            items = items[:max_items_per_category]
        rendered = _render_category_block(cat, items, primary=(cat == primary_material))
        if rendered:
            out_blocks.append(rendered)

    return "\n\n".join(out_blocks)


def _render_category_block(category: str, items: list[CatalogItem], *, primary: bool) -> str:
    if not items:
        return ""
    label = "Основная" if primary else "Сопутствующая"
    header = f"### {label} категория: {category} (всего {len(items)} артикулов)"

    if category == "wpc":
        body = _render_wpc(items)
    elif category == "flex":
        body = _render_flex(items)
    elif category == "reiki":
        body = _render_reiki(items)
    elif category == "profiles":
        body = _render_profiles(items)
    else:  # pragma: no cover — lighting filtered upstream
        body = _render_generic(items)

    return f"{header}\n{body}"


# ---------- per-category renderers ----------


def _render_wpc(items: list[CatalogItem]) -> str:
    """WPC — group by series, then by texture_type. Show name if non-default."""
    by_series: dict[str, list[CatalogItem]] = {}
    for it in items:
        series = str(it.extra.get("series") or "?")
        by_series.setdefault(series, []).append(it)

    chunks: list[str] = []
    # Stable series order: P, A, B, C, D, M, S, Y, G, BJL, BJ, then alphabetical rest.
    preferred = ["P", "A", "B", "C", "D", "M", "S", "Y", "G", "BJL", "BJ"]
    series_keys = [s for s in preferred if s in by_series]
    series_keys.extend(sorted(s for s in by_series if s not in preferred))

    for series in series_keys:
        block_items = sorted(by_series[series], key=lambda x: x.code)
        lines = [f"  Серия {series}:"]
        for it in block_items:
            tex = str(it.extra.get("texture_type") or "")
            tex_part = f" [{tex}]" if tex else ""
            name_part = ""
            if it.name and it.name != it.code:
                name_part = f" — {it.name}"
            desc_part = f" / {it.description}" if it.description else ""
            lines.append(f"    {it.code}{tex_part}{name_part}{desc_part}")
        chunks.append("\n".join(lines))
    return "\n".join(chunks)


def _render_flex(items: list[CatalogItem]) -> str:
    """Flex — code, name, толщина, размер (берём первый из sizes), цена в юанях."""
    items = sorted(items, key=lambda x: x.code)
    lines: list[str] = []
    for it in items:
        thick = it.extra.get("thick_mm")
        sizes = it.extra.get("sizes") or []
        first_size = ""
        if isinstance(sizes, list) and sizes and isinstance(sizes[0], list) and len(sizes[0]) == 2:
            first_size = f"{sizes[0][0]}×{sizes[0][1]}мм"
        thick_part = f", {thick}мм" if thick else ""
        size_part = f", {first_size}" if first_size else ""
        price = it.extra.get("price_yuan")
        price_part = f", {price}¥/м²" if price else ""
        new_part = " [NEW]" if it.extra.get("is_new") else ""
        desc_part = f" / {it.description}" if it.description else ""
        lines.append(f"  {it.code} — {it.name}{thick_part}{size_part}{price_part}{new_part}{desc_part}")
    return "\n".join(lines)


def _render_reiki(items: list[CatalogItem]) -> str:
    """Reiki — code, name, ширина (главное для подбора), длина, цена."""
    items = sorted(items, key=lambda x: x.code)
    lines: list[str] = []
    for it in items:
        width = it.extra.get("width_mm")
        length = it.extra.get("length_mm")
        width_part = f", ширина ~{round(float(width))}мм" if isinstance(width, (int, float)) else ""
        length_part = f", длина {length}мм" if isinstance(length, (int, float)) else ""
        price = it.extra.get("price_yuan")
        price_part = f", {round(float(price), 1)}¥" if isinstance(price, (int, float)) else ""
        desc_part = f" / {it.description}" if it.description else ""
        lines.append(f"  {it.code} — {it.name}{width_part}{length_part}{price_part}{desc_part}")
    return "\n".join(lines)


def _render_profiles(items: list[CatalogItem]) -> str:
    """Profiles — group by category_name (Т-профиль, U-профиль и т.д.)."""
    by_cat: dict[str, list[CatalogItem]] = {}
    for it in items:
        cat_name = str(it.extra.get("category_name") or "Прочее")
        by_cat.setdefault(cat_name, []).append(it)

    chunks: list[str] = []
    for cat_name in sorted(by_cat.keys()):
        sorted_items = sorted(by_cat[cat_name], key=lambda x: x.code)
        lines = [f"  {cat_name}:"]
        for it in sorted_items:
            size = str(it.extra.get("size") or "")
            size_part = f" {size}" if size else ""
            price = it.extra.get("price_yuan")
            price_part = f" ({price}¥)" if price else ""
            desc_part = f" / {it.description}" if it.description else ""
            lines.append(f"    {it.code}{size_part}{price_part}{desc_part}")
        chunks.append("\n".join(lines))
    return "\n".join(chunks)


def _render_generic(items: list[CatalogItem]) -> str:
    """Fallback (used only if a new category appears)."""
    items = sorted(items, key=lambda x: x.code)
    lines = [f"  {it.code} — {it.name}" + (f" / {it.description}" if it.description else "") for it in items]
    return "\n".join(lines)


def collect_codes_for_validator(payload: CatalogPayload) -> frozenset[str]:
    """Build a code-set for the regex validator.

    Includes ALL categories — including lighting — because the validator scans
    AI prose for any article-like token, and we'd rather accept a lighting code
    that AI somehow surfaced than reject it as `bad_article` and force a retry.
    """
    return frozenset(it.code for it in payload.items if it.code)
