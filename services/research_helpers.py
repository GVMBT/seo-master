"""Shared helper functions for web research / competitor analysis.

Used by both services/publish.py (auto-publish) and services/preview.py (manual pipeline).
DRY: single implementation for competitor filtering, analysis formatting, gap detection,
and web research data gathering (Serper + Firecrawl + Perplexity Sonar Pro).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import structlog

from cache.keys import RESEARCH_CACHE_TTL, CacheKeys
from services.ai.articles import RESEARCH_SCHEMA
from services.ai.orchestrator import GenerationRequest

if TYPE_CHECKING:
    from cache.client import RedisClient
    from services.ai.orchestrator import AIOrchestrator
    from services.external.firecrawl import FirecrawlClient
    from services.external.serper import SerperClient

log = structlog.get_logger()

# Truncation limits for competitor data passed to AI prompt
MAX_H2_PER_COMPETITOR = 12
MAX_SUMMARY_CHARS = 400

# Max competitor pages to scrape (cost: 1 Firecrawl credit each)
MAX_COMPETITOR_SCRAPE = 3

# Max internal links to include in prompt
MAX_INTERNAL_LINKS = 20


def is_own_site(url: str, project_url: str | None) -> bool:
    """Check if a URL belongs to the project's own site (skip in competitor scraping)."""
    if not project_url:
        return False
    try:
        own_domain = urlparse(project_url).netloc.lower().replace("www.", "")
        url_domain = urlparse(url).netloc.lower().replace("www.", "")
        return own_domain == url_domain
    except (ValueError, AttributeError):  # fmt: skip
        return False


def format_competitor_analysis(pages: list[dict[str, Any]]) -> str:
    """Format competitor scrape results into a text block for AI prompt."""
    lines: list[str] = []
    for i, page in enumerate(pages, 1):
        h2_headings = [h["text"] for h in page.get("headings", []) if h.get("level") == 2]
        lines.append(f"Конкурент {i} ({page.get('url', '')}):")
        lines.append(f"  Объём: ~{page.get('word_count', 0)} слов")
        if page.get("summary"):
            lines.append(f"  Тема: {page['summary'][:MAX_SUMMARY_CHARS]}")
        if h2_headings:
            lines.append(f"  H2: {', '.join(h2_headings[:MAX_H2_PER_COMPETITOR])}")
        lines.append("")
    return "\n".join(lines)


def identify_gaps(pages: list[dict[str, Any]]) -> str:
    """Summarize competitor structure for AI to identify content gaps.

    Instead of naive Counter-based comparison (which fails for semantically
    different headings like blogs), we pass raw competitor headings to the AI
    outline prompt and let it determine real content gaps.
    """
    if not pages:
        return ""

    lines: list[str] = []
    for i, page in enumerate(pages, 1):
        h2_list = [str(h.get("text", "")) for h in page.get("headings", []) if h.get("level") == 2]
        if h2_list:
            lines.append(f"Конкурент {i}: {', '.join(h2_list[:MAX_H2_PER_COMPETITOR])}")

    if not lines:
        return ""

    return (
        "Структура H2 конкурентов (определи, какие темы НЕ раскрыты "
        "ни одним конкурентом — это твоя уникальная ценность):\n" + "\n".join(lines)
    )


async def fetch_research(
    orchestrator: AIOrchestrator,
    redis: RedisClient | None,
    *,
    main_phrase: str,
    specialization: str,
    company_name: str,
    geography: str = "",
    company_description_short: str = "",
) -> dict[str, Any] | None:
    """Fetch web research via Perplexity Sonar Pro with Redis caching.

    Returns parsed research dict or None on failure (graceful degradation E53).
    """
    cache_input = f"{main_phrase}|{specialization}|{company_name}".lower()
    keyword_hash = hashlib.md5(cache_input.encode(), usedforsecurity=False).hexdigest()[:12]
    cache_key = CacheKeys.research(keyword_hash)

    # Check cache
    if redis:
        try:
            cached = await redis.get(cache_key)
            if cached:
                parsed = json.loads(cached)
                if isinstance(parsed, dict):
                    log.info("research_cache_hit", keyword=main_phrase[:50])
                    return parsed
                log.warning("research_cache_invalid_type", type=type(parsed).__name__)
        except Exception:
            log.warning("research_cache_read_failed", exc_info=True)

    # Fetch from Sonar Pro (E53: graceful degradation on failure)
    try:
        context = {
            "main_phrase": main_phrase,
            "specialization": specialization,
            "company_name": company_name,
            "geography": geography,
            "company_description_short": company_description_short[:200] if company_description_short else "",
            "language": "ru",
        }
        request = GenerationRequest(
            task="article_research",
            context=context,
            user_id=0,  # system-level request, no per-user rate limit
            response_schema=RESEARCH_SCHEMA,
        )
        result = await orchestrator.generate_without_rate_limit(request)
        research = result.content if isinstance(result.content, dict) else None
        if not research:
            return None
    except Exception:
        log.warning("research_fetch_failed", keyword=main_phrase[:50], exc_info=True)
        return None

    # Cache result
    if redis:
        try:
            await redis.set(cache_key, json.dumps(research, ensure_ascii=False), ex=RESEARCH_CACHE_TTL)
            log.info("research_cached", keyword=main_phrase[:50], ttl=RESEARCH_CACHE_TTL)
        except Exception:
            log.warning("research_cache_write_failed", exc_info=True)

    return research


