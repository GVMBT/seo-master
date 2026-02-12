"""Tests for db/repositories/projects.py."""

import pytest

from db.models import Project, ProjectCreate, ProjectUpdate
from db.repositories.projects import ProjectsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def project_row() -> dict:
    return {
        "id": 1,
        "user_id": 123456789,
        "name": "My Blog",
        "company_name": "Test Co",
        "specialization": "SEO",
        "website_url": "https://example.com",
        "company_city": None,
        "company_address": None,
        "company_phone": None,
        "company_email": None,
        "company_instagram": None,
        "company_vk": None,
        "company_pinterest": None,
        "company_telegram": None,
        "experience": None,
        "advantages": None,
        "description": None,
        "timezone": "Europe/Moscow",
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> ProjectsRepository:
    return ProjectsRepository(mock_db)  # type: ignore[arg-type]


class TestGetById:
    async def test_found(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient, project_row: dict
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=project_row))
        project = await repo.get_by_id(1)
        assert project is not None
        assert isinstance(project, Project)
        assert project.name == "My Blog"

    async def test_not_found(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=None))
        assert await repo.get_by_id(999) is None


class TestGetByUser:
    async def test_returns_list(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient, project_row: dict
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[project_row]))
        projects = await repo.get_by_user(123456789)
        assert len(projects) == 1
        assert projects[0].user_id == 123456789

    async def test_empty_list(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[]))
        projects = await repo.get_by_user(999)
        assert projects == []


class TestGetCountByUser:
    async def test_count(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[], count=3))
        assert await repo.get_count_by_user(123456789) == 3


class TestCreate:
    async def test_create(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient, project_row: dict
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[project_row]))
        data = ProjectCreate(
            user_id=123456789, name="My Blog", company_name="Test Co", specialization="SEO"
        )
        project = await repo.create(data)
        assert isinstance(project, Project)
        assert project.name == "My Blog"


class TestUpdate:
    async def test_partial_update(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient, project_row: dict
    ) -> None:
        updated = {**project_row, "name": "New Name"}
        mock_db.set_response("projects", MockResponse(data=[updated]))
        project = await repo.update(1, ProjectUpdate(name="New Name"))
        assert project is not None
        assert project.name == "New Name"

    async def test_empty_update(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient, project_row: dict
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=project_row))
        project = await repo.update(1, ProjectUpdate())
        assert project is not None


class TestDelete:
    async def test_success(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient, project_row: dict
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[project_row]))
        assert await repo.delete(1) is True

    async def test_not_found(
        self, repo: ProjectsRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("projects", MockResponse(data=[]))
        assert await repo.delete(999) is False
