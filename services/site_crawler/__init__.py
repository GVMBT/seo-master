"""Site crawlers — небольшие хелперы для обхода сайтов на стороне бота.

Сейчас единственный модуль — `bamboodom`: грузит sitemap.xml + (опц.) HTML-обход
с главной страницы, считает «новые» URL'ы относительно snapshot'а в Redis.
"""

from services.site_crawler.bamboodom import (
    CrawlResult,
    crawl_bamboodom,
    diff_against_snapshot,
    save_snapshot,
)

__all__ = [
    "CrawlResult",
    "crawl_bamboodom",
    "diff_against_snapshot",
    "save_snapshot",
]
