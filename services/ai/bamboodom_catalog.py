"""Bamboodom rich-catalog client (Session 4B.1.8 + v11 compact-aux mode).

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

v11 (2026-04-25, after smoke-test 1+2 of v10): compact-aux render mode. The
v10 prompt with all 555 articles fully described pushed input to ~65k tokens;
Sonnet 4.5 then "tired out" on the long context and consistently produced
1100-1200 word articles instead of the 1500-2200 target. v11 keeps the primary
material category fully rich (descriptions, series, texture_type) but renders
non-primary categories as bare code lists with a one-line metadata hint
(texture types for wpc, thickness range for flex, profile families for
profiles). Drop is ~50-65% in prompt size, primary attention budget restored.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

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
    compact_aux: bool = True,
    shuffle_seed: str | None = None,
) -> str:
    """Render the catalog as a structured markdown block for AI consumption.

    Layout: primary_material first ("Основная категория"), the rest alphabetical
    ("Сопутствующие"). Within each category, items are grouped by series/texture
    where that helps; otherwise sorted by code.

    `max_items_per_category` is a safety knob — None = unlimited.

    v11 default `compact_aux=True`: non-primary categories rendered as bare
    code lists (12/line) with a one-line metadata hint. Saves ~50-65% prompt
    size vs full rendering. AI cites aux articles by code in product-blocks
    (validator allowlist still covers all categories), and writes aux mentions
    in prose generically ("XHS-профили для стыков") rather than fabricating
    pseudo-specific phrases from a flood of descriptions.

    Pass `compact_aux=False` to restore v10-style full rendering for all
    categories — useful for debugging or for comparison-articles where AI
    really needs full data on both sides.
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

    # v14.1 (2026-04-27): shuffle items per category with deterministic seed
    # derived from the article topic. Each topic gets a different rotation,
    # so AI sees a different "first batch" of candidates and breaks out of
    # the TK001A/TK029P/TK070C rut. Same topic re-generated → same order
    # (deterministic, useful for retry-loop stability).
    import hashlib
    import random as _random

    rng: _random.Random | None = None
    if shuffle_seed:
        seed_int = int(hashlib.sha256(shuffle_seed.encode("utf-8")).hexdigest()[:16], 16)
        rng = _random.Random(seed_int)  # noqa: S311 — non-crypto shuffle is fine

    out_blocks: list[str] = []
    for cat in order:
        items = list(grouped[cat])  # mutable copy so shuffle doesn't touch source
        if rng is not None:
            rng.shuffle(items)
        if max_items_per_category is not None and len(items) > max_items_per_category:
            items = items[:max_items_per_category]
        is_primary = cat == primary_material
        rendered = _render_category_block(cat, items, primary=is_primary, compact=(compact_aux and not is_primary))
        if rendered:
            out_blocks.append(rendered)

    return "\n\n".join(out_blocks)


def _render_category_block(category: str, items: list[CatalogItem], *, primary: bool, compact: bool = False) -> str:
    if not items:
        return ""
    label = "Основная" if primary else "Сопутствующая"
    header = f"### {label} категория: {category} (всего {len(items)} артикулов)"

    if compact:
        body = _render_compact(category, items)
        return f"{header}\n{body}"

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


# ---------- compact aux renderer (v11) ----------


_COMPACT_CODES_PER_LINE = 12


def _render_compact(category: str, items: list[CatalogItem]) -> str:
    """Bare code list + one-line metadata hint. Used for non-primary categories.

    Output is ~5-10% the size of the rich render. AI can still pick a code
    for product-blocks (validator allowlist covers all 1021 codes), and the
    hint keeps prose mentions grounded ("гибкая керамика — толщины 2-17 мм,
    серия Travertine для стен", not "серия XYZ-Plus которой не существует").
    """
    sorted_codes = sorted(it.code for it in items if it.code)
    chunks = [
        ", ".join(sorted_codes[i : i + _COMPACT_CODES_PER_LINE])
        for i in range(0, len(sorted_codes), _COMPACT_CODES_PER_LINE)
    ]
    hint = _compact_hint_for_category(category, items)
    body_lines: list[str] = []
    if hint:
        body_lines.append(f"  _{hint}_")
    body_lines.append("  " + "\n  ".join(chunks))
    return "\n".join(body_lines)


