"""Tests for services/dashboard.py — DashboardService.

Covers: dashboard data aggregation, platform flags, active schedules count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from services.dashboard import DashboardData, DashboardService, LastPublication

_SVC_MODULE = "services.dashboard"


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def dash_svc(mock_db: MagicMock) -> DashboardService:
    return DashboardService(db=mock_db, encryption_key="test-key")


# ---------------------------------------------------------------------------
# DashboardData model
# ---------------------------------------------------------------------------


class TestDashboardData:
    def test_create_frozen_model_raises_on_mutation(self) -> None:
        data = DashboardData(
            project_count=1, schedule_count=2,
            total_publications=0, last_publication=None, tokens_per_week=0, tokens_per_month=0,
        )
        with pytest.raises(ValidationError):
            data.project_count = 5  # type: ignore[misc]

    def test_create_model_stores_fields(self) -> None:
        data = DashboardData(
            project_count=3, schedule_count=7,
            total_publications=10, last_publication=None, tokens_per_week=960, tokens_per_month=3840,
        )
        assert data.project_count == 3
        assert data.schedule_count == 7
        assert data.total_publications == 10
        assert data.tokens_per_week == 960
        assert data.tokens_per_month == 3840


# ---------------------------------------------------------------------------
# get_dashboard_data — no projects
# ---------------------------------------------------------------------------


class TestGetDashboardDataNoProjects:
    async def test_get_dashboard_data_empty_returns_zeros(self, dash_svc: DashboardService) -> None:
        dash_svc._db = MagicMock()

        with (
            patch(f"{_SVC_MODULE}.ProjectsRepository") as mock_repo_cls,
            patch(f"{_SVC_MODULE}.PublicationsRepository") as mock_pub_cls,
        ):
            mock_repo_cls.return_value.get_by_user = AsyncMock(return_value=[])
            mock_pub_cls.return_value.get_stats_by_user = AsyncMock(
                return_value={"total_publications": 0, "total_tokens_spent": 0},
            )
            mock_pub_cls.return_value.get_last_successful = AsyncMock(return_value=None)

            result = await dash_svc.get_dashboard_data(42)

        assert result.project_count == 0
        assert result.schedule_count == 0
        assert result.total_publications == 0
        assert result.last_publication is None


# ---------------------------------------------------------------------------
# get_dashboard_data — with projects
# ---------------------------------------------------------------------------


def _mock_pub_repo(mock_cls: MagicMock) -> None:
    """Set up PublicationsRepository mock with empty defaults."""
    mock_cls.return_value.get_stats_by_user = AsyncMock(
        return_value={"total_publications": 0, "total_tokens_spent": 0},
    )
    mock_cls.return_value.get_last_successful = AsyncMock(return_value=None)


class TestGetDashboardDataWithProjects:
    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_get_dashboard_data_schedules_aggregated(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1), MagicMock(id=2)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
        _mock_pub_repo(mock_pub_cls)

        # Categories + schedules
        cat1 = MagicMock(id=10)
        cat2 = MagicMock(id=20)
        mock_cats = MagicMock()
        mock_cats.get_by_project = AsyncMock(side_effect=[[cat1], [cat2]])
        mock_cats_cls.return_value = mock_cats

        sched1 = MagicMock(
            enabled=True, schedule_days=["mon", "wed", "fri"], posts_per_day=1, platform_type="wordpress",
        )
        sched2 = MagicMock(enabled=False, schedule_days=[], posts_per_day=1, platform_type="telegram")
        sched3 = MagicMock(enabled=True, schedule_days=["mon"], posts_per_day=1, platform_type="telegram")
        mock_sched = MagicMock()
        mock_sched.get_by_project = AsyncMock(return_value=[sched1, sched2, sched3])
        mock_sched_cls.return_value = mock_sched

        result = await dash_svc.get_dashboard_data(42)

        assert result.project_count == 2
        assert result.schedule_count == 2  # 2 enabled out of 3
        assert result.tokens_per_week == 3 * 320 + 1 * 40  # 3 WP posts/wk + 1 TG post/wk
        assert result.tokens_per_month == result.tokens_per_week * 4

    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_get_dashboard_data_no_categories_returns_zero_schedules(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
        _mock_pub_repo(mock_pub_cls)

        mock_cats_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_sched_cls.return_value.get_by_project = AsyncMock(return_value=[])

        result = await dash_svc.get_dashboard_data(42)

        assert result.schedule_count == 0

    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_last_publication_populated_from_successful(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        """get_last_successful returns a publication -> last_publication is populated."""
        from datetime import UTC, datetime

        projects = [MagicMock(id=1)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)

        last_pub_mock = MagicMock(
            keyword="seo оптимизация",
            content_type="article",
            created_at=datetime(2026, 2, 15, tzinfo=UTC),
        )
        mock_pub_cls.return_value.get_stats_by_user = AsyncMock(
            return_value={"total_publications": 5, "total_tokens_spent": 1600},
        )
        mock_pub_cls.return_value.get_last_successful = AsyncMock(return_value=last_pub_mock)

        mock_cats_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_sched_cls.return_value.get_by_project = AsyncMock(return_value=[])

        result = await dash_svc.get_dashboard_data(42)

        assert result.last_publication is not None
        assert result.last_publication.keyword == "seo оптимизация"
        assert result.last_publication.content_type == "article"
        assert result.last_publication.created_at == datetime(2026, 2, 15, tzinfo=UTC)
        assert result.total_publications == 5


# ---------------------------------------------------------------------------
# build_text (moved from router to service — CR-113)
# ---------------------------------------------------------------------------


def _data(**overrides: object) -> DashboardData:
    """Create DashboardData with sensible defaults."""
    defaults: dict[str, object] = {
        "project_count": 1,
        "schedule_count": 0,
        "total_publications": 0,
        "last_publication": None,
        "tokens_per_week": 0,
        "tokens_per_month": 0,
    }
    defaults.update(overrides)
    return DashboardData(**defaults)  # type: ignore[arg-type]


class TestBuildText:
    def test_negative_balance_shows_debt_warning(self) -> None:
        text = DashboardService.build_text("Test", -100, False, _data())
        assert "Баланс: -100 токенов" in text
        assert "Долг 100 токенов" in text

    def test_zero_balance_shows_topup_message(self) -> None:
        text = DashboardService.build_text("Test", 0, False, _data())
        assert "Баланс: 0 токенов" in text
        assert "пополнить" in text

    def test_new_user_no_projects_shows_welcome(self) -> None:
        text = DashboardService.build_text("Иван", 1500, True, _data(project_count=0))
        assert "Привет, Иван!" in text
        assert "~4 статей" in text  # 1500 // 320 = 4

    def test_returning_user_with_projects_shows_stats(self) -> None:
        text = DashboardService.build_text(
            "Test", 1500, False, _data(project_count=2, schedule_count=3, total_publications=10),
        )
        assert "Проектов: 2" in text
        assert "Расписаний: 3" in text
        assert "Публикаций: 10" in text

    def test_last_publication_shown_in_text(self) -> None:
        from datetime import UTC, datetime

        lp = LastPublication(keyword="seo tips", content_type="article", created_at=datetime(2026, 2, 15, tzinfo=UTC))
        text = DashboardService.build_text("Test", 1500, False, _data(last_publication=lp, total_publications=1))
        assert "seo tips" in text
        assert "15.02" in text

    def test_forecast_shown_when_positive(self) -> None:
        text = DashboardService.build_text(
            "Test", 1500, False, _data(tokens_per_week=960, tokens_per_month=3840),
        )
        assert "960 ток/нед" in text
        assert "3 840 ток/мес" in text

    def test_returning_user_no_projects_shows_prompt(self) -> None:
        text = DashboardService.build_text("Test", 1500, False, _data(project_count=0))
        assert "нет проектов" in text
