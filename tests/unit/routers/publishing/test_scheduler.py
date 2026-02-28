"""Tests for routers/publishing/scheduler.py — Scheduler router handlers.

Coverage target: all handlers + FSM flow + validation + edge cases.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.models import Category, PlatformConnection, PlatformSchedule, Project, User
from routers.publishing.scheduler import (
    ScheduleSetupFSM,
    _extract_selected_from_keyboard,
    _filter_social,
    schedule_cancel,
    schedule_count_select,
    schedule_day_toggle,
    schedule_days_done,
    schedule_time_toggle,
    schedule_times_done,
    scheduler_articles_entry,
    scheduler_category,
    scheduler_conn_list_back,
    scheduler_connection,
    scheduler_crosspost_config,
    scheduler_crosspost_save,
    scheduler_disable,
    scheduler_entry,
    scheduler_manual,
    scheduler_preset,
    scheduler_social_connection,
    scheduler_social_entry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "id": 123456,
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User",
        "balance": 1500,
        "language": "ru",
        "role": "user",
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_project(**overrides: Any) -> Project:
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 123456,
        "name": "Test Project",
        "company_name": "TestCo",
        "specialization": "SEO",
        "timezone": "Europe/Moscow",
    }
    defaults.update(overrides)
    return Project(**defaults)


def _make_category(**overrides: Any) -> Category:
    defaults: dict[str, Any] = {
        "id": 10,
        "project_id": 1,
        "name": "Test Category",
    }
    defaults.update(overrides)
    return Category(**defaults)


def _make_connection(**overrides: Any) -> PlatformConnection:
    defaults: dict[str, Any] = {
        "id": 5,
        "project_id": 1,
        "platform_type": "wordpress",
        "identifier": "blog.example.com",
        "credentials": {"url": "https://blog.example.com"},
        "status": "active",
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_schedule(**overrides: Any) -> PlatformSchedule:
    defaults: dict[str, Any] = {
        "id": 1,
        "category_id": 10,
        "platform_type": "wordpress",
        "connection_id": 5,
        "schedule_days": ["mon", "wed", "fri"],
        "schedule_times": ["09:00", "15:00"],
        "posts_per_day": 2,
        "enabled": True,
        "status": "active",
        "qstash_schedule_ids": ["qs_1"],
        "cross_post_connection_ids": [],
        "last_post_at": None,
        "created_at": None,
    }
    defaults.update(overrides)
    return PlatformSchedule(**defaults)


def _make_social_conn(**overrides: Any) -> PlatformConnection:
    defaults: dict[str, Any] = {
        "id": 20,
        "project_id": 1,
        "platform_type": "telegram",
        "identifier": "@testchannel",
        "credentials": {"bot_token": "xxx"},
        "status": "active",
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


@pytest.fixture
def mock_callback() -> MagicMock:
    """Mock CallbackQuery with message and async methods."""
    cb = MagicMock()
    cb.message = MagicMock()
    cb.message.edit_text = AsyncMock()
    cb.message.edit_reply_markup = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.reply_markup = None
    cb.answer = AsyncMock()
    cb.data = ""
    return cb


@pytest.fixture
def mock_state() -> MagicMock:
    state = MagicMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.get_state = AsyncMock(return_value=None)
    state.update_data = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    return state


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def user() -> User:
    return _make_user()


@pytest.fixture
def project() -> Project:
    return _make_project()


@pytest.fixture
def category() -> Category:
    return _make_category()


@pytest.fixture
def scheduler_service() -> AsyncMock:
    svc = AsyncMock()
    svc.create_schedule = AsyncMock(return_value=_make_schedule())
    svc.delete_schedule = AsyncMock(return_value=True)
    svc.estimate_weekly_cost = MagicMock(return_value=960)
    return svc


# ---------------------------------------------------------------------------
# Unit: _filter_social
# ---------------------------------------------------------------------------


class TestFilterSocial:
    def test_filters_social_active_connections(self) -> None:
        conns = [
            _make_connection(id=1, platform_type="wordpress"),
            _make_social_conn(id=2, platform_type="telegram"),
            _make_social_conn(id=3, platform_type="vk"),
            _make_social_conn(id=4, platform_type="pinterest"),
            _make_social_conn(id=5, platform_type="telegram", status="error"),
        ]
        result = _filter_social(conns)
        assert len(result) == 3
        assert all(c.status == "active" for c in result)

    def test_empty_list(self) -> None:
        assert _filter_social([]) == []

    def test_no_social(self) -> None:
        conns = [_make_connection(platform_type="wordpress")]
        assert _filter_social(conns) == []


# ---------------------------------------------------------------------------
# Unit: _extract_selected_from_keyboard
# ---------------------------------------------------------------------------


class TestExtractSelectedFromKeyboard:
    def test_no_markup(self) -> None:
        assert _extract_selected_from_keyboard(None) == []

    def test_extracts_checked_connections(self) -> None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="\u2713 Telegram", callback_data="sched_xp:10:5:20:toggle")],
                [InlineKeyboardButton(text="VK", callback_data="sched_xp:10:5:30:toggle")],
            ]
        )
        result = _extract_selected_from_keyboard(kb)
        assert result == [20]

    def test_no_checked_items(self) -> None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Telegram", callback_data="sched_xp:10:5:20:toggle")],
            ]
        )
        result = _extract_selected_from_keyboard(kb)
        assert result == []


# ---------------------------------------------------------------------------
# Entry handlers
# ---------------------------------------------------------------------------


class TestSchedulerEntry:
    @patch("routers.publishing.scheduler.scheduler_cat_list_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.CategoriesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_happy_path(
        self,
        mock_proj_cls: MagicMock,
        mock_cat_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[_make_category()])
        mock_callback.data = "project:1:scheduler"

        await scheduler_entry(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()
        mock_callback.answer.assert_awaited_once()

    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_project_not_found(
        self,
        mock_proj_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=None)
        mock_callback.data = "project:1:scheduler"

        await scheduler_entry(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_with("Проект не найден", show_alert=True)

    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_wrong_owner(
        self,
        mock_proj_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project(user_id=999))
        mock_callback.data = "project:1:scheduler"

        await scheduler_entry(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_with("Проект не найден", show_alert=True)

    @patch("routers.publishing.scheduler.CategoriesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_no_categories(
        self,
        mock_proj_cls: MagicMock,
        mock_cat_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_callback.data = "project:1:scheduler"

        await scheduler_entry(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_with("Сначала создайте категорию в карточке проекта", show_alert=True)

    async def test_inaccessible_message(self, mock_callback: MagicMock, user: User, mock_db: MagicMock) -> None:
        from aiogram.types import InaccessibleMessage

        mock_callback.message = MagicMock(spec=InaccessibleMessage)
        mock_callback.data = "project:1:scheduler"

        await scheduler_entry(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_once()


# ---------------------------------------------------------------------------
# Social entry
# ---------------------------------------------------------------------------


class TestSchedulerSocialEntry:
    @patch("routers.publishing.scheduler.scheduler_social_cat_list_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.CategoriesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_happy_path(
        self,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_cat_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(
            return_value=[_make_social_conn(id=20, platform_type="telegram")]
        )
        mock_conn_fn.return_value = mock_conn_repo
        mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[_make_category()])
        mock_callback.data = "project:1:sched_social"

        await scheduler_social_entry(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()

    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_no_social_connections(
        self,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(
            return_value=[_make_connection(platform_type="wordpress")]
        )
        mock_conn_fn.return_value = mock_conn_repo
        mock_callback.data = "project:1:sched_social"

        await scheduler_social_entry(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_with("Нет подключённых соцсетей", show_alert=True)


# ---------------------------------------------------------------------------
# Category -> connections list
# ---------------------------------------------------------------------------


class TestSchedulerCategory:
    @patch("routers.publishing.scheduler.scheduler_conn_list_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_happy_path(
        self,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(return_value=[_make_connection()])
        mock_conn_fn.return_value = mock_conn_repo
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "scheduler:1:cat:10"

        await scheduler_category(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()

    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_no_connections(
        self,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(return_value=[])
        mock_conn_fn.return_value = mock_conn_repo
        mock_callback.data = "scheduler:1:cat:10"

        await scheduler_category(mock_callback, user, mock_db)

        mock_callback.answer.assert_awaited_with("Нет подключений. Добавьте платформу.", show_alert=True)


# ---------------------------------------------------------------------------
# Connection config screen
# ---------------------------------------------------------------------------


class TestSchedulerConnection:
    @patch("routers.publishing.scheduler.scheduler_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_shows_existing_schedule(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_sched_cls.return_value.get_by_category = AsyncMock(
            return_value=[_make_schedule(connection_id=5, enabled=True)]
        )
        mock_callback.data = "scheduler:10:conn:5"

        await scheduler_connection(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Текущее расписание" in text

    @patch("routers.publishing.scheduler.scheduler_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_no_existing_schedule(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "scheduler:10:conn:5"

        await scheduler_connection(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Текущее расписание" not in text


# ---------------------------------------------------------------------------
# Preset schedule
# ---------------------------------------------------------------------------


class TestSchedulerPreset:
    @patch("routers.publishing.scheduler.scheduler_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_preset_1w_creates_schedule(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        scheduler_service: AsyncMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        conn = _make_connection()
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_id = AsyncMock(return_value=conn)
        mock_conn_fn.return_value = mock_conn_repo
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "sched:10:5:preset:1w"

        await scheduler_preset(mock_callback, user, mock_db, scheduler_service)

        scheduler_service.create_schedule.assert_awaited_once()
        call_kwargs = scheduler_service.create_schedule.call_args[1]
        assert call_kwargs["days"] == ["wed"]
        assert call_kwargs["times"] == ["10:00"]
        assert call_kwargs["posts_per_day"] == 1

    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_preset_deletes_existing(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        scheduler_service: AsyncMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        conn = _make_connection()
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_id = AsyncMock(return_value=conn)
        mock_conn_fn.return_value = mock_conn_repo
        existing = _make_schedule(id=99, connection_id=5)
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[existing])
        mock_callback.data = "sched:10:5:preset:daily"

        await scheduler_preset(mock_callback, user, mock_db, scheduler_service)

        scheduler_service.delete_schedule.assert_awaited_once_with(99)

    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_preset_creation_failure(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        scheduler_service: AsyncMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_id = AsyncMock(return_value=_make_connection())
        mock_conn_fn.return_value = mock_conn_repo
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        scheduler_service.create_schedule.side_effect = Exception("QStash boom")
        mock_callback.data = "sched:10:5:preset:1w"

        await scheduler_preset(mock_callback, user, mock_db, scheduler_service)

        mock_callback.answer.assert_awaited_with("Ошибка создания расписания", show_alert=True)


# ---------------------------------------------------------------------------
# Disable schedule
# ---------------------------------------------------------------------------


class TestSchedulerDisable:
    @patch("routers.publishing.scheduler.scheduler_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_disable_deletes_matching_schedule(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        scheduler_service: AsyncMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        existing = _make_schedule(id=42, connection_id=5)
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[existing])
        mock_callback.data = "sched:10:5:disable"

        await scheduler_disable(mock_callback, user, mock_db, scheduler_service)

        scheduler_service.delete_schedule.assert_awaited_once_with(42)
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "отключено" in text


# ---------------------------------------------------------------------------
# Manual FSM: entry + day toggle + days done + count + time toggle + times done
# ---------------------------------------------------------------------------


class TestSchedulerManualFSM:
    @patch("routers.publishing.scheduler.schedule_days_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.ensure_no_active_fsm", return_value=None)
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_manual_entry_sets_fsm_state(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_ensure: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "sched:10:5:manual"

        await scheduler_manual(mock_callback, user, mock_db, mock_state)

        mock_state.set_state.assert_awaited_with(ScheduleSetupFSM.select_days)
        mock_state.update_data.assert_awaited_once()
        data = mock_state.update_data.call_args[1]
        assert data["sched_cat_id"] == 10
        assert data["sched_conn_id"] == 5
        assert data["sched_days"] == []

    @patch("routers.publishing.scheduler.schedule_days_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.ensure_no_active_fsm", return_value="создание проекта")
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_manual_entry_interrupts_existing_fsm(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_ensure: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
        mock_state: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "sched:10:5:manual"

        await scheduler_manual(mock_callback, user, mock_db, mock_state)

        mock_callback.message.answer.assert_awaited_once()
        text = mock_callback.message.answer.call_args[0][0]
        assert "создание проекта" in text

    @patch("routers.publishing.scheduler.schedule_days_kb", return_value=MagicMock())
    async def test_day_toggle_adds_day(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_state.get_data.return_value = {"sched_days": []}
        mock_callback.data = "sched:day:mon"

        await schedule_day_toggle(mock_callback, mock_state)

        call_args = mock_state.update_data.call_args[1]
        assert "mon" in call_args["sched_days"]

    @patch("routers.publishing.scheduler.schedule_days_kb", return_value=MagicMock())
    async def test_day_toggle_removes_day(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_state.get_data.return_value = {"sched_days": ["mon", "wed"]}
        mock_callback.data = "sched:day:mon"

        await schedule_day_toggle(mock_callback, mock_state)

        call_args = mock_state.update_data.call_args[1]
        assert "mon" not in call_args["sched_days"]

    async def test_days_done_rejects_empty(self, mock_callback: MagicMock, mock_state: MagicMock) -> None:
        mock_state.get_data.return_value = {"sched_days": []}
        mock_callback.data = "sched:days:done"

        await schedule_days_done(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_with("Выберите хотя бы один день", show_alert=True)

    @patch("routers.publishing.scheduler.schedule_count_kb", return_value=MagicMock())
    async def test_days_done_advances_to_count(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_state.get_data.return_value = {"sched_days": ["mon"]}
        mock_callback.data = "sched:days:done"

        await schedule_days_done(mock_callback, mock_state)

        mock_state.set_state.assert_awaited_with(ScheduleSetupFSM.select_count)

    @patch("routers.publishing.scheduler.schedule_times_kb", return_value=MagicMock())
    async def test_count_select_stores_and_advances(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_callback.data = "sched:count:3"

        await schedule_count_select(mock_callback, mock_state)

        mock_state.update_data.assert_awaited()
        data = mock_state.update_data.call_args[1]
        assert data["sched_count"] == 3
        assert data["sched_times"] == []
        mock_state.set_state.assert_awaited_with(ScheduleSetupFSM.select_times)

    @patch("routers.publishing.scheduler.schedule_times_kb", return_value=MagicMock())
    async def test_time_toggle_adds_time(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_state.get_data.return_value = {"sched_times": [], "sched_count": 2}
        mock_callback.data = "sched:time:10:00"

        await schedule_time_toggle(mock_callback, mock_state)

        data = mock_state.update_data.call_args[1]
        assert "10:00" in data["sched_times"]

    @patch("routers.publishing.scheduler.schedule_times_kb", return_value=MagicMock())
    async def test_time_toggle_removes_time(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_state.get_data.return_value = {"sched_times": ["10:00"], "sched_count": 2}
        mock_callback.data = "sched:time:10:00"

        await schedule_time_toggle(mock_callback, mock_state)

        data = mock_state.update_data.call_args[1]
        assert "10:00" not in data["sched_times"]

    async def test_time_toggle_rejects_over_limit(self, mock_callback: MagicMock, mock_state: MagicMock) -> None:
        mock_state.get_data.return_value = {"sched_times": ["10:00"], "sched_count": 1}
        mock_callback.data = "sched:time:14:00"

        await schedule_time_toggle(mock_callback, mock_state)

        mock_callback.answer.assert_awaited_with("Максимум 1 слотов", show_alert=True)


# ---------------------------------------------------------------------------
# FSM: times done -> save
# ---------------------------------------------------------------------------


class TestScheduleTimesDone:
    async def test_rejects_wrong_count(self, mock_callback: MagicMock, mock_state: MagicMock) -> None:
        mock_state.get_data.return_value = {"sched_times": ["10:00"], "sched_count": 2}
        mock_callback.data = "sched:times:done"

        await schedule_times_done(
            mock_callback, _make_user(), MagicMock(), mock_state, AsyncMock()
        )

        mock_callback.answer.assert_awaited_with("Выберите ровно 2 слотов", show_alert=True)

    @patch("routers.publishing.scheduler.scheduler_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_creates_schedule_on_valid_input(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        mock_state: MagicMock,
        scheduler_service: AsyncMock,
    ) -> None:
        mock_state.get_data.return_value = {
            "sched_times": ["10:00"],
            "sched_count": 1,
            "sched_cat_id": 10,
            "sched_conn_id": 5,
            "sched_days": ["mon", "wed"],
        }
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_id = AsyncMock(return_value=_make_connection())
        mock_conn_fn.return_value = mock_conn_repo
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "sched:times:done"

        await schedule_times_done(
            mock_callback, _make_user(), MagicMock(), mock_state, scheduler_service
        )

        scheduler_service.create_schedule.assert_awaited_once()
        mock_state.clear.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Расписание установлено" in text


# ---------------------------------------------------------------------------
# FSM: cancel
# ---------------------------------------------------------------------------


class TestScheduleCancel:
    @patch("routers.publishing.scheduler.scheduler_config_kb", return_value=MagicMock())
    async def test_cancel_clears_state(
        self, mock_kb: MagicMock, mock_callback: MagicMock, mock_state: MagicMock
    ) -> None:
        mock_state.get_data.return_value = {"sched_cat_id": 10, "sched_conn_id": 5, "sched_has_schedule": False}
        mock_callback.data = "sched:cancel"

        await schedule_cancel(mock_callback, mock_state)

        mock_state.clear.assert_awaited_once()
        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "отменена" in text

    async def test_cancel_without_context(self, mock_callback: MagicMock, mock_state: MagicMock) -> None:
        mock_state.get_data.return_value = {}
        mock_callback.data = "sched:cancel"

        await schedule_cancel(mock_callback, mock_state)

        mock_state.clear.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "отменена" in text


# ---------------------------------------------------------------------------
# Conn list back
# ---------------------------------------------------------------------------


class TestSchedulerConnListBack:
    @patch("routers.publishing.scheduler.scheduler_conn_list_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_back_navigates(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(return_value=[_make_connection()])
        mock_conn_fn.return_value = mock_conn_repo
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "scheduler:10:conn_list"

        await scheduler_conn_list_back(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# Social connection config
# ---------------------------------------------------------------------------


class TestSchedulerSocialConnection:
    @patch("routers.publishing.scheduler.scheduler_social_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_shows_crosspost_info(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_sched_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        sched = _make_schedule(connection_id=20, cross_post_connection_ids=[30])
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[sched])
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(
            return_value=[_make_social_conn(id=20), _make_social_conn(id=30, platform_type="vk")]
        )
        mock_conn_fn.return_value = mock_conn_repo
        mock_callback.data = "sched_social:10:conn:20"

        await scheduler_social_connection(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "\u041a\u0440\u043e\u0441\u0441-\u043f\u043e\u0441\u0442\u0438\u043d\u0433" in text


# ---------------------------------------------------------------------------
# Crosspost config & save
# ---------------------------------------------------------------------------


class TestSchedulerCrosspost:
    @patch("routers.publishing.scheduler.scheduler_crosspost_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_crosspost_config_shows_screen(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_id = AsyncMock(return_value=_make_social_conn())
        mock_conn_repo.get_by_project = AsyncMock(return_value=[_make_social_conn()])
        mock_conn_fn.return_value = mock_conn_repo
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[])
        mock_callback.data = "sched_xp:10:20:config"

        await scheduler_crosspost_config(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "\u041a\u0440\u043e\u0441\u0441-\u043f\u043e\u0441\u0442\u0438\u043d\u0433" in text

    @patch("routers.publishing.scheduler.scheduler_social_config_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.SchedulesRepository")
    @patch("routers.publishing.scheduler._make_conn_repo")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    @patch("routers.publishing.scheduler.CategoriesRepository")
    async def test_crosspost_save_updates_schedule(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_conn_fn: MagicMock,
        mock_sched_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=_make_category())
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_conn_repo = MagicMock()
        mock_conn_repo.get_by_project = AsyncMock(
            return_value=[
                _make_social_conn(id=20, platform_type="telegram"),
                _make_social_conn(id=30, platform_type="vk"),
            ]
        )
        mock_conn_fn.return_value = mock_conn_repo
        existing = _make_schedule(connection_id=20)
        mock_sched_cls.return_value.get_by_category = AsyncMock(return_value=[existing])
        mock_sched_cls.return_value.update = AsyncMock()
        mock_callback.data = "sched_xp:10:20:save"
        # Simulate checked keyboard
        mock_callback.message.reply_markup = None  # no selections

        await scheduler_crosspost_save(mock_callback, user, mock_db)

        text = mock_callback.message.edit_text.call_args[0][0]
        assert "отключён" in text


# ---------------------------------------------------------------------------
# Articles entry
# ---------------------------------------------------------------------------


class TestSchedulerArticlesEntry:
    @patch("routers.publishing.scheduler.scheduler_cat_list_kb", return_value=MagicMock())
    @patch("routers.publishing.scheduler.CategoriesRepository")
    @patch("routers.publishing.scheduler.ProjectsRepository")
    async def test_happy_path(
        self,
        mock_proj_cls: MagicMock,
        mock_cat_cls: MagicMock,
        mock_kb: MagicMock,
        mock_callback: MagicMock,
        user: User,
        mock_db: MagicMock,
    ) -> None:
        mock_proj_cls.return_value.get_by_id = AsyncMock(return_value=_make_project())
        mock_cat_cls.return_value.get_by_project = AsyncMock(return_value=[_make_category()])
        mock_callback.data = "project:1:sched_articles"

        await scheduler_articles_entry(mock_callback, user, mock_db)

        mock_callback.message.edit_text.assert_awaited_once()
        text = mock_callback.message.edit_text.call_args[0][0]
        assert "Статьи" in text
