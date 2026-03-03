"""Tests for schedule error tracking in services/publish.py.

Covers:
- _disable_schedule: disables schedule + deletes QStash crons
- _disable_schedule without scheduler_service
- _make_token_refresh_cb: persists refreshed credentials via ConnectionsRepository
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from cryptography.fernet import Fernet
from pydantic import SecretStr

from cache.client import RedisClient
from db.models import PlatformSchedule, PlatformScheduleUpdate
from services.publish import PublishService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_schedule(**overrides: Any) -> PlatformSchedule:
    defaults: dict[str, Any] = {
        "id": 42,
        "category_id": 10,
        "platform_type": "wordpress",
        "connection_id": 5,
        "schedule_days": ["mon"],
        "schedule_times": ["09:00"],
        "posts_per_day": 1,
        "enabled": True,
        "status": "active",
        "qstash_schedule_ids": ["sch_1", "sch_2"],
        "last_post_at": None,
        "created_at": None,
    }
    defaults.update(overrides)
    return PlatformSchedule(**defaults)


def _make_service(
    scheduler_service: Any = "default",
    redis: Any | None = None,
) -> PublishService:
    """Build a PublishService with all deps mocked."""
    mock_scheduler: Any
    if scheduler_service == "default":
        mock_scheduler = MagicMock()
        mock_scheduler.delete_qstash_schedules = AsyncMock()
    else:
        mock_scheduler = scheduler_service

    mock_redis = redis or AsyncMock(spec=RedisClient)

    svc = PublishService(
        db=MagicMock(),
        redis=mock_redis,
        http_client=MagicMock(),
        ai_orchestrator=MagicMock(),
        image_storage=MagicMock(),
        admin_ids=[1],
        scheduler_service=cast(Any, mock_scheduler),
    )
    # Ensure _schedules.update is an AsyncMock
    svc._schedules.update = AsyncMock()  # type: ignore[method-assign]
    return svc


# ---------------------------------------------------------------------------
# TestPauseSchedulePlatformError
# ---------------------------------------------------------------------------


class TestPauseSchedulePlatformError:
    """Tests for PublishService._disable_schedule."""

    async def test_pause_disables_schedule_and_deletes_qstash(self) -> None:
        """Verify schedule set to error/disabled AND QStash crons deleted."""
        svc = _make_service()
        schedule = _make_schedule(qstash_schedule_ids=["sch_1", "sch_2"])

        await svc._disable_schedule(schedule, "publish_platform_errors_threshold", reason="Connection timeout")

        # QStash schedules must be deleted
        svc._scheduler_service.delete_qstash_schedules.assert_awaited_once_with(  # type: ignore[union-attr]
            ["sch_1", "sch_2"]
        )

        # Schedule must be updated to error + disabled + cleared IDs
        svc._schedules.update.assert_awaited_once()
        call_args = svc._schedules.update.call_args
        assert call_args[0][0] == 42  # schedule.id
        update_model = call_args[0][1]
        assert isinstance(update_model, PlatformScheduleUpdate)
        assert update_model.status == "error"
        assert update_model.enabled is False
        assert update_model.qstash_schedule_ids == []

    async def test_pause_without_scheduler_service(self) -> None:
        """When scheduler_service is None, skip QStash deletion but still update DB."""
        svc = _make_service(scheduler_service=None)
        schedule = _make_schedule(qstash_schedule_ids=["sch_1"])

        await svc._disable_schedule(schedule, "publish_platform_errors_threshold", reason="Platform error")

        # Schedule must still be updated even without scheduler
        svc._schedules.update.assert_awaited_once()
        call_args = svc._schedules.update.call_args
        assert call_args[0][0] == schedule.id
        update_model = call_args[0][1]
        assert isinstance(update_model, PlatformScheduleUpdate)
        assert update_model.status == "error"
        assert update_model.enabled is False
        assert update_model.qstash_schedule_ids == []

    async def test_pause_with_empty_qstash_ids(self) -> None:
        """Schedule without QStash IDs should not call delete_qstash_schedules."""
        svc = _make_service()
        schedule = _make_schedule(qstash_schedule_ids=[])

        await svc._disable_schedule(schedule, "publish_platform_errors_threshold", reason="Error")

        # delete_qstash_schedules should NOT be called (empty list is falsy)
        svc._scheduler_service.delete_qstash_schedules.assert_not_awaited()  # type: ignore[union-attr]

        # But DB update must still happen
        svc._schedules.update.assert_awaited_once()

    async def test_pause_logs_warning(self) -> None:
        """Verify that a warning is logged with schedule_id and reason."""
        svc = _make_service()
        schedule = _make_schedule()

        with patch("services.publish.log") as mock_log:
            await svc._disable_schedule(schedule, "publish_platform_errors_threshold", reason="test reason")
            mock_log.warning.assert_called_once_with(
                "publish_platform_errors_threshold",
                schedule_id=42,
                reason="test reason",
            )


# ---------------------------------------------------------------------------
# TestMakeTokenRefreshCb
# ---------------------------------------------------------------------------


class TestMakeTokenRefreshCb:
    """Tests for PublishService._make_token_refresh_cb."""

    @patch("services.publish.get_settings")
    @patch("services.publish.ConnectionsRepository")
    @patch("services.publish.CredentialManager")
    async def test_make_token_refresh_cb_calls_update_credentials(
        self,
        mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Callback should call ConnectionsRepository.update_credentials with connection_id and new_creds."""
        # Generate a real Fernet key for the mock
        real_fernet_key = Fernet.generate_key().decode()
        mock_settings_instance = MagicMock()
        mock_settings_instance.encryption_key = SecretStr(real_fernet_key)
        mock_settings.return_value = mock_settings_instance

        mock_repo_instance = MagicMock()
        mock_repo_instance.update_credentials = AsyncMock()
        mock_conn_cls.return_value = mock_repo_instance

        svc = _make_service()
        connection_id = 77
        cb = svc._make_token_refresh_cb(connection_id)

        old_creds = {"access_token": "old_token", "refresh_token": "old_refresh"}
        new_creds = {"access_token": "new_token", "refresh_token": "new_refresh"}

        await cb(old_creds, new_creds)

        # CredentialManager should be instantiated with the encryption key
        mock_cm_cls.assert_called_once_with(real_fernet_key)

        # ConnectionsRepository should be instantiated with db and credential manager
        mock_conn_cls.assert_called_once_with(svc._db, mock_cm_cls.return_value)

        # update_credentials should be called with connection_id and new credentials
        mock_repo_instance.update_credentials.assert_awaited_once_with(
            connection_id, new_creds
        )

    @patch("services.publish.get_settings")
    @patch("services.publish.ConnectionsRepository")
    @patch("services.publish.CredentialManager")
    async def test_token_refresh_cb_different_connection_ids(
        self,
        mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_settings: MagicMock,
    ) -> None:
        """Each callback is bound to a specific connection_id."""
        real_fernet_key = Fernet.generate_key().decode()
        mock_settings_instance = MagicMock()
        mock_settings_instance.encryption_key = SecretStr(real_fernet_key)
        mock_settings.return_value = mock_settings_instance

        mock_repo_instance = MagicMock()
        mock_repo_instance.update_credentials = AsyncMock()
        mock_conn_cls.return_value = mock_repo_instance

        svc = _make_service()

        cb_10 = svc._make_token_refresh_cb(10)
        cb_20 = svc._make_token_refresh_cb(20)

        await cb_10({}, {"token": "a"})
        await cb_20({}, {"token": "b"})

        # Each call should use its own connection_id
        calls = mock_repo_instance.update_credentials.await_args_list
        assert len(calls) == 2
        assert calls[0][0] == (10, {"token": "a"})
        assert calls[1][0] == (20, {"token": "b"})
