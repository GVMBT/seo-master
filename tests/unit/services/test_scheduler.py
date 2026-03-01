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
    # P0-1: numeric DOW per API_CONTRACTS §1.8
    assert call_args.kwargs.get("cron", call_args[1].get("cron", "")) == "CRON_TZ=Europe/Moscow 30 14 * * 1,5"


async def test_create_qstash_schedules_failure_raises() -> None:
    """QStash API failure raises ScheduleError."""
    from bot.exceptions import ScheduleError

    svc, mock_q = _make_service()
    mock_q.schedule.create.side_effect = Exception("API error")

    schedule = _make_schedule(schedule_times=["09:00"])
    with pytest.raises(ScheduleError):
        await svc.create_qstash_schedules(schedule, user_id=1, project_id=1, timezone="UTC")


async def test_create_qstash_body_contains_stable_idempotency_key() -> None:
    """QStash body idempotency_key is pub_{schedule_id}_{time_slot} (not UUID)."""
    import json

    svc, mock_q = _make_service()
    mock_q.schedule.create.return_value = MagicMock(schedule_id="qs_1")

    schedule = _make_schedule(id=42, schedule_times=["14:30"])
    await svc.create_qstash_schedules(schedule, user_id=1, project_id=1, timezone="UTC")

    body_str = mock_q.schedule.create.call_args.kwargs.get("body", mock_q.schedule.create.call_args[1].get("body", ""))
    body = json.loads(body_str)
    assert body["idempotency_key"] == "pub_42_14:30"


async def test_create_qstash_partial_failure_cleans_up() -> None:
    """Partial failure cleans up already-created schedules."""
    from bot.exceptions import ScheduleError

    svc, mock_q = _make_service()
    # First call succeeds, second fails
    mock_q.schedule.create.side_effect = [
        MagicMock(schedule_id="qs_1"),
        Exception("API error"),
    ]

    schedule = _make_schedule(schedule_times=["09:00", "15:00"])
    with pytest.raises(ScheduleError):
        await svc.create_qstash_schedules(schedule, user_id=1, project_id=1, timezone="UTC")

    # Verify cleanup of the first schedule
    mock_q.schedule.delete.assert_called_once_with("qs_1")


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
    mock_repo.get_by_id = AsyncMock(return_value=_make_schedule(enabled=True, qstash_schedule_ids=["qs_1"]))
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
    mock_repo.get_by_category = AsyncMock(return_value=[_make_schedule(id=1, qstash_schedule_ids=["qs_a", "qs_b"])])
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
    mock_repo.get_by_project = AsyncMock(return_value=[_make_schedule(qstash_schedule_ids=["qs_x"])])
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
    """Non-WP uses social post cost (text only, no images = 10 per post)."""
    cost = SchedulerService.estimate_weekly_cost(days=7, posts_per_day=2, platform_type="telegram")
    assert cost == 7 * 2 * 10  # 7 days * 2 posts * 10 tokens (no images in auto-publish)


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
        category_id=10,
        connection_id=5,
        platform_type="wordpress",
        days=["mon"],
        times=["10:00"],
        posts_per_day=1,
        user_id=1,
        project_id=1,
        timezone="UTC",
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
    mock_repo.get_by_id = AsyncMock(return_value=_make_schedule(qstash_schedule_ids=["qs_1"]))
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


# ---------------------------------------------------------------------------
# cancel_schedules_for_connection
# ---------------------------------------------------------------------------


async def test_cancel_for_connection() -> None:
    """Cancels all QStash schedules for a connection."""
    svc, mock_q = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_connection = AsyncMock(
        return_value=[
            _make_schedule(id=1, qstash_schedule_ids=["qs_a"]),
            _make_schedule(id=2, qstash_schedule_ids=["qs_b", "qs_c"]),
        ]
    )
    mock_repo.update = AsyncMock(return_value=None)
    svc._schedules = mock_repo

    await svc.cancel_schedules_for_connection(5)

    assert mock_q.schedule.delete.call_count == 3
    assert mock_repo.update.call_count == 2


