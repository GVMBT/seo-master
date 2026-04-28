"""Bamboodom keyword collector (4Y, 2026-04-27).

Orchestration:
1. Generate seed phrases for material (5-10 per material) — uses static
   seed lists for now; AI seed-gen from ARTICLES_CATALOG can be added later.
2. Run DataForSEO keywords_for_seed for each seed (parallel via gather).
3. Filter (volume >= MIN_VOLUME, dedup phrases).
4. AI-cluster via clusterer.py.
5. Save batch via BamboodomKeywordsRepository.
"""

from __future__ import annotations


import httpx
import structlog

from bot.config import get_settings
from db.models import BamboodomKeywordCreate
from db.repositories import BamboodomKeywordsRepository
from services.bamboodom_keywords.clusterer import (
    cluster_keywords,
    label_to_cluster_id,
)
from services.external.dataforseo import DataForSEOClient

log = structlog.get_logger()

# Material-specific volume thresholds (5F, 2026-04-28). Profiles are a
# narrow B2B niche — Google Ads barely shows volume there, so threshold is
# lowered. Other materials keep 30 to filter long-tail noise.
_MIN_VOLUME_DEFAULT = 30
_MIN_VOLUME_BY_MATERIAL = {
    "wpc": 10,       # 5G: lowered from 30 — narrow Russian-term niche on Google Ads
    "flex": 30,
    "reiki": 30,
    "profiles": 5,
}
_MAX_PER_SEED = 80  # DataForSEO limit per call

# Seed phrases per material — bare-bones starter set.
# Phase 2 enhancement: derive from ARTICLES_CATALOG series + texture types.
_SEEDS_BY_MATERIAL: dict[str, list[str]] = {
    "wpc": [
        # 5U (2026-04-28): WPC = ТОЛЬКО стеновые панели для ИНТЕРЬЕРА.
        # Расширенный набор: разные помещения, стили, типы жилья, сценарии.
        # Цель — разнообразие тем статей, не только generic "wpc панели".

        # ── базовые / синонимы ──
        "wpc стеновые панели",
        "wpc панели для интерьера",
        "монтаж wpc стеновых панелей",
        "wpc или дпк для стен",
        "бамбуковые стеновые панели",
        "бамбуковые панели для интерьера",
        "декоративные бамбуковые панели",
        "панели из бамбука для стен",
        "дпк стеновые панели",
        "дпк панели для интерьера",
        "композитные панели для стен",

        # ── жилые помещения ──
        "стеновые панели в гостиную",
        "wpc панели в спальню",
        "стеновые панели для прихожей",
        "стеновые панели для коридора",
        "стеновые панели в кухню",
        "стеновые панели для ванной",
        "стеновые панели в санузел",
        "стеновые панели в детскую",
        "стеновые панели в кабинет",
        "стеновые панели в гардеробную",
        "стеновые панели в столовую",

        # ── общественные / коммерческие ──
        "стеновые панели для офиса",
        "wpc панели в переговорную",
        "стеновые панели в ресепшн",
        "wpc панели в ресторан",
        "стеновые панели для кафе",
        "стеновые панели в гостиницу",
        "стеновые панели в отель",
        "стеновые панели в шоурум",
        "стеновые панели в салон красоты",
        "стеновые панели в фитнес клуб",

        # ── стили интерьера ──
        "wpc панели лофт",
        "wpc панели скандинавский стиль",
        "wpc панели в стиле минимализм",
        "wpc панели хай тек",
        "wpc панели классика",
        "wpc панели японский стиль",
        "wpc панели эко стиль",
        "wpc панели современный интерьер",

        # ── тип жилья ──
        "wpc панели в новостройку",
        "wpc панели для вторички",
        "wpc панели для частного дома",
        "wpc панели в студию",
        "wpc панели в апартаменты",
        "wpc панели в таунхаус",

        # ── сценарии и проблемы ──
        "отделка стен за один день",
        "стеновые панели без обрешётки",
        "стеновые панели на неровные стены",
        "стеновые панели вместо плитки",
        "стеновые панели вместо обоев",
        "стеновые панели для арендной квартиры",
        "акустические стеновые панели",
        "влагостойкие стеновые панели",
        "стеновые панели скрыть проводку",
        "стеновые панели в проходной зоне",
    ],
    "flex": [
        "гибкая керамика",
        "гибкий камень",
        "гибкая плитка",
        "гибкий камень для фасада",
        "монтаж гибкого камня",
        "гибкий камень в интерьере",
    ],
    "reiki": [
        "реечные панели",
        "реечные панели на потолок",
        "реечные панели в спальне",
        "монтаж реечных панелей",
        "стеновые рейки",
        "реечная стена",
    ],
    "profiles": [
        "алюминиевые профили xhs",
        "монтажные профили wpc",
        "соединительный профиль панелей",
        "торцевой профиль для wpc",
        "L-профиль для стеновых панелей",
        "алюминиевый профиль декоративный",
        "профиль для стеновых панелей",
        "угловой профиль для панелей",
        "h профиль для панелей",
        "f профиль для панелей",
        "стартовый профиль для панелей",
        "финишный профиль декоративный",
        "плинтус для стеновых панелей",
        "отделочный профиль",
        "торцевая планка для wpc",
    ],
}


