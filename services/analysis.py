"""Site analysis service — branding, internal links, PSI audit.

Runs all three analyses in parallel at WordPress connection time.
Each component is optional — partial failures don't block the others.

Source of truth: PRD.md §7.1 (site connection flow).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal

import structlog

from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import SiteAuditCreate, SiteBrandingCreate
from db.repositories.audits import AuditsRepository
from db.repositories.connections import ConnectionsRepository
from services.external.firecrawl import BrandingResult, FirecrawlClient, MapResult
from services.external.pagespeed import AuditResult, PageSpeedClient

log = structlog.get_logger()

MAX_INTERNAL_LINKS_CACHE = 50  # How many links to cache in connection metadata


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    """Result of full site analysis (all fields optional)."""

    branding: BrandingResult | None = None
    map_urls: list[str] = field(default_factory=list)
    psi: AuditResult | None = None
    errors: list[str] = field(default_factory=list)


class SiteAnalysisService:
    """Orchestrates branding + map + PSI in parallel.

    Zero Telegram dependencies. Designed to be called fire-and-forget
    from connection handlers.
    """

    def __init__(
        self,
        db: SupabaseClient,
        firecrawl: FirecrawlClient,
        pagespeed: PageSpeedClient,
        encryption_key: str = "",
    ) -> None:
        self._db = db
        self._firecrawl = firecrawl
        self._pagespeed = pagespeed
        self._encryption_key = encryption_key

    async def run_full_analysis(
        self,
        project_id: int,
        site_url: str,
        connection_id: int,
    ) -> AnalysisReport:
        """Run branding + map + PSI in parallel, persist results.

        Each component is independent — if one fails, others still save.
        Internal links are stored in connection metadata for cache.
        """
        branding_coro = self._firecrawl.scrape_branding(site_url)
        map_coro = self._firecrawl.map_site(site_url, limit=100)
        psi_coro = self._pagespeed.audit(site_url)

        results = await asyncio.gather(
            branding_coro, map_coro, psi_coro, return_exceptions=True,
        )

        branding_raw = results[0]
        map_raw = results[1]
        psi_raw = results[2]

        errors: list[str] = []
        branding: BrandingResult | None = None
        map_result: MapResult | None = None
        psi: AuditResult | None = None
        audits_repo = AuditsRepository(self._db)

        # --- Save branding ---
        if isinstance(branding_raw, BaseException):
            errors.append(f"branding: {branding_raw}")
            log.warning("analysis.branding_failed", project_id=project_id, error=str(branding_raw))
        elif branding_raw is not None:
            branding = branding_raw
            await audits_repo.upsert_branding(SiteBrandingCreate(
                project_id=project_id,
                url=site_url,
                colors=branding.colors,
                fonts=branding.fonts,
                logo_url=branding.logo_url,
            ))
            log.info("analysis.branding_saved", project_id=project_id)

        # --- Save internal links to connection metadata ---
        map_urls: list[str] = []
        if isinstance(map_raw, BaseException):
            errors.append(f"map: {map_raw}")
            log.warning("analysis.map_failed", project_id=project_id, error=str(map_raw))
        elif map_raw is not None:
            map_result = map_raw
            map_urls = [
                u.get("url", "") for u in map_result.urls[:MAX_INTERNAL_LINKS_CACHE]
                if u.get("url")
            ]
            if map_urls:
                await self._save_internal_links(connection_id, map_urls)
                log.info("analysis.map_saved", project_id=project_id, url_count=len(map_urls))

        # --- Save PSI audit ---
        if isinstance(psi_raw, BaseException):
            errors.append(f"psi: {psi_raw}")
            log.warning("analysis.psi_failed", project_id=project_id, error=str(psi_raw))
        elif psi_raw is not None:
            psi = psi_raw
            await audits_repo.upsert_audit(SiteAuditCreate(
                project_id=project_id,
                url=site_url,
                performance=psi.performance_score,
                accessibility=psi.accessibility_score,
                best_practices=psi.best_practices_score,
                seo_score=psi.seo_score,
                lcp_ms=psi.lcp_ms,
                inp_ms=psi.inp_ms,
                cls=Decimal(str(psi.cls)),
                ttfb_ms=psi.ttfb_ms,
                full_report=psi.full_report,
                recommendations=psi.recommendations,
            ))
            log.info("analysis.psi_saved", project_id=project_id)

        return AnalysisReport(
            branding=branding,
            map_urls=map_urls,
            psi=psi,
            errors=errors,
        )

    async def _save_internal_links(self, connection_id: int, urls: list[str]) -> None:
        """Store internal links in connection metadata for caching."""
        cm = CredentialManager(self._encryption_key)
        repo = ConnectionsRepository(self._db, cm)
        await repo.merge_metadata(connection_id, {"internal_links": "\n".join(urls)})