def _compact_hint_for_category(category: str, items: list[CatalogItem]) -> str:
    """Short metadata summary so aux mentions in prose stay grounded."""
    if category == "wpc":
        textures = sorted({str(it.extra.get("texture_type") or "") for it in items if it.extra.get("texture_type")})
        textures = [t for t in textures if t]
        series = sorted({str(it.extra.get("series") or "") for it in items if it.extra.get("series")})
        series = [s for s in series if s]
        bits: list[str] = []
        if series:
            bits.append(f"серии: {', '.join(series)}")
        if textures:
            bits.append(f"текстуры: {', '.join(textures)}")
        return "; ".join(bits)
    if category == "flex":
        thicks = sorted(
            {int(it.extra["thick_mm"]) for it in items if isinstance(it.extra.get("thick_mm"), (int, float))}
        )
        return f"толщины: {min(thicks)}-{max(thicks)} мм" if thicks else ""
    if category == "reiki":
        widths = sorted(
            {
                int(round(float(it.extra["width_mm"])))
                for it in items
                if isinstance(it.extra.get("width_mm"), (int, float))
            }
        )
        return f"ширина: {min(widths)}-{max(widths)} мм" if widths else ""
    if category == "profiles":
        cats = sorted({str(it.extra.get("category_name") or "") for it in items if it.extra.get("category_name")})
        cats = [c for c in cats if c]
        return f"типы: {', '.join(cats)}" if cats else ""
    return ""


# ---------- per-category rich renderers (used for primary) ----------


def _render_wpc(items: list[CatalogItem]) -> str:
    """WPC — group by series, then by texture_type. Show name if non-default."""
    by_series: dict[str, list[CatalogItem]] = {}
    for it in items:
        series = str(it.extra.get("series") or "?")
        by_series.setdefault(series, []).append(it)

    chunks: list[str] = []
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
    """Flex — code, name, толщина, размер, цена."""
    items = sorted(items, key=lambda x: x.code)
    lines: list[str] = []
    for it in items:
        thick = it.extra.get("thick_mm")
        sizes = it.extra.get("sizes") or []
        first_size = ""
        if isinstance(sizes, list) and sizes and isinstance(sizes[0], list) and len(sizes[0]) == 2:
            first_size = f"{sizes[0][0]}x{sizes[0][1]}мм"
        thick_part = f", {thick}мм" if thick else ""
        size_part = f", {first_size}" if first_size else ""
        price = it.extra.get("price_yuan")
        price_part = f", {price}Y/м2" if price else ""
        new_part = " [NEW]" if it.extra.get("is_new") else ""
        desc_part = f" / {it.description}" if it.description else ""
        lines.append(f"  {it.code} — {it.name}{thick_part}{size_part}{price_part}{new_part}{desc_part}")
    return "\n".join(lines)


def _render_reiki(items: list[CatalogItem]) -> str:
    """Reiki — code, name, ширина, длина, цена."""
    items = sorted(items, key=lambda x: x.code)
    lines: list[str] = []
    for it in items:
        width = it.extra.get("width_mm")
        length = it.extra.get("length_mm")
        width_part = f", ширина ~{round(float(width))}мм" if isinstance(width, (int, float)) else ""
        length_part = f", длина {length}мм" if isinstance(length, (int, float)) else ""
        price = it.extra.get("price_yuan")
        price_part = f", {round(float(price), 1)}Y" if isinstance(price, (int, float)) else ""
        desc_part = f" / {it.description}" if it.description else ""
        lines.append(f"  {it.code} — {it.name}{width_part}{length_part}{price_part}{desc_part}")
    return "\n".join(lines)


def _render_profiles(items: list[CatalogItem]) -> str:
    """Profiles — group by category_name."""
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
            price_part = f" ({price}Y)" if price else ""
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
    that AI somehow surfaced than reject it as bad_article and force a retry.

    v12 (2026-04-25): for codes containing whitespace (e.g. XHS-QBDD901 with
    its description), we ALSO add the prefix-up-to-first-whitespace as an
    alias. Side B confirmed ProductCard accepts either form, so AI writing
    the bare prefix should not trip the validator.
    """
    out: set[str] = set()
    for it in payload.items:
        code = it.code
        if not code:
            continue
        out.add(code)
        prefix = code.split(None, 1)[0]
        if prefix and prefix != code:
            out.add(prefix)
    return frozenset(out)
