"""Tests for UsersService.delete_account — 152-FZ account deletion.

Covers: full pipeline (5 steps), partial failures, Redis cleanup, E11/E42.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import ArticlePreview, Project
from services.users import DeleteAccountResult, UsersService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_project(**overrides) -> Project:  # type: ignore[no-untyped-def]
    defaults = {
        "id": 1,
        "user_id": 123,
        "name": "Test",
        "company_name": "Co",
        "specialization": "SEO",
    }
    defaults.update(overrides)
    return Project(**defaults)


def _make_preview(**overrides) -> ArticlePreview:  # type: ignore[no-untyped-def]
    defaults = {
        "id": 10,
        "user_id": 123,
        "project_id": 1,
        "category_id": 5,
        "status": "draft",
        "tokens_charged": 320,
    }
    defaults.update(overrides)
    return ArticlePreview(**defaults)


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.delete = AsyncMock(return_value=1)
    redis.scan_keys = AsyncMock(return_value=[])
    return redis


@pytest.fixture
def mock_scheduler() -> MagicMock:
    svc = MagicMock()
    svc.cancel_schedules_for_project = AsyncMock()
    return svc


@pytest.fixture
def service(mock_db: MagicMock) -> UsersService:
    svc = UsersService.__new__(UsersService)
    svc._db = mock_db
    svc._users = AsyncMock()
    return svc


# ---------------------------------------------------------------------------
# Full successful deletion
# ---------------------------------------------------------------------------


class TestDeleteAccountSuccess:
    @patch("services.users.PreviewsRepository")
    @patch("services.users.ProjectsRepository")
    @patch("services.users.TokenService")
    async def test_full_deletion_pipeline(
        self,
        mock_token_cls: MagicMock,
        mock_projects_cls: MagicMock,
        mock_previews_cls: MagicMock,
        service: UsersService,
        mock_redis: MagicMock,
        mock_scheduler: MagicMock,
    ) -> None:
        """All 5 steps execute in order for a user with projects."""
        # Setup: user has 2 projects, one with active preview
        projects = [_make_project(id=1), _make_project(id=2)]
        mock_projects_cls.return_value.get_by_user = AsyncMock(return_value=projects)

        preview = _make_preview(project_id=1, tokens_charged=320)
        mock_previews_cls.return_value.get_active_drafts_by_project = AsyncMock(side_effect=[[preview], []])

        mock_token_svc = AsyncMock()
        mock_token_svc.refund_active_previews = AsyncMock(return_value=1)
        mock_token_cls.return_value = mock_token_svc

        service._users.anonymize_financial_records = AsyncMock(return_value=(5, 2))
        service._users.delete_user = AsyncMock(return_value=True)

        result = await service.delete_account(
            user_id=123,
            redis=mock_redis,
            scheduler_service=mock_scheduler,
            admin_ids=[],
        )

        assert result.success is True
        assert result.schedules_cancelled == 2  # both projects
        assert result.previews_refunded == 1
        assert result.expenses_anonymized == 5
        assert result.payments_anonymized == 2

        # Verify QStash cancelled for both projects (E11)
        assert mock_scheduler.cancel_schedules_for_project.await_count == 2

        # Verify user row deleted
        service._users.delete_user.assert_awaited_once_with(123)

    @patch("services.users.PreviewsRepository")
    @patch("services.users.ProjectsRepository")
    @patch("services.users.TokenService")
    async def test_no_projects_user(
        self,
        mock_token_cls: MagicMock,
        mock_projects_cls: MagicMock,
        mock_previews_cls: MagicMock,
        service: UsersService,
        mock_redis: MagicMock,
        mock_scheduler: MagicMock,
    ) -> None:
        """User with no projects: skip schedule/preview steps, still delete."""
        mock_projects_cls.return_value.get_by_user = AsyncMock(return_value=[])
        service._users.anonymize_financial_records = AsyncMock(return_value=(0, 0))
        service._users.delete_user = AsyncMock(return_value=True)

        result = await service.delete_account(
            user_id=123,
            redis=mock_redis,
            scheduler_service=mock_scheduler,
            admin_ids=[],
        )

        assert result.success is True
        assert result.schedules_cancelled == 0
        assert result.previews_refunded == 0
        mock_scheduler.cancel_schedules_for_project.assert_not_awaited()
        service._users.delete_user.assert_awaited_once_with(123)


# ---------------------------------------------------------------------------
# Partial failures
# ---------------------------------------------------------------------------


class TestDeleteAccountPartialFailure:
    @patch("services.users.PreviewsRepository")
    @patch("services.users.ProjectsRepository")
    @patch("services.users.TokenService")
    async def test_schedule_cancel_error_continues(
        self,
        mock_token_cls: MagicMock,
        mock_projects_cls: MagicMock,
        mock_previews_cls: MagicMock,
        service: UsersService,
        mock_redis: MagicMock,
        mock_scheduler: MagicMock,
    ) -> None:
        """If QStash cancel fails for one project, deletion continues."""
        projects = [_make_project(id=1), _make_project(id=2)]
        mock_projects_cls.return_value.get_by_user = AsyncMock(return_value=projects)

        # First project fails, second succeeds
        mock_scheduler.cancel_schedules_for_project = AsyncMock(side_effect=[Exception("QStash down"), None])
        mock_previews_cls.return_value.get_active_drafts_by_project = AsyncMock(return_value=[])
        mock_token_cls.return_value = AsyncMock()
        service._users.anonymize_financial_records = AsyncMock(return_value=(0, 0))
        service._users.delete_user = AsyncMock(return_value=True)

        result = await service.delete_account(
            user_id=123,
            redis=mock_redis,
            scheduler_service=mock_scheduler,
            admin_ids=[],
        )

        assert result.success is True
        assert "schedule_cancel_project_1" in result.errors
        assert result.schedules_cancelled == 1  # only project 2 succeeded

    @patch("services.users.PreviewsRepository")
    @patch("services.users.ProjectsRepository")
    @patch("services.users.TokenService")
    async def test_user_delete_failure(
        self,
        mock_token_cls: MagicMock,
        mock_projects_cls: MagicMock,
        mock_previews_cls: MagicMock,
        service: UsersService,
        mock_redis: MagicMock,
        mock_scheduler: MagicMock,
    ) -> None:
        """If user row deletion fails, result.success is False."""
        mock_projects_cls.return_value.get_by_user = AsyncMock(return_value=[])
        service._users.anonymize_financial_records = AsyncMock(return_value=(0, 0))
        service._users.delete_user = AsyncMock(return_value=False)

        result = await service.delete_account(
            user_id=123,
            redis=mock_redis,
            scheduler_service=mock_scheduler,
            admin_ids=[],
        )

        assert result.success is False
        assert "user_not_found" in result.errors

    @patch("services.users.PreviewsRepository")
    @patch("services.users.ProjectsRepository")
    @patch("services.users.TokenService")
    async def test_user_delete_exception(
        self,
        mock_token_cls: MagicMock,
        mock_projects_cls: MagicMock,
        mock_previews_cls: MagicMock,
        service: UsersService,
        mock_redis: MagicMock,
        mock_scheduler: MagicMock,
    ) -> None:
        """If user row deletion raises, result.success is False."""
        mock_projects_cls.return_value.get_by_user = AsyncMock(return_value=[])
        service._users.anonymize_financial_records = AsyncMock(return_value=(0, 0))
        service._users.delete_user = AsyncMock(side_effect=Exception("DB error"))

        result = await service.delete_account(
            user_id=123,
            redis=mock_redis,
            scheduler_service=mock_scheduler,
            admin_ids=[],
        )

        assert result.success is False
        assert "delete_user_row" in result.errors


# ---------------------------------------------------------------------------
# Redis cleanup
# ---------------------------------------------------------------------------


class TestRedisCleanup:
    async def test_cleanup_known_keys(self, mock_redis: MagicMock) -> None:
        """Known keys (user cache, pipeline state) are deleted."""
        deleted = await UsersService._cleanup_redis(123, mock_redis)

        # 2 known keys + 0 scanned keys
        assert deleted >= 2
        mock_redis.delete.assert_any_call("user:123")
        mock_redis.delete.assert_any_call("pipeline:123:state")

    async def test_cleanup_scanned_keys(self, mock_redis: MagicMock) -> None:
        """Scan finds FSM keys and deletes them."""
        mock_redis.scan_keys = AsyncMock(
            side_effect=[
                ["fsm:123:state", "fsm:123:data"],  # fsm pattern
                ["throttle:123:generate"],  # throttle pattern
                [],  # rate pattern
            ]
        )
        # Mock returns count of deleted keys per call
        mock_redis.delete = AsyncMock(side_effect=[1, 1, 2, 1])

        deleted = await UsersService._cleanup_redis(123, mock_redis)

        # 2 known keys (1 each) + 2 fsm keys (1 batch=2) + 1 throttle (1) = 5
        assert deleted == 5

    async def test_cleanup_redis_error_ignored(self, mock_redis: MagicMock) -> None:
        """Redis errors during cleanup are logged but not raised."""
        mock_redis.delete = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.scan_keys = AsyncMock(side_effect=ConnectionError("Redis down"))

        # Should not raise
        deleted = await UsersService._cleanup_redis(123, mock_redis)
        assert deleted == 0


# ---------------------------------------------------------------------------
# DeleteAccountResult dataclass
# ---------------------------------------------------------------------------


class TestDeleteAccountResult:
    def test_default_values(self) -> None:
        result = DeleteAccountResult()
        assert result.success is False
        assert result.schedules_cancelled == 0
        assert result.previews_refunded == 0
        assert result.expenses_anonymized == 0
        assert result.payments_anonymized == 0
        assert result.redis_keys_deleted == 0
        assert result.errors == []
