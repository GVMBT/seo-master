"""Tests for services/analysis.py — SiteAnalysisService.

Covers: full success, partial failures, total failure, internal links caching.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.analysis import SiteAnalysisService
from services.external.firecrawl import BrandingResult, MapResult
from services.external.pagespeed import AuditResult


def _make_branding() -> BrandingResult:
    return BrandingResult(
        colors={"background": "#fff", "text": "#333", "accent": "#06c"},
        fonts={"heading": "Arial", "body": "Helvetica"},
        logo_url="https://example.com/logo.png",
    )


def _make_map() -> MapResult:
    return MapResult(
        urls=[{"url": f"https://example.com/page{i}"} for i in range(5)],
        total_found=5,
    )


def _make_psi() -> AuditResult:
    return AuditResult(
        performance_score=85,
        accessibility_score=90,
        best_practices_score=80,
        seo_score=95,
        fcp_ms=1200,
        lcp_ms=2500,
        cls=0.05,
        tbt_ms=300,
        inp_ms=200,
        ttfb_ms=400,
        speed_index=3000,
        recommendations=[{"title": "Minify CSS", "description": "...", "priority": "high"}],
        full_report={"version": "1.0"},
    )


def _make_service(
    *,
    branding: BrandingResult | Exception | None = None,
    map_result: MapResult | Exception | None = None,
    psi: AuditResult | Exception | None = None,
) -> SiteAnalysisService:
    db = MagicMock()
    firecrawl = MagicMock()
    pagespeed = MagicMock()

    if isinstance(branding, Exception):
        firecrawl.scrape_branding = AsyncMock(side_effect=branding)
    else:
        firecrawl.scrape_branding = AsyncMock(return_value=branding)

    if isinstance(map_result, Exception):
        firecrawl.map_site = AsyncMock(side_effect=map_result)
    else:
        firecrawl.map_site = AsyncMock(return_value=map_result)

    if isinstance(psi, Exception):
        pagespeed.audit = AsyncMock(side_effect=psi)
    else:
        pagespeed.audit = AsyncMock(return_value=psi)

    return SiteAnalysisService(db, firecrawl, pagespeed)


@pytest.mark.asyncio
class TestSiteAnalysisService:
    """SiteAnalysisService.run_full_analysis."""

    async def test_full_success(self) -> None:
        """All 3 components succeed — branding, map, PSI saved."""
        svc = _make_service(
            branding=_make_branding(),
            map_result=_make_map(),
            psi=_make_psi(),
        )

        with (
            patch("services.analysis.AuditsRepository") as mock_audits_cls,
            patch("services.analysis.ConnectionsRepository") as mock_conn_cls,
        ):
            mock_audits = MagicMock()
            mock_audits.upsert_branding = AsyncMock()
            mock_audits.upsert_audit = AsyncMock()
            mock_audits_cls.return_value = mock_audits

            mock_conn = MagicMock()
            mock_conn.merge_metadata = AsyncMock()
            mock_conn_cls.return_value = mock_conn

            report = await svc.run_full_analysis(1, "https://example.com", 10)

        assert report.branding is not None
        assert report.branding.colors["accent"] == "#06c"
        assert len(report.map_urls) == 5
        assert report.psi is not None
        assert report.psi.performance_score == 85
        assert not report.errors

        mock_audits.upsert_branding.assert_called_once()
        mock_audits.upsert_audit.assert_called_once()
        mock_conn.merge_metadata.assert_called_once()

    async def test_branding_fails_others_succeed(self) -> None:
        """Branding failure doesn't block map + PSI."""
        svc = _make_service(
            branding=RuntimeError("Firecrawl down"),
            map_result=_make_map(),
            psi=_make_psi(),
        )

        with (
            patch("services.analysis.AuditsRepository") as mock_audits_cls,
            patch("services.analysis.ConnectionsRepository") as mock_conn_cls,
        ):
            mock_audits = MagicMock()
            mock_audits.upsert_audit = AsyncMock()
            mock_audits_cls.return_value = mock_audits

            mock_conn = MagicMock()
            mock_conn.merge_metadata = AsyncMock()
            mock_conn_cls.return_value = mock_conn

            report = await svc.run_full_analysis(1, "https://example.com", 10)

        assert report.branding is None
        assert len(report.map_urls) == 5
        assert report.psi is not None
        assert len(report.errors) == 1
        assert "branding" in report.errors[0]

    async def test_all_fail(self) -> None:
        """All 3 components fail — report has 3 errors, no data."""
        svc = _make_service(
            branding=RuntimeError("fail"),
            map_result=RuntimeError("fail"),
            psi=RuntimeError("fail"),
        )

        with patch("services.analysis.AuditsRepository"), patch("services.analysis.ConnectionsRepository"):
            report = await svc.run_full_analysis(1, "https://example.com", 10)

        assert report.branding is None
        assert report.map_urls == []
        assert report.psi is None
        assert len(report.errors) == 3

    async def test_none_results_no_save(self) -> None:
        """When clients return None (e.g. empty response), nothing is saved."""
        svc = _make_service(branding=None, map_result=None, psi=None)

        with (
            patch("services.analysis.AuditsRepository") as mock_audits_cls,
            patch("services.analysis.ConnectionsRepository") as mock_conn_cls,
        ):
            mock_audits = MagicMock()
            mock_audits.upsert_branding = AsyncMock()
            mock_audits.upsert_audit = AsyncMock()
            mock_audits_cls.return_value = mock_audits

            mock_conn = MagicMock()
            mock_conn.merge_metadata = AsyncMock()
            mock_conn_cls.return_value = mock_conn

            report = await svc.run_full_analysis(1, "https://example.com", 10)

        assert report.branding is None
        assert report.map_urls == []
        assert report.psi is None
        assert not report.errors

        mock_audits.upsert_branding.assert_not_called()
        mock_audits.upsert_audit.assert_not_called()
        mock_conn.merge_metadata.assert_not_called()

    async def test_psi_field_mapping(self) -> None:
        """AuditResult fields are correctly mapped to SiteAuditCreate."""
        svc = _make_service(psi=_make_psi())

        with (
            patch("services.analysis.AuditsRepository") as mock_audits_cls,
            patch("services.analysis.ConnectionsRepository"),
        ):
            mock_audits = MagicMock()
            mock_audits.upsert_audit = AsyncMock()
            mock_audits_cls.return_value = mock_audits

            await svc.run_full_analysis(1, "https://example.com", 10)

        call_args = mock_audits.upsert_audit.call_args[0][0]
        assert call_args.performance == 85
        assert call_args.accessibility == 90
        assert call_args.best_practices == 80
        assert call_args.seo_score == 95
        assert call_args.lcp_ms == 2500
        assert call_args.ttfb_ms == 400
