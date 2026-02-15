"""Tests for db/repositories/connections.py — encryption integration."""

import pytest

from db.credential_manager import CredentialManager
from db.models import PlatformConnection, PlatformConnectionCreate
from db.repositories.connections import ConnectionsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def raw_creds() -> dict:
    return {"url": "https://site.com/wp-json", "user": "admin", "app_password": "xxxx"}


@pytest.fixture
def connection_row(credential_manager: CredentialManager, raw_creds: dict) -> dict:
    return {
        "id": 1,
        "project_id": 1,
        "platform_type": "wordpress",
        "status": "active",
        "credentials": credential_manager.encrypt(raw_creds),
        "metadata": {},
        "identifier": "https://site.com",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient, credential_manager: CredentialManager) -> ConnectionsRepository:
    return ConnectionsRepository(mock_db, credential_manager)  # type: ignore[arg-type]


class TestGetById:
    async def test_decrypts_credentials(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
        raw_creds: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=connection_row))
        conn = await repo.get_by_id(1)
        assert conn is not None
        assert isinstance(conn, PlatformConnection)
        # credentials is decrypted dict from repository layer
        assert conn.credentials == raw_creds

    async def test_not_found(
        self, repo: ConnectionsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=None))
        assert await repo.get_by_id(999) is None


class TestGetByProject:
    async def test_returns_decrypted_list(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        conns = await repo.get_by_project(1)
        assert len(conns) == 1
        assert conns[0].platform_type == "wordpress"


class TestGetByProjectAndPlatform:
    async def test_filtered(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        conns = await repo.get_by_project_and_platform(1, "wordpress")
        assert len(conns) == 1


class TestCreate:
    async def test_encrypts_credentials(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
        raw_creds: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        data = PlatformConnectionCreate(
            project_id=1,
            platform_type="wordpress",
            identifier="https://site.com",
        )
        conn = await repo.create(data, raw_creds)
        assert isinstance(conn, PlatformConnection)


class TestUpdateCredentials:
    async def test_re_encrypts(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        new_creds = {"url": "https://new-site.com", "user": "admin", "app_password": "new"}
        conn = await repo.update_credentials(1, new_creds)
        assert conn is not None

    async def test_not_found(
        self, repo: ConnectionsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[]))
        assert await repo.update_credentials(999, {"key": "val"}) is None


class TestUpdateStatus:
    async def test_update_to_error(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        error_row = {**connection_row, "status": "error"}
        mock_db.set_response("platform_connections", MockResponse(data=[error_row]))
        conn = await repo.update_status(1, "error")
        assert conn is not None
        assert conn.status == "error"


class TestDelete:
    async def test_success(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        assert await repo.delete(1) is True


class TestGetByIdentifierForUser:
    async def test_found(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[{"id": 1}]))
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        conn = await repo.get_by_identifier_for_user("https://site.com", "wordpress", 42)
        assert conn is not None
        assert isinstance(conn, PlatformConnection)
        assert conn.identifier == "https://site.com"

    async def test_not_found(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[{"id": 1}]))
        mock_db.set_response("platform_connections", MockResponse(data=[]))
        conn = await repo.get_by_identifier_for_user("https://other.com", "wordpress", 42)
        assert conn is None

    async def test_no_projects(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[]))
        conn = await repo.get_by_identifier_for_user("https://site.com", "wordpress", 999)
        assert conn is None


class TestGetAllRaw:
    async def test_returns_encrypted_data(
        self,
        repo: ConnectionsRepository,
        mock_db: MockSupabaseClient,
        connection_row: dict,
    ) -> None:
        mock_db.set_response("platform_connections", MockResponse(data=[connection_row]))
        raw = await repo.get_all_raw()
        assert len(raw) == 1
        # Raw data should still have encrypted credentials
        assert raw[0]["credentials"] == connection_row["credentials"]