async def test_cancel_for_connection_empty() -> None:
    """No schedules for connection — no QStash calls."""
    svc, mock_q = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_connection = AsyncMock(return_value=[])
    svc._schedules = mock_repo

    await svc.cancel_schedules_for_connection(999)

    mock_q.schedule.delete.assert_not_called()


# ---------------------------------------------------------------------------
# H23 Phase 4: verify_category_ownership
# ---------------------------------------------------------------------------


@patch("services.scheduler.ProjectsRepository")
@patch("services.scheduler.CategoriesRepository")
async def test_verify_ownership_happy(mock_cat_cls: MagicMock, mock_proj_cls: MagicMock) -> None:
    """Returns SchedulerContext when category owned by user."""
    from db.models import Category, Project
    from services.scheduler import SchedulerContext

    cat = Category(id=10, project_id=1, name="C")
    proj = Project(id=1, user_id=42, name="P", company_name="X", specialization="SEO")
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=proj)

    svc, _ = _make_service()
    ctx = await svc.verify_category_ownership(10, 42)

    assert ctx is not None
    assert isinstance(ctx, SchedulerContext)
    assert ctx.category.id == 10
    assert ctx.project.id == 1


@patch("services.scheduler.ProjectsRepository")
@patch("services.scheduler.CategoriesRepository")
async def test_verify_ownership_wrong_user(mock_cat_cls: MagicMock, mock_proj_cls: MagicMock) -> None:
    """Returns None when project belongs to another user."""
    from db.models import Category, Project

    cat = Category(id=10, project_id=1, name="C")
    proj = Project(id=1, user_id=999, name="P", company_name="X", specialization="SEO")
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=proj)

    svc, _ = _make_service()
    ctx = await svc.verify_category_ownership(10, 42)
    assert ctx is None


@patch("services.scheduler.CategoriesRepository")
async def test_verify_ownership_no_category(mock_cat_cls: MagicMock) -> None:
    """Returns None when category does not exist."""
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=None)

    svc, _ = _make_service()
    ctx = await svc.verify_category_ownership(999, 42)
    assert ctx is None


# ---------------------------------------------------------------------------
# H23 Phase 4: _filter_social
# ---------------------------------------------------------------------------


def test_filter_social_static() -> None:
    """_filter_social filters active social connections."""
    from db.models import PlatformConnection

    conns = [
        PlatformConnection(
            id=1,
            project_id=1,
            platform_type="wordpress",
            identifier="wp",
            credentials={},
            status="active",
        ),
        PlatformConnection(
            id=2,
            project_id=1,
            platform_type="telegram",
            identifier="tg",
            credentials={},
            status="active",
        ),
        PlatformConnection(
            id=3,
            project_id=1,
            platform_type="vk",
            identifier="vk",
            credentials={},
            status="error",
        ),
    ]
    result = SchedulerService._filter_social(conns)
    assert len(result) == 1
    assert result[0].platform_type == "telegram"


# ---------------------------------------------------------------------------
# H23 Phase 4: get_category_schedules_map
# ---------------------------------------------------------------------------


async def test_get_category_schedules_map() -> None:
    """Returns dict keyed by connection_id."""
    svc, _ = _make_service()
    s1 = _make_schedule(id=1, connection_id=5)
    s2 = _make_schedule(id=2, connection_id=20)
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[s1, s2])
    svc._schedules = mock_repo

    result = await svc.get_category_schedules_map(10)
    assert result == {5: s1, 20: s2}


async def test_get_category_schedules_map_empty() -> None:
    """Empty list returns empty dict."""
    svc, _ = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[])
    svc._schedules = mock_repo

    result = await svc.get_category_schedules_map(10)
    assert result == {}


# ---------------------------------------------------------------------------
# H23 Phase 4: apply_schedule
# ---------------------------------------------------------------------------


