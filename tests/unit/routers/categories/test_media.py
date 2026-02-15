"""Tests for routers/categories/media.py — media gallery (F23)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, Project, User
from routers.categories.media import (
    _MAX_MEDIA,
    _append_media,
    cb_media_clear,
    cb_media_start,
    cb_media_upload_prompt,
    on_document_received,
    on_photo_received,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def category_with_media(project: Project) -> Category:
    return Category(
        id=10,
        project_id=project.id,
        name="Test Category",
        media=[{"file_id": "abc", "type": "photo", "file_size": 1000, "uploaded_at": "2026-01-01"}],
    )


@pytest.fixture
def category_no_media(project: Project) -> Category:
    return Category(id=10, project_id=project.id, name="Test Category", media=[])


# ---------------------------------------------------------------------------
# cb_media_start
# ---------------------------------------------------------------------------


class TestCbMediaStart:
    @patch("routers.categories.media.ProjectsRepository")
    @patch("routers.categories.media.CategoriesRepository")
    async def test_shows_media_count(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        project: Project,
        category_with_media: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:media"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_media)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_media_start(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "1 / 20" in text

    @patch("routers.categories.media.ProjectsRepository")
    @patch("routers.categories.media.CategoriesRepository")
    async def test_empty_media(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        project: Project,
        category_no_media: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "category:10:media"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_media)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_media_start(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "0 / 20" in text


# ---------------------------------------------------------------------------
# cb_media_upload_prompt
# ---------------------------------------------------------------------------


class TestCbMediaUploadPrompt:
    @patch("routers.categories.media.ProjectsRepository")
    @patch("routers.categories.media.CategoriesRepository")
    async def test_sets_awaiting_state(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_no_media: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "media:cat:10:upload"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_no_media)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)

        await cb_media_upload_prompt(mock_callback, mock_state, user, mock_db)

        mock_state.update_data.assert_called_with(awaiting_media_cat=10)


# ---------------------------------------------------------------------------
# on_photo_received
# ---------------------------------------------------------------------------


class TestOnPhotoReceived:
    async def test_ignores_when_not_awaiting(self, mock_state: AsyncMock, user: User, mock_db: MagicMock) -> None:
        mock_state.get_data = AsyncMock(return_value={})
        msg = MagicMock()
        msg.photo = [MagicMock(file_id="xyz", file_size=500)]

        await on_photo_received(msg, mock_state, user, mock_db)

        # No answer, no state change — handler returned early
        msg.answer.assert_not_called() if hasattr(msg.answer, "assert_not_called") else None

    @patch("routers.categories.media._append_media")
    async def test_calls_append_when_awaiting(
        self, mock_append: AsyncMock, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"awaiting_media_cat": 10})
        photo = MagicMock(file_id="photo123", file_size=1024)
        msg = MagicMock()
        msg.photo = [MagicMock(file_id="small", file_size=100), photo]  # last = largest

        await on_photo_received(msg, mock_state, user, mock_db)

        mock_append.assert_called_once()


# ---------------------------------------------------------------------------
# on_document_received
# ---------------------------------------------------------------------------


class TestOnDocumentReceived:
    async def test_ignores_when_not_awaiting(self, mock_state: AsyncMock, user: User, mock_db: MagicMock) -> None:
        mock_state.get_data = AsyncMock(return_value={})
        msg = MagicMock()
        msg.document = MagicMock(file_id="doc1", file_size=2000)

        await on_document_received(msg, mock_state, user, mock_db)

    @patch("routers.categories.media._append_media")
    async def test_calls_append_when_awaiting(
        self, mock_append: AsyncMock, mock_state: AsyncMock, user: User, mock_db: MagicMock
    ) -> None:
        mock_state.get_data = AsyncMock(return_value={"awaiting_media_cat": 10})
        msg = MagicMock()
        msg.document = MagicMock(file_id="doc123", file_size=5000)

        await on_document_received(msg, mock_state, user, mock_db)

        mock_append.assert_called_once()


# ---------------------------------------------------------------------------
# _append_media
# ---------------------------------------------------------------------------


class TestAppendMedia:
    @patch("routers.categories.media.CategoriesRepository")
    async def test_appends_and_saves(
        self, mock_cat_repo_cls: MagicMock, mock_state: AsyncMock, mock_db: MagicMock
    ) -> None:
        cat = Category(id=10, project_id=1, name="Test", media=[])
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=cat)
        mock_cat_repo_cls.return_value.update_media = AsyncMock()
        msg = MagicMock()
        msg.answer = AsyncMock()

        await _append_media(msg, mock_state, mock_db, 10, "file123", "photo", 1024)

        mock_cat_repo_cls.return_value.update_media.assert_called_once()
        saved_media = mock_cat_repo_cls.return_value.update_media.call_args[0][1]
        assert len(saved_media) == 1
        assert saved_media[0]["file_id"] == "file123"

    @patch("routers.categories.media.CategoriesRepository")
    async def test_max_media_limit(
        self, mock_cat_repo_cls: MagicMock, mock_state: AsyncMock, mock_db: MagicMock
    ) -> None:
        media = [{"file_id": f"f{i}", "type": "photo", "file_size": 100, "uploaded_at": ""} for i in range(_MAX_MEDIA)]
        cat = Category(id=10, project_id=1, name="Test", media=media)
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=cat)
        msg = MagicMock()
        msg.answer = AsyncMock()

        await _append_media(msg, mock_state, mock_db, 10, "overflow", "photo", 100)

        text = msg.answer.call_args[0][0]
        assert "лимит" in text.lower()

    @patch("routers.categories.media.CategoriesRepository")
    async def test_category_not_found(
        self, mock_cat_repo_cls: MagicMock, mock_state: AsyncMock, mock_db: MagicMock
    ) -> None:
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=None)
        msg = MagicMock()
        msg.answer = AsyncMock()

        await _append_media(msg, mock_state, mock_db, 999, "file1", "photo", 100)

        msg.answer.assert_called_with("Категория не найдена.")


# ---------------------------------------------------------------------------
# cb_media_clear
# ---------------------------------------------------------------------------


class TestCbMediaClear:
    @patch("routers.categories.media.ProjectsRepository")
    @patch("routers.categories.media.CategoriesRepository")
    async def test_clears_media(
        self,
        mock_cat_repo_cls: MagicMock,
        mock_proj_repo_cls: MagicMock,
        mock_callback: MagicMock,
        mock_state: AsyncMock,
        user: User,
        project: Project,
        category_with_media: Category,
        mock_db: MagicMock,
    ) -> None:
        mock_callback.data = "media:cat:10:clear"
        mock_cat_repo_cls.return_value.get_by_id = AsyncMock(return_value=category_with_media)
        mock_proj_repo_cls.return_value.get_by_id = AsyncMock(return_value=project)
        mock_cat_repo_cls.return_value.update_media = AsyncMock()

        await cb_media_clear(mock_callback, mock_state, user, mock_db)

        mock_cat_repo_cls.return_value.update_media.assert_called_with(10, [])
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "0 / 20" in text
