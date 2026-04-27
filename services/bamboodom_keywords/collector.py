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

from db.models import BamboodomKeywordCreate
from db.repositories import BamboodomKeywordsRepository
from integrations.dataforseo_yandex import DataForSEOYandexClient
from services.bamboodom_keywords.clusterer import (
    cluster_keywords,
    label_to_cluster_id,
)

log = structlog.get_logger()

_MIN_VOLUME = 30  # filter out long-tail noise; matches existing research handler
_MAX_PER_SEED = 80  # DataForSEO limit per call

# Seed phrases per material — bare-bones starter set.
# Phase 2 enhancement: derive from ARTICLES_CATALOG series + texture types.
_SEEDS_BY_MATERIAL: dict[str, list[str]] = {
    "wpc": [
        "wpc панели",
        "стеновые панели wpc",
        "террасная доска wpc",
        "wpc для бассейна",
        "панели для интерьера",
        "монтаж wpc панелей",
        "wpc или дпк",
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

    # 1) DataForSEO calls — sequential to respect Yandex rate limits at vendor.
    # Parallel=2 should be safe but vendor sometimes flaps; sequential adds
    # ~5-10 seconds total per material which is fine for an admin-triggered job.
    dfs_client = DataForSEOYandexClient()
    fetched: dict[str, tuple[int, float | None]] = {}
    for seed in seeds:
        try:
            results = await dfs_client.keywords_for_seed(seed=seed, limit=_MAX_PER_SEED)
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

    # 2) Filter
    filtered = {
        phrase: (vol, comp)
        for phrase, (vol, comp) in fetched.items()
        if vol >= _MIN_VOLUME
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
