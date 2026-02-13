"""Tests for services/scheduler.py — QStash schedule management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import PlatformSchedule
from services.scheduler import SchedulerService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_schedule(**overrides) -> PlatformSchedule:
    """Create a test PlatformSchedule."""
    defaults = {
        "id": 1,
        "category_id": 10,
        "platform_type": "wordpress",
        "connection_id": 5,
        "schedule_days": ["mon", "wed", "fri"],
        "schedule_times": ["09:00", "15:00"],
        "posts_per_day": 2,
        "enabled": False,
        "status": "active",
        "qstash_schedule_ids": [],
        "last_post_at": None,
        "created_at": None,
    }
    defaults.update(overrides)
    return PlatformSchedule(**defaults)


def _make_service(mock_db=None) -> tuple[SchedulerService, MagicMock]:
    """Create SchedulerService with mocked QStash client."""
    db = mock_db or MagicMock()
    svc = SchedulerService(db=db, qstash_token="test_token", base_url="https://example.com")
    mock_qstash = MagicMock()
    svc._qstash = mock_qstash
    return svc, mock_qstash


# ---------------------------------------------------------------------------
# create_qstash_schedules
# ---------------------------------------------------------------------------


async def test_create_qstash_schedules_creates_per_time_slot() -> None:
    """One QStash schedule created per time slot."""
    svc, mock_q = _make_service()
    mock_q.schedule.create.return_value = MagicMock(schedule_id="qs_1")

    schedule = _make_schedule(schedule_times=["09:00", "15:00"])
    ids = await svc.create_qstash_schedules(schedule, user_id=1, project_id=1, timezone="Europe/Moscow")

    assert len(ids) == 2
    assert ids == ["qs_1", "qs_1"]
    assert mock_q.schedule.create.call_count == 2


async def test_create_qstash_cron_format() -> None:
    """Cron string includes timezone and day schedule."""
    svc, mock_q = _make_service()
    mock_q.schedule.create.return_value = MagicMock(schedule_id="qs_1")

    schedule = _make_schedule(schedule_days=["mon", "fri"], schedule_times=["14:30"])
    await svc.create_qstash_schedules(schedule, user_id=1, project_id=1, timezone="Europe/Moscow")

    call_args = mock_q.schedule.create.call_args
    assert call_args.kwargs.get("cron", call_args[1].get("cron", "")) == "CRON_TZ=Europe/Moscow 30 14 * * mon,fri"


async def test_create_qstash_schedules_failure_raises() -> None:
    """QStash API failure raises ScheduleError."""
    from bot.exceptions import ScheduleError

    svc, mock_q = _make_service()
    mock_q.schedule.create.side_effect = Exception("API error")

    schedule = _make_schedule(schedule_times=["09:00"])
    with pytest.raises(ScheduleError):
        await svc.create_qstash_schedules(schedule, user_id=1, project_id=1, timezone="UTC")


# ---------------------------------------------------------------------------
# delete_qstash_schedules
# ---------------------------------------------------------------------------


async def test_delete_qstash_schedules_happy() -> None:
    """All schedule IDs are deleted."""
    svc, mock_q = _make_service()
    await svc.delete_qstash_schedules(["qs_1", "qs_2"])
    assert mock_q.schedule.delete.call_count == 2


async def test_delete_qstash_ignores_404() -> None:
    """404 on delete is ignored (already deleted)."""
    svc, mock_q = _make_service()
    mock_q.schedule.delete.side_effect = Exception("404")

    # Should not raise
    await svc.delete_qstash_schedules(["qs_1"])


# ---------------------------------------------------------------------------
# toggle_schedule
# ---------------------------------------------------------------------------


@patch("services.scheduler.SchedulesRepository")
async def test_toggle_enable(mock_repo_cls: MagicMock) -> None:
    """Enabling a disabled schedule creates QStash and updates DB."""
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=_make_schedule(enabled=False))
    mock_repo.update = AsyncMock(return_value=_make_schedule(enabled=True, qstash_schedule_ids=["qs_1"]))
    mock_repo_cls.return_value = mock_repo

    svc, mock_q = _make_service()
    svc._schedules = mock_repo
    mock_q.schedule.create.return_value = MagicMock(schedule_id="qs_1")

    result = await svc.toggle_schedule(1, enabled=True, user_id=1, project_id=1, timezone="UTC")

    assert result is not None
    mock_repo.update.assert_called_once()


@patch("services.scheduler.SchedulesRepository")
async def test_toggle_disable(mock_repo_cls: MagicMock) -> None:
    """Disabling an enabled schedule deletes QStash and updates DB."""
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(
        return_value=_make_schedule(enabled=True, qstash_schedule_ids=["qs_1"])
    )
    mock_repo.update = AsyncMock(return_value=_make_schedule(enabled=False))
    mock_repo_cls.return_value = mock_repo

    svc, mock_q = _make_service()
    svc._schedules = mock_repo

    result = await svc.toggle_schedule(1, enabled=False, user_id=1, project_id=1, timezone="UTC")

    assert result is not None
    mock_q.schedule.delete.assert_called_once_with("qs_1")


# ---------------------------------------------------------------------------
# cancel_schedules_for_category / project
# ---------------------------------------------------------------------------


async def test_cancel_for_category() -> None:
    """Cancels all QStash schedules for a category (E24)."""
    svc, mock_q = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(
        return_value=[_make_schedule(id=1, qstash_schedule_ids=["qs_a", "qs_b"])]
    )
    mock_repo.update = AsyncMock(return_value=None)
    svc._schedules = mock_repo

    await svc.cancel_schedules_for_category(10)

    assert mock_q.schedule.delete.call_count == 2
    mock_repo.update.assert_called_once()


@patch("services.scheduler.CategoriesRepository")
async def test_cancel_for_project(mock_cat_cls: MagicMock) -> None:
    """Cancels all QStash schedules for a project (E11)."""

    mock_cat = MagicMock()
    mock_cat.get_by_project = AsyncMock(return_value=[MagicMock(id=10)])
    mock_cat_cls.return_value = mock_cat

    svc, mock_q = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_project = AsyncMock(
        return_value=[_make_schedule(qstash_schedule_ids=["qs_x"])]
    )
    mock_repo.update = AsyncMock(return_value=None)
    svc._schedules = mock_repo

    await svc.cancel_schedules_for_project(1)

    mock_q.schedule.delete.assert_called_once_with("qs_x")


# ---------------------------------------------------------------------------
# estimate_weekly_cost
# ---------------------------------------------------------------------------


def test_estimate_weekly_cost_wordpress() -> None:
    """WordPress uses article cost (default ~320 per post)."""
    cost = SchedulerService.estimate_weekly_cost(days=3, posts_per_day=1, platform_type="wordpress")
    assert cost == 3 * 320  # 3 days * 1 post * 320 tokens


def test_estimate_weekly_cost_telegram() -> None:
    """Non-WP uses social post cost (default ~40 per post)."""
    cost = SchedulerService.estimate_weekly_cost(days=7, posts_per_day=2, platform_type="telegram")
    assert cost == 7 * 2 * 40  # 7 days * 2 posts * 40 tokens


# ---------------------------------------------------------------------------
# create_schedule
# ---------------------------------------------------------------------------


async def test_create_schedule_full_flow() -> None:
    """create_schedule creates DB row + QStash + updates with IDs."""
    svc, mock_q = _make_service()
    mock_q.schedule.create.return_value = MagicMock(schedule_id="qs_new")

    mock_repo = MagicMock()
    mock_repo.create = AsyncMock(return_value=_make_schedule(id=42, schedule_times=["10:00"]))
    mock_repo.update = AsyncMock(return_value=_make_schedule(id=42, enabled=True, qstash_schedule_ids=["qs_new"]))
    svc._schedules = mock_repo

    result = await svc.create_schedule(
        category_id=10, connection_id=5, platform_type="wordpress",
        days=["mon"], times=["10:00"], posts_per_day=1,
        user_id=1, project_id=1, timezone="UTC",
    )

    assert result.enabled is True
    mock_repo.create.assert_called_once()
    mock_repo.update.assert_called_once()


# ---------------------------------------------------------------------------
# delete_schedule
# ---------------------------------------------------------------------------


async def test_delete_schedule_cancels_qstash() -> None:
    """delete_schedule cancels QStash before DB delete."""
    svc, mock_q = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(
        return_value=_make_schedule(qstash_schedule_ids=["qs_1"])
    )
    mock_repo.delete = AsyncMock(return_value=True)
    svc._schedules = mock_repo

    result = await svc.delete_schedule(1)
    assert result is True
    mock_q.schedule.delete.assert_called_once()


async def test_delete_schedule_not_found() -> None:
    """delete_schedule returns False for missing schedule."""
    svc, _ = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_id = AsyncMock(return_value=None)
    svc._schedules = mock_repo

    result = await svc.delete_schedule(999)
    assert result is False
