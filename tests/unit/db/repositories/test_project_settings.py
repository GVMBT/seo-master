"""Tests for db/repositories/project_settings.py."""

import pytest

from db.models import ProjectPlatformSettings
from db.repositories.project_settings import ProjectPlatformSettingsRepository

from .conftest import MockResponse, MockSupabaseClient

_TABLE = "project_platform_settings"


@pytest.fixture
def settings_row() -> dict:
    return {
        "id": 1,
        "project_id": 5,
        "platform_type": "wordpress",
        "text_settings": {"words_min": 2000, "html_style": "magazine"},
        "image_settings": {"aspect_ratio": "16:9", "count": 3},
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> ProjectPlatformSettingsRepository:
    return ProjectPlatformSettingsRepository(mock_db)  # type: ignore[arg-type]


class TestGetByProjectAndPlatform:
    async def test_found(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
        settings_row: dict,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=settings_row))
        result = await repo.get_by_project_and_platform(5, "wordpress")
        assert result is not None
        assert isinstance(result, ProjectPlatformSettings)
        assert result.platform_type == "wordpress"
        assert result.text_settings == {"words_min": 2000, "html_style": "magazine"}

    async def test_not_found(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=None))
        result = await repo.get_by_project_and_platform(5, "telegram")
        assert result is None


class TestGetAllByProject:
    async def test_returns_list(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
        settings_row: dict,
    ) -> None:
        tg_row = {
            **settings_row,
            "id": 2,
            "platform_type": "telegram",
            "text_settings": {"words_min": 500},
            "image_settings": {},
        }
        mock_db.set_response(_TABLE, MockResponse(data=[settings_row, tg_row]))
        result = await repo.get_all_by_project(5)
        assert len(result) == 2
        assert all(isinstance(r, ProjectPlatformSettings) for r in result)

    async def test_empty(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=[]))
        result = await repo.get_all_by_project(5)
        assert result == []


class TestUpsert:
    async def test_upsert_creates(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
        settings_row: dict,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=[settings_row]))
        result = await repo.upsert(
            5,
            "wordpress",
            text_settings={"words_min": 2000, "html_style": "magazine"},
            image_settings={"aspect_ratio": "16:9", "count": 3},
        )
        assert isinstance(result, ProjectPlatformSettings)
        assert result.project_id == 5

    async def test_upsert_partial_text_only(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
        settings_row: dict,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=[settings_row]))
        result = await repo.upsert(5, "wordpress", text_settings={"words_min": 3000})
        assert isinstance(result, ProjectPlatformSettings)

    async def test_upsert_partial_image_only(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
        settings_row: dict,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=[settings_row]))
        result = await repo.upsert(5, "wordpress", image_settings={"count": 5})
        assert isinstance(result, ProjectPlatformSettings)


class TestDelete:
    async def test_success(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
        settings_row: dict,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=[settings_row]))
        assert await repo.delete(5, "wordpress") is True

    async def test_not_found(
        self,
        repo: ProjectPlatformSettingsRepository,
        mock_db: MockSupabaseClient,
    ) -> None:
        mock_db.set_response(_TABLE, MockResponse(data=[]))
        assert await repo.delete(5, "telegram") is False
