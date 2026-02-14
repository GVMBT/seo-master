"""External service clients -- Telegraph, Firecrawl, DataForSEO, Serper, PageSpeed."""

from services.external.dataforseo import DataForSEOClient, KeywordData, KeywordSuggestion
from services.external.firecrawl import (
    BrandingResult,
    FirecrawlClient,
    MapResult,
    ScrapeResult,
)
from services.external.pagespeed import AuditResult, PageSpeedClient
from services.external.serper import SerperClient, SerperResult
from services.external.telegraph import TelegraphClient, TelegraphPage

__all__ = [
    "AuditResult",
    "BrandingResult",
    "DataForSEOClient",
    "FirecrawlClient",
    "KeywordData",
    "KeywordSuggestion",
    "MapResult",
    "PageSpeedClient",
    "ScrapeResult",
    "SerperClient",
    "SerperResult",
    "TelegraphClient",
    "TelegraphPage",
]
