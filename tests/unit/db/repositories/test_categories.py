"""Tests for db/repositories/categories.py."""

import pytest

from db.models import (
    Category,
    CategoryCreate,
    CategoryUpdate,
    PlatformContentOverride,
    PlatformContentOverrideCreate,
)
from db.repositories.categories import CategoriesRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def category_row() -> dict:
    return {
        "id": 1,
        "project_id": 1,
        "name": "SEO Tips",
        "description": "Tips about SEO",
        "keywords": [{"phrase": "seo tips", "volume": 1000, "difficulty": 30}],
        "media": [],
        "prices": None,
        "reviews": [],
        "image_settings": {"style": "photo"},
        "text_settings": {"tone": "professional"},
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def override_row() -> dict:
    return {
        "id": 1,
        "category_id": 1,
        "platform_type": "wordpress",
        "image_settings": {"style": "illustration"},
        "text_settings": None,
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> CategoriesRepository:
    return CategoriesRepository(mock_db)  # type: ignore[arg-type]


class TestGetById:
    async def test_found(self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict) -> None:
        mock_db.set_response("categories", MockResponse(data=category_row))
        cat = await repo.get_by_id(1)
        assert cat is not None
        assert isinstance(cat, Category)
        assert cat.name == "SEO Tips"

    async def test_not_found(self, repo: CategoriesRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("categories", MockResponse(data=None))
        assert await repo.get_by_id(999) is None


class TestGetByProject:
    async def test_returns_list(
        self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict
    ) -> None:
        mock_db.set_response("categories", MockResponse(data=[category_row]))
        cats = await repo.get_by_project(1)
        assert len(cats) == 1

    async def test_empty(self, repo: CategoriesRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("categories", MockResponse(data=[]))
        assert await repo.get_by_project(1) == []


class TestCreate:
    async def test_create(self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict) -> None:
        mock_db.set_response("categories", MockResponse(data=[category_row]))
        cat = await repo.create(CategoryCreate(project_id=1, name="SEO Tips"))
        assert isinstance(cat, Category)


class TestUpdate:
    async def test_partial_update(
        self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict
    ) -> None:
        updated = {**category_row, "name": "New Name"}
        mock_db.set_response("categories", MockResponse(data=[updated]))
        cat = await repo.update(1, CategoryUpdate(name="New Name"))
        assert cat is not None
        assert cat.name == "New Name"


class TestUpdateKeywords:
    async def test_replace_keywords(
        self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict
    ) -> None:
        new_kw = [{"phrase": "new kw", "volume": 500, "difficulty": 20}]
        updated = {**category_row, "keywords": new_kw}
        mock_db.set_response("categories", MockResponse(data=[updated]))
        cat = await repo.update_keywords(1, new_kw)
        assert cat is not None
        assert cat.keywords == new_kw


class TestDelete:
    async def test_success(self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict) -> None:
        mock_db.set_response("categories", MockResponse(data=[category_row]))
        assert await repo.delete(1) is True


class TestContentSettingsInheritance:
    """F41: override field None -> inherit from category."""

    async def test_no_override_returns_category_settings(
        self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict
    ) -> None:
        mock_db.set_response("categories", MockResponse(data=category_row))
        mock_db.set_response("platform_content_overrides", MockResponse(data=None))
        image_s, text_s = await repo.get_content_settings(1, "wordpress")
        assert image_s == {"style": "photo"}
        assert text_s == {"tone": "professional"}

    async def test_override_replaces_image_settings(
        self, repo: CategoriesRepository, mock_db: MockSupabaseClient, category_row: dict, override_row: dict
    ) -> None:
        mock_db.set_response("categories", MockResponse(data=category_row))
        mock_db.set_response("platform_content_overrides", MockResponse(data=override_row))
        image_s, text_s = await repo.get_content_settings(1, "wordpress")
        # Override has image_settings, so it replaces category's
        assert image_s == {"style": "illustration"}
        # Override has text_settings=None, so category's is inherited
        assert text_s == {"tone": "professional"}

    async def test_category_not_found_returns_empty(
        self, repo: CategoriesRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("categories", MockResponse(data=None))
        image_s, text_s = await repo.get_content_settings(999, "wordpress")
        assert image_s == {}
        assert text_s == {}


class TestUpsertOverride:
    async def test_upsert(self, repo: CategoriesRepository, mock_db: MockSupabaseClient, override_row: dict) -> None:
        mock_db.set_response("platform_content_overrides", MockResponse(data=[override_row]))
        result = await repo.upsert_override(
            PlatformContentOverrideCreate(
                category_id=1,
                platform_type="wordpress",
                image_settings={"style": "illustration"},
            )
        )
        assert isinstance(result, PlatformContentOverride)
