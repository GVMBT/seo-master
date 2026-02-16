"""Tests for services/cleanup.py — expired preview cleanup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from db.models import ArticlePreview, User
from services.cleanup import CleanupService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_preview(**overrides) -> ArticlePreview:
    defaults = {
        "id": 1,
        "user_id": 100,
        "project_id": 1,
        "category_id": 10,
        "status": "draft",
        "keyword": "test keyword",
        "tokens_charged": 320,
        "telegraph_path": None,
        "images": [],
        "created_at": datetime.now(tz=UTC),
        "expires_at": datetime.now(tz=UTC) - timedelta(hours=1),
    }
    defaults.update(overrides)
    return ArticlePreview(**defaults)


def _make_user(**overrides) -> User:
    defaults = {
        "id": 100,
        "username": "testuser",
        "first_name": "Test",
        "balance": 1500,
        "notify_balance": True,
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_service() -> CleanupService:
    return CleanupService(
        db=MagicMock(),
        http_client=MagicMock(),
        image_storage=MagicMock(),
        admin_ids=[999],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@patch("services.cleanup.UsersRepository")
async def test_cleanup_expired_drafts_happy(mock_users_cls: MagicMock) -> None:
    """Expired drafts are marked expired and tokens refunded."""
    svc = _make_service()
    preview = _make_preview(tokens_charged=200)
    mock_users_cls.return_value.get_by_id = AsyncMock(return_value=_make_user())

    svc._previews.get_expired_drafts = AsyncMock(return_value=[preview])
    svc._previews.atomic_mark_expired = AsyncMock(return_value=preview)
    svc._tokens.refund = AsyncMock(return_value=1200)
    svc._image_storage.cleanup_by_paths = AsyncMock(return_value=0)

    result = await svc.execute()

    assert result.expired_count == 1
    assert len(result.refunded) == 1
    assert result.refunded[0]["tokens_refunded"] == 200
    assert result.refunded[0]["notify_balance"] is True
    svc._tokens.refund.assert_called_once_with(
        100,
        200,
        reason="preview_expired",
        description="Expired preview: test keyword",
    )


async def test_cleanup_race_condition_skips() -> None:
    """If atomic_mark_expired returns None (already processed), skip it."""
    svc = _make_service()
    preview = _make_preview()

    svc._previews.get_expired_drafts = AsyncMock(return_value=[preview])
    svc._previews.atomic_mark_expired = AsyncMock(return_value=None)  # Race condition
    svc._tokens.refund = AsyncMock()

    result = await svc.execute()

    assert result.expired_count == 0
    svc._tokens.refund.assert_not_called()


async def test_cleanup_no_tokens_charged() -> None:
    """Preview with 0 tokens_charged: no refund needed."""
    svc = _make_service()
    preview = _make_preview(tokens_charged=0)

    svc._previews.get_expired_drafts = AsyncMock(return_value=[preview])
    svc._previews.atomic_mark_expired = AsyncMock(return_value=preview)
    svc._tokens.refund = AsyncMock()

    result = await svc.execute()

    assert result.expired_count == 1
    assert len(result.refunded) == 0
    svc._tokens.refund.assert_not_called()


@patch("services.cleanup.UsersRepository")
async def test_cleanup_with_images(mock_users_cls: MagicMock) -> None:
    """Preview with images: storage paths cleaned up."""
    svc = _make_service()
    preview = _make_preview(images=[{"storage_path": "100/1/img_1.webp"}, {"storage_path": "100/1/img_2.webp"}])
    mock_users_cls.return_value.get_by_id = AsyncMock(return_value=_make_user())

    svc._previews.get_expired_drafts = AsyncMock(return_value=[preview])
    svc._previews.atomic_mark_expired = AsyncMock(return_value=preview)
    svc._tokens.refund = AsyncMock(return_value=1500)
    svc._image_storage.cleanup_by_paths = AsyncMock(return_value=2)

    result = await svc.execute()

    assert result.images_deleted == 2
    svc._image_storage.cleanup_by_paths.assert_called_once_with(["100/1/img_1.webp", "100/1/img_2.webp"])


@patch("services.cleanup.UsersRepository")
@patch("services.cleanup.TelegraphClient")
async def test_cleanup_with_telegraph(mock_tg_cls: MagicMock, mock_users_cls: MagicMock) -> None:
    """Preview with telegraph_path triggers Telegraph delete."""
    svc = _make_service()
    preview = _make_preview(telegraph_path="test-page-01-01")
    mock_users_cls.return_value.get_by_id = AsyncMock(return_value=_make_user())

    svc._previews.get_expired_drafts = AsyncMock(return_value=[preview])
    svc._previews.atomic_mark_expired = AsyncMock(return_value=preview)
    svc._tokens.refund = AsyncMock(return_value=1500)

    mock_tg = MagicMock()
    mock_tg.delete_page = AsyncMock()
    mock_tg_cls.return_value = mock_tg

    result = await svc.execute()

    assert result.expired_count == 1
    mock_tg.delete_page.assert_called_once_with("test-page-01-01")


async def test_cleanup_empty() -> None:
    """No expired drafts: clean run."""
    svc = _make_service()
    svc._previews.get_expired_drafts = AsyncMock(return_value=[])

    result = await svc.execute()

    assert result.expired_count == 0
    assert result.refunded == []


@patch("services.cleanup.UsersRepository")
async def test_cleanup_error_handling(mock_users_cls: MagicMock) -> None:
    """Error on one preview doesn't stop processing others."""
    svc = _make_service()
    p1 = _make_preview(id=1)
    p2 = _make_preview(id=2, tokens_charged=100)
    mock_users_cls.return_value.get_by_id = AsyncMock(return_value=_make_user())

    svc._previews.get_expired_drafts = AsyncMock(return_value=[p1, p2])
    svc._previews.atomic_mark_expired = AsyncMock(side_effect=[Exception("db error"), p2])
    svc._tokens.refund = AsyncMock(return_value=1500)

    result = await svc.execute()

    assert result.expired_count == 1  # Only p2 processed


@patch("services.cleanup.PublicationsRepository")
async def test_cleanup_old_logs(mock_pubs_cls: MagicMock) -> None:
    """Old publication logs (>90 days) are deleted."""
    svc = _make_service()
    svc._previews.get_expired_drafts = AsyncMock(return_value=[])
    mock_pubs_cls.return_value.delete_old_logs = AsyncMock(return_value=2)

    result = await svc.execute()

    assert result.logs_deleted == 2
    mock_pubs_cls.return_value.delete_old_logs.assert_awaited_once()
