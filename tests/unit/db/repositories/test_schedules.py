"""Tests for db/repositories/schedules.py."""

import pytest

from db.models import PlatformSchedule, PlatformScheduleCreate, PlatformScheduleUpdate
from db.repositories.schedules import SchedulesRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def schedule_row() -> dict:
    return {
        "id": 1,
        "category_id": 1,
        "platform_type": "wordpress",
        "connection_id": 1,
        "schedule_days": ["mon", "wed", "fri"],
        "schedule_times": ["10:00", "14:00"],
        "posts_per_day": 2,
        "enabled": True,
        "qstash_schedule_ids": ["sched_abc123"],
        "last_post_at": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> SchedulesRepository:
    return SchedulesRepository(mock_db)  # type: ignore[arg-type]


class TestGetById:
    async def test_found(self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=schedule_row))
        sched = await repo.get_by_id(1)
        assert sched is not None
        assert isinstance(sched, PlatformSchedule)
        assert sched.posts_per_day == 2

    async def test_not_found(self, repo: SchedulesRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=None))
        assert await repo.get_by_id(999) is None


class TestGetByCategory:
    async def test_returns_list(
        self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict
    ) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=[schedule_row]))
        scheds = await repo.get_by_category(1)
        assert len(scheds) == 1


class TestGetByConnection:
    async def test_returns_list(
        self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict
    ) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=[schedule_row]))
        scheds = await repo.get_by_connection(1)
        assert len(scheds) == 1


class TestGetEnabled:
    async def test_returns_enabled_only(
        self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict
    ) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=[schedule_row]))
        scheds = await repo.get_enabled()
        assert len(scheds) == 1
        assert scheds[0].enabled is True


class TestCreate:
    async def test_create(self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=[schedule_row]))
        data = PlatformScheduleCreate(category_id=1, platform_type="wordpress", connection_id=1, posts_per_day=2)
        sched = await repo.create(data)
        assert isinstance(sched, PlatformSchedule)


class TestUpdate:
    async def test_partial_update(
        self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict
    ) -> None:
        updated = {**schedule_row, "enabled": False}
        mock_db.set_response("platform_schedules", MockResponse(data=[updated]))
        sched = await repo.update(1, PlatformScheduleUpdate(enabled=False))
        assert sched is not None
        assert sched.enabled is False


class TestGetByProject:
    async def test_returns_schedules_for_category_ids(
        self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict
    ) -> None:
        # Caller passes category_ids directly (no cross-repo query)
        mock_db.set_response("platform_schedules", MockResponse(data=[schedule_row]))
        scheds = await repo.get_by_project([1, 2])
        assert len(scheds) == 1

    async def test_returns_empty_when_no_category_ids(
        self, repo: SchedulesRepository, mock_db: MockSupabaseClient
    ) -> None:
        scheds = await repo.get_by_project([])
        assert scheds == []


class TestDelete:
    async def test_success(self, repo: SchedulesRepository, mock_db: MockSupabaseClient, schedule_row: dict) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=[schedule_row]))
        assert await repo.delete(1) is True

    async def test_not_found(self, repo: SchedulesRepository, mock_db: MockSupabaseClient) -> None:
        mock_db.set_response("platform_schedules", MockResponse(data=[]))
        assert await repo.delete(999) is False
