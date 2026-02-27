"""Shared helper functions for web research / competitor analysis.

Used by both services/publish.py (auto-publish) and services/preview.py (manual pipeline).
DRY: single implementation for competitor filtering, analysis formatting, and gap detection.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

# Truncation limits for competitor data passed to AI prompt
MAX_H2_PER_COMPETITOR = 12
MAX_SUMMARY_CHARS = 400


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