async def _scrape_competitors(
    firecrawl: FirecrawlClient,
    organic: list[dict[str, Any]],
    project_url: str | None,
) -> list[dict[str, Any]]:
    """Scrape top competitor pages from Serper organic results via Firecrawl."""
    competitor_urls = [
        r["link"]
        for r in organic
        if r.get("link") and not is_own_site(r["link"], project_url)
    ][:MAX_COMPETITOR_SCRAPE]
    if not competitor_urls:
        return []
    scrape_tasks = [firecrawl.scrape_content(url) for url in competitor_urls]
    scrape_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)
    pages: list[dict[str, Any]] = []
    for sr in scrape_results:
        if sr and not isinstance(sr, BaseException):
            pages.append(
                {
                    "url": sr.url,
                    "word_count": sr.word_count,
                    "headings": sr.headings,
                    "summary": sr.summary or "",
                }
            )
    return pages


async def gather_websearch_data(
    keyword: str,
    project_url: str | None,
    *,
    serper: SerperClient | None = None,
    firecrawl: FirecrawlClient | None = None,
    orchestrator: AIOrchestrator | None = None,
    redis: RedisClient | None = None,
    specialization: str = "",
    company_name: str = "",
    geography: str = "",
    company_description_short: str = "",
) -> dict[str, Any]:
    """Gather Serper PAA + Firecrawl competitor data + Research in parallel.

    Returns dict with keys: serper_data, competitor_pages, competitor_analysis,
    competitor_gaps, research_data. All values gracefully degrade to empty on failure.
    Cost: ~$0.001 (Serper) + ~$0.03 (3 Firecrawl scrapes) + ~$0.01 (Sonar Pro).
    """
    result: dict[str, Any] = {
        "serper_data": None,
        "competitor_pages": [],
        "competitor_analysis": "",
        "competitor_gaps": "",
        "research_data": None,
    }

    tasks: dict[str, Any] = {}

    # Serper: PAA + organic results for the keyword
    if serper:
        tasks["serper"] = serper.search(keyword, num=10)

    # Research: Perplexity Sonar Pro (parallel with Serper, API_CONTRACTS.md section 7a)
    if orchestrator:
        tasks["research"] = fetch_research(
            orchestrator,
            redis,
            main_phrase=keyword,
            specialization=specialization,
            company_name=company_name,
            geography=geography,
            company_description_short=company_description_short,
        )

    # Firecrawl: internal links for the project site (if URL provided)
    if firecrawl and project_url:
        tasks["map"] = firecrawl.map_site(project_url, limit=100)

    if not tasks:
        return result

    task_keys = list(tasks.keys())
    task_coros = list(tasks.values())
    gathered = await asyncio.gather(*task_coros, return_exceptions=True)
    responses = dict(zip(task_keys, gathered, strict=True))

    # Process Research results (E53: graceful degradation)
    research_result = responses.get("research")
    if research_result and not isinstance(research_result, BaseException):
        result["research_data"] = research_result
    elif isinstance(research_result, BaseException):
        log.warning("research_skipped", error=str(research_result))

    # Process Serper results
    serper_result = responses.get("serper")
    if serper_result and not isinstance(serper_result, BaseException):
        result["serper_data"] = {
            "organic": serper_result.organic,
            "people_also_ask": serper_result.people_also_ask,
            "related_searches": serper_result.related_searches,
        }

        # Scrape top-3 competitor pages via Firecrawl
        if firecrawl and serper_result.organic:
            pages = await _scrape_competitors(firecrawl, serper_result.organic, project_url)
            result["competitor_pages"] = pages
            if pages:
                result["competitor_analysis"] = format_competitor_analysis(pages)
                result["competitor_gaps"] = identify_gaps(pages)
    elif isinstance(serper_result, BaseException):
        log.warning("websearch_serper_failed", error=str(serper_result))

    # Format internal links
    map_result = responses.get("map")
    if map_result and not isinstance(map_result, BaseException):
        urls = [u.get("url", "") for u in map_result.urls[:MAX_INTERNAL_LINKS] if u.get("url")]
        result["internal_links"] = "\n".join(urls) if urls else ""
    elif isinstance(map_result, BaseException):
        log.warning("websearch_map_failed", error=str(map_result))

    log.info(
        "websearch_data_gathered",
        has_serper=result["serper_data"] is not None,
        has_research=result["research_data"] is not None,
        competitor_count=len(result["competitor_pages"]),
        has_internal_links=bool(result.get("internal_links")),
    )
    return result