@patch("services.scheduler.ConnectionsRepository")
@patch("services.scheduler.CredentialManager")
@patch("services.scheduler.ProjectsRepository")
@patch("services.scheduler.CategoriesRepository")
async def test_apply_schedule_happy(
    mock_cat_cls: MagicMock,
    mock_proj_cls: MagicMock,
    mock_cm_cls: MagicMock,
    mock_conn_cls: MagicMock,
) -> None:
    """apply_schedule verifies ownership, deletes existing, creates new."""
    from db.models import Category, PlatformConnection, Project
    from services.scheduler import ApplyScheduleResult

    cat = Category(id=10, project_id=1, name="C")
    proj = Project(id=1, user_id=42, name="P", company_name="X", specialization="SEO", timezone="UTC")
    conn = PlatformConnection(
        id=5,
        project_id=1,
        platform_type="wordpress",
        identifier="wp",
        credentials={},
        status="active",
    )

    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=proj)
    mock_conn_cls.return_value.get_by_id = AsyncMock(return_value=conn)

    svc, mock_q = _make_service()
    mock_q.schedule.create.return_value = MagicMock(schedule_id="qs_1")

    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[])
    mock_repo.create = AsyncMock(return_value=_make_schedule(id=99, schedule_times=["10:00"]))
    mock_repo.update = AsyncMock(return_value=_make_schedule(id=99, enabled=True))
    svc._schedules = mock_repo

    result = await svc.apply_schedule(10, 5, 42, ["mon"], ["10:00"], 1)

    assert result is not None
    assert isinstance(result, ApplyScheduleResult)
    assert result.connection.id == 5
    assert result.weekly_cost > 0


@patch("services.scheduler.ProjectsRepository")
@patch("services.scheduler.CategoriesRepository")
async def test_apply_schedule_ownership_fail(mock_cat_cls: MagicMock, mock_proj_cls: MagicMock) -> None:
    """apply_schedule returns None when ownership check fails."""
    from db.models import Category, Project

    cat = Category(id=10, project_id=1, name="C")
    proj = Project(id=1, user_id=999, name="P", company_name="X", specialization="SEO")
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=proj)

    svc, _ = _make_service()
    result = await svc.apply_schedule(10, 5, 42, ["mon"], ["10:00"], 1)
    assert result is None


# ---------------------------------------------------------------------------
# H23 Phase 4: disable_connection_schedule
# ---------------------------------------------------------------------------


@patch("services.scheduler.ProjectsRepository")
@patch("services.scheduler.CategoriesRepository")
async def test_disable_connection_schedule_happy(mock_cat_cls: MagicMock, mock_proj_cls: MagicMock) -> None:
    """Disables schedule for owned category + connection."""
    from db.models import Category, Project

    cat = Category(id=10, project_id=1, name="C")
    proj = Project(id=1, user_id=42, name="P", company_name="X", specialization="SEO")
    mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=cat)
    mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=proj)

    svc, mock_q = _make_service()
    existing = _make_schedule(id=7, connection_id=5, qstash_schedule_ids=["qs_1"])
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[existing])
    mock_repo.get_by_id = AsyncMock(return_value=existing)
    mock_repo.delete = AsyncMock(return_value=True)
    svc._schedules = mock_repo

    result = await svc.disable_connection_schedule(10, 5, 42)
    assert result is True
    mock_q.schedule.delete.assert_called_once_with("qs_1")


# ---------------------------------------------------------------------------
# H23 Phase 4: has_active_schedule
# ---------------------------------------------------------------------------


async def test_has_active_schedule_true() -> None:
    svc, _ = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[_make_schedule(connection_id=5, enabled=True)])
    svc._schedules = mock_repo

    assert await svc.has_active_schedule(10, 5) is True


async def test_has_active_schedule_false() -> None:
    svc, _ = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[_make_schedule(connection_id=5, enabled=False)])
    svc._schedules = mock_repo

    assert await svc.has_active_schedule(10, 5) is False


async def test_has_active_schedule_different_connection() -> None:
    svc, _ = _make_service()
    mock_repo = MagicMock()
    mock_repo.get_by_category = AsyncMock(return_value=[_make_schedule(connection_id=99, enabled=True)])
    svc._schedules = mock_repo

    assert await svc.has_active_schedule(10, 5) is False
