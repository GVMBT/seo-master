"""Tests for db/repositories/audits.py."""

import pytest

from db.models import SiteAudit, SiteAuditCreate, SiteBranding, SiteBrandingCreate
from db.repositories.audits import AuditsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def audit_row() -> dict:
    return {
        "id": 1,
        "project_id": 1,
        "url": "https://example.com",
        "performance": 85,
        "accessibility": 90,
        "best_practices": 92,
        "seo_score": 88,
        "lcp_ms": 2500,
        "inp_ms": 200,
        "cls": "0.1",
        "ttfb_ms": 800,
        "full_report": {"raw": "data"},
        "recommendations": [
            {"text": "Optimize images", "priority": "high"},
            {"text": "Add meta descriptions", "priority": "medium"},
        ],
        "audited_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def branding_row() -> dict:
    return {
        "id": 1,
        "project_id": 1,
        "url": "https://example.com",
        "colors": {"primary": "#333", "secondary": "#666"},
        "fonts": {"heading": "Arial", "body": "Helvetica"},
        "logo_url": "https://example.com/logo.png",
        "extracted_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> AuditsRepository:
    return AuditsRepository(mock_db)  # type: ignore[arg-type]


class TestUpsertAudit:
    async def test_upsert(self, repo: AuditsRepository, mock_db: MockSupabaseClient, audit_row: dict) -> None:
        mock_db.set_response("site_audits", MockResponse(data=[audit_row]))
        data = SiteAuditCreate(project_id=1, url="https://example.com", performance=85, seo_score=88)
        audit = await repo.upsert_audit(data)
        assert isinstance(audit, SiteAudit)
        assert audit.performance == 85


class TestGetAuditByProject:
    async def test_found(self, repo: AuditsRepository, mock_db: MockSupabaseClient, audit_row: dict) -> None:
        mock_db.set_response("site_audits", MockResponse(data=audit_row))
        audit = await repo.get_audit_by_project(1)
        assert audit is not None
        assert audit.seo_score == 88

    async def test_not_found(self, repo: AuditsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("site_audits", MockResponse(data=None))
        assert await repo.get_audit_by_project(999) is None


class TestUpsertBranding:
    async def test_upsert(self, repo: AuditsRepository, mock_db: MockSupabaseClient, branding_row: dict) -> None:
        mock_db.set_response("site_brandings", MockResponse(data=[branding_row]))
        data = SiteBrandingCreate(
            project_id=1,
            url="https://example.com",
            colors={"primary": "#333"},
        )
        branding = await repo.upsert_branding(data)
        assert isinstance(branding, SiteBranding)


class TestGetBrandingByProject:
    async def test_found(self, repo: AuditsRepository, mock_db: MockSupabaseClient, branding_row: dict) -> None:
        mock_db.set_response("site_brandings", MockResponse(data=branding_row))
        branding = await repo.get_branding_by_project(1)
        assert branding is not None
        assert branding.logo_url == "https://example.com/logo.png"

    async def test_not_found(self, repo: AuditsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("site_brandings", MockResponse(data=None))
        assert await repo.get_branding_by_project(999) is None
