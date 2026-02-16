"""Tests for db/repositories/previews.py."""

import pytest

from db.models import ArticlePreview, ArticlePreviewCreate, ArticlePreviewUpdate
from db.repositories.previews import PreviewsRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def preview_row() -> dict:
    return {
        "id": 1,
        "user_id": 123456789,
        "project_id": 1,
        "category_id": 1,
        "connection_id": 1,
        "telegraph_url": "https://telegra.ph/test-article",
        "telegraph_path": "test-article",
        "title": "SEO Tips for 2026",
        "keyword": "seo tips",
        "word_count": 2000,
        "images_count": 4,
        "tokens_charged": 320,
        "regeneration_count": 0,
        "status": "draft",
        "content_html": "<h1>SEO Tips</h1><p>Content here...</p>",
        "images": [{"url": "https://example.com/img1.jpg", "width": 800, "height": 600}],
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires_at": "2026-01-02T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> PreviewsRepository:
    return PreviewsRepository(mock_db)  # type: ignore[arg-type]


class TestCreate:
    async def test_create(self, repo: PreviewsRepository, mock_db: MockSupabaseClient, preview_row: dict) -> None:
        mock_db.set_response("article_previews", MockResponse(data=[preview_row]))
        data = ArticlePreviewCreate(
            user_id=123456789,
            project_id=1,
            category_id=1,
            title="SEO Tips for 2026",
            keyword="seo tips",
        )
        preview = await repo.create(data)
        assert isinstance(preview, ArticlePreview)
        assert preview.title == "SEO Tips for 2026"


class TestGetById:
    async def test_found(self, repo: PreviewsRepository, mock_db: MockSupabaseClient, preview_row: dict) -> None:
        mock_db.set_response("article_previews", MockResponse(data=preview_row))
        preview = await repo.get_by_id(1)
        assert preview is not None
        assert preview.keyword == "seo tips"

    async def test_not_found(self, repo: PreviewsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("article_previews", MockResponse(data=None))
        assert await repo.get_by_id(999) is None


class TestGetActiveByUser:
    async def test_returns_drafts(
        self, repo: PreviewsRepository, mock_db: MockSupabaseClient, preview_row: dict
    ) -> None:
        mock_db.set_response("article_previews", MockResponse(data=[preview_row]))
        previews = await repo.get_active_by_user(123456789)
        assert len(previews) == 1
        assert previews[0].status == "draft"

    async def test_empty(self, repo: PreviewsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("article_previews", MockResponse(data=[]))
        assert await repo.get_active_by_user(999) == []


class TestUpdate:
    async def test_partial_update(
        self, repo: PreviewsRepository, mock_db: MockSupabaseClient, preview_row: dict
    ) -> None:
        updated = {**preview_row, "status": "published"}
        mock_db.set_response("article_previews", MockResponse(data=[updated]))
        preview = await repo.update(1, ArticlePreviewUpdate(status="published"))
        assert preview is not None
        assert preview.status == "published"

    async def test_empty_update_returns_current(
        self, repo: PreviewsRepository, mock_db: MockSupabaseClient, preview_row: dict
    ) -> None:
        mock_db.set_response("article_previews", MockResponse(data=preview_row))
        preview = await repo.update(1, ArticlePreviewUpdate())
        assert preview is not None


class TestGetExpiredDrafts:
    async def test_returns_expired_previews(
        self, repo: PreviewsRepository, mock_db: MockSupabaseClient, preview_row: dict
    ) -> None:
        mock_db.set_response("article_previews", MockResponse(data=[preview_row]))
        expired = await repo.get_expired_drafts()
        assert len(expired) == 1

    async def test_empty_when_none_expired(self, repo: PreviewsRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("article_previews", MockResponse(data=[]))
        assert await repo.get_expired_drafts() == []
