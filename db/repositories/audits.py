"""Repository for site_audits and site_brandings tables."""

from db.models import SiteAudit, SiteAuditCreate, SiteBranding, SiteBrandingCreate
from db.repositories.base import BaseRepository

_AUDITS_TABLE = "site_audits"
_BRANDINGS_TABLE = "site_brandings"


class AuditsRepository(BaseRepository):
    """CRUD operations for site_audits + site_brandings (UNIQUE project_id)."""

    # --- site_audits ---

    async def upsert_audit(self, data: SiteAuditCreate) -> SiteAudit:
        """Create or update site audit (UNIQUE on project_id)."""
        resp = await self._table(_AUDITS_TABLE).upsert(data.model_dump(), on_conflict="project_id").execute()
        row = self._require_first(resp)
        return SiteAudit(**row)

    async def get_audit_by_project(self, project_id: int) -> SiteAudit | None:
        """Get latest audit for a project."""
        resp = await self._table(_AUDITS_TABLE).select("*").eq("project_id", project_id).maybe_single().execute()
        row = self._single(resp)
        return SiteAudit(**row) if row else None

    # --- site_brandings ---

    async def upsert_branding(self, data: SiteBrandingCreate) -> SiteBranding:
        """Create or update site branding (UNIQUE on project_id)."""
        resp = await self._table(_BRANDINGS_TABLE).upsert(data.model_dump(), on_conflict="project_id").execute()
        row = self._require_first(resp)
        return SiteBranding(**row)

    async def get_branding_by_project(self, project_id: int) -> SiteBranding | None:
        """Get branding info for a project."""
        resp = await self._table(_BRANDINGS_TABLE).select("*").eq("project_id", project_id).maybe_single().execute()
        row = self._single(resp)
        return SiteBranding(**row) if row else None
