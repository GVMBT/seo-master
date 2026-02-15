"""Repository for platform_connections table with Fernet encryption."""

from typing import Any

from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnection, PlatformConnectionCreate, PlatformConnectionUpdate
from db.repositories.base import BaseRepository

_TABLE = "platform_connections"


class ConnectionsRepository(BaseRepository):
    """CRUD for platform_connections. Encrypts/decrypts credentials transparently."""

    def __init__(self, db: SupabaseClient, credential_manager: CredentialManager) -> None:
        super().__init__(db)
        self._cm = credential_manager

    def _decrypt_row(self, row: dict[str, Any]) -> dict[str, Any]:
        """Decrypt credentials field in a row dict."""
        if row.get("credentials"):
            decrypted = self._cm.decrypt(row["credentials"])
            row = {**row, "credentials": decrypted}
        return row

    def _to_connection(self, row: dict[str, Any]) -> PlatformConnection:
        """Convert row to PlatformConnection with decrypted credentials dict."""
        decrypted = self._decrypt_row(row)
        return PlatformConnection(**decrypted)

    async def get_by_id(self, connection_id: int) -> PlatformConnection | None:
        """Get connection by ID with decrypted credentials."""
        resp = await self._table(_TABLE).select("*").eq("id", connection_id).maybe_single().execute()
        row = self._single(resp)
        if not row:
            return None
        return self._to_connection(row)

    async def get_by_project(self, project_id: int) -> list[PlatformConnection]:
        """Get all connections for a project with decrypted credentials."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [self._to_connection(row) for row in self._rows(resp)]

    async def get_by_project_and_platform(
        self, project_id: int, platform_type: str
    ) -> list[PlatformConnection]:
        """Get connections filtered by project and platform type."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .eq("project_id", project_id)
            .eq("platform_type", platform_type)
            .execute()
        )
        return [self._to_connection(row) for row in self._rows(resp)]

    async def create(self, data: PlatformConnectionCreate, raw_credentials: dict[str, Any]) -> PlatformConnection:
        """Create connection with encrypted credentials."""
        encrypted = self._cm.encrypt(raw_credentials)
        payload = data.model_dump()
        payload["credentials"] = encrypted
        resp = await self._table(_TABLE).insert(payload).execute()
        row = self._require_first(resp)
        return self._to_connection(row)

    async def update_credentials(
        self, connection_id: int, raw_credentials: dict[str, Any]
    ) -> PlatformConnection | None:
        """Re-encrypt and update credentials."""
        encrypted = self._cm.encrypt(raw_credentials)
        resp = (
            await self._table(_TABLE)
            .update({"credentials": encrypted})
            .eq("id", connection_id)
            .execute()
        )
        row = self._first(resp)
        return self._to_connection(row) if row else None

    async def update_status(self, connection_id: int, status: str) -> PlatformConnection | None:
        """Update connection status (active, error, disconnected)."""
        resp = (
            await self._table(_TABLE)
            .update({"status": status})
            .eq("id", connection_id)
            .execute()
        )
        row = self._first(resp)
        return self._to_connection(row) if row else None

    async def update(self, connection_id: int, data: PlatformConnectionUpdate) -> PlatformConnection | None:
        """Partial update (status, metadata). Does NOT update credentials — use update_credentials."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return await self.get_by_id(connection_id)
        resp = await self._table(_TABLE).update(payload).eq("id", connection_id).execute()
        row = self._first(resp)
        return self._to_connection(row) if row else None

    async def delete(self, connection_id: int) -> bool:
        """Delete connection."""
        resp = await self._table(_TABLE).delete().eq("id", connection_id).execute()
        return len(self._rows(resp)) > 0

    async def get_by_identifier_for_user(
        self, identifier: str, platform_type: str, user_id: int
    ) -> PlatformConnection | None:
        """Find an existing connection by identifier+platform across user's projects.

        Used for E41: duplicate WordPress site warning.
        Joins through projects table to filter by user_id.
        """
        # Get all user's projects first, then check connections
        projects_resp = (
            await self._db.table("projects")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        project_ids = [row["id"] for row in self._rows(projects_resp)]
        if not project_ids:
            return None

        for pid in project_ids:
            resp = (
                await self._table(_TABLE)
                .select("*")
                .eq("project_id", pid)
                .eq("platform_type", platform_type)
                .eq("identifier", identifier)
                .limit(1)
                .execute()
            )
            rows = self._rows(resp)
            if rows:
                return self._to_connection(rows[0])
        return None

    async def get_platform_types_by_project(self, project_id: int) -> list[str]:
        """Get distinct active platform types for a project (no credential decryption)."""
        resp = (
            await self._table(_TABLE)
            .select("platform_type")
            .eq("project_id", project_id)
            .eq("status", "active")
            .execute()
        )
        rows = self._rows(resp)
        return sorted({row["platform_type"] for row in rows})

    async def get_all_raw(self) -> list[dict[str, Any]]:
        """Get all connections with RAW (encrypted) credentials. For key rotation only."""
        resp = await self._table(_TABLE).select("*").execute()
        return self._rows(resp)

    async def update_credentials_raw(self, connection_id: int, encrypted: str) -> None:
        """Update credentials with pre-encrypted string. For key rotation only."""
        await self._table(_TABLE).update({"credentials": encrypted}).eq("id", connection_id).execute()