async def collect_for_material(
    material: str,
    repo: BamboodomKeywordsRepository,
    openrouter_api_key: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    progress_cb=None,
) -> dict[str, int]:
    """Run end-to-end collection for one material.

    Returns stats: {"fetched": N, "after_filter": N, "saved_new": N,
                    "saved_updated": N, "by_cluster": {label: count}}.

    progress_cb(stage_name: str) — optional callback so caller can update
    the user-facing progress message. Stages: "fetching", "clustering", "saving".
    """
    seeds = _SEEDS_BY_MATERIAL.get(material, [])
    if not seeds:
        raise ValueError(f"Unknown material: {material}")

    if progress_cb:
        await progress_cb("fetching")

    # 1) DataForSEO calls.
    # IMPORTANT (4Y, 2026-04-27): DataForSEO Yandex `keywords_data/yandex/*`
    # endpoints all return 40402 "Invalid Path" — Yandex keywords API is gone
    # from DataForSEO. Switched to Google Ads suggestions via DataForSEOClient
    # (services/external/dataforseo.py). location_code=2804 (Ukraine) because
    # Russia (2643) is banned for Google Ads keyword_suggestions endpoint.
    # Russian-language search trends overlap heavily between Yandex/Google.
    if http_client is None:
        # Fallback for callers that didn't pass an http client.
        own_http = True
        http_client = httpx.AsyncClient(timeout=60.0)
    else:
        own_http = False

    settings = get_settings()
    dfs_client = DataForSEOClient(
        login=settings.dataforseo_login,
        password=settings.dataforseo_password.get_secret_value(),
        http_client=http_client,
    )
    fetched: dict[str, tuple[int, float | None]] = {}
    try:
        for seed in seeds:
            try:
                results = await dfs_client.keyword_suggestions(seed=seed, limit=_MAX_PER_SEED)
            except Exception as exc:
                log.warning(
                    "bbk_collect_seed_failed",
                    seed=seed,
                    material=material,
                    error=str(exc)[:200],
                )
                continue
            for v in results:
                phrase = (v.phrase or "").strip().lower()
                if not phrase:
                    continue
                existing_vol = fetched.get(phrase, (0, None))[0]
                if v.volume > existing_vol:
                    fetched[phrase] = (v.volume, v.competition)
    finally:
        if own_http:
            await http_client.aclose()

    # 2) Filter
    min_vol = _MIN_VOLUME_BY_MATERIAL.get(material, _MIN_VOLUME_DEFAULT)
    filtered = {
        phrase: (vol, comp)
        for phrase, (vol, comp) in fetched.items()
        if vol >= min_vol
    }
    log.info(
        "bbk_collect_fetched",
        material=material,
        seeds=len(seeds),
        fetched=len(fetched),
        after_filter=len(filtered),
    )

    if not filtered:
        return {
            "fetched": len(fetched),
            "after_filter": 0,
            "saved_new": 0,
            "saved_updated": 0,
            "by_cluster": {},
        }

    # 3) AI-cluster
    if progress_cb:
        await progress_cb("clustering")
    phrases = list(filtered.keys())
    labels = await cluster_keywords(
        phrases,
        material=material,
        api_key=openrouter_api_key,
        http_client=http_client,
    )

    # 4) Build batch + save
    if progress_cb:
        await progress_cb("saving")
    items: list[BamboodomKeywordCreate] = []
    by_cluster: dict[str, int] = {}
    for phrase, (vol, comp) in filtered.items():
        lbl = labels.get(phrase, "общее")
        by_cluster[lbl] = by_cluster.get(lbl, 0) + 1
        items.append(
            BamboodomKeywordCreate(
                keyword=phrase,
                material=material,
                search_volume=vol,
                competition=comp,
                cluster_id=label_to_cluster_id(lbl),
                cluster_label=lbl,
                status="new",
            )
        )

    save_stats = await repo.save_batch(items)

    return {
        "fetched": len(fetched),
        "after_filter": len(filtered),
        "saved_new": save_stats["new"],
        "saved_updated": save_stats["updated"],
        "by_cluster": by_cluster,
    }
