"""Tests for services/dashboard.py — DashboardService.

Covers: dashboard data aggregation, platform flags, active schedules count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from services.dashboard import DashboardData, DashboardService

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
            project_count=1, schedule_count=2, has_wp=True, has_social=False,
            total_publications=0, last_publication=None, tokens_per_week=0, tokens_per_month=0,
        )
        with pytest.raises(ValidationError):
            data.project_count = 5  # type: ignore[misc]

    def test_create_model_stores_fields(self) -> None:
        data = DashboardData(
            project_count=3, schedule_count=7, has_wp=True, has_social=True,
            total_publications=10, last_publication=None, tokens_per_week=960, tokens_per_month=3840,
        )
        assert data.project_count == 3
        assert data.schedule_count == 7
        assert data.has_wp is True
        assert data.has_social is True
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
            mock_pub_cls.return_value.get_by_user = AsyncMock(return_value=[])

            result = await dash_svc.get_dashboard_data(42)

        assert result.project_count == 0
        assert result.schedule_count == 0
        assert result.has_wp is False
        assert result.has_social is False
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
    mock_cls.return_value.get_by_user = AsyncMock(return_value=[])


class TestGetDashboardDataWithProjects:
    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_get_dashboard_data_wp_and_social_aggregated(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1), MagicMock(id=2)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
        _mock_pub_repo(mock_pub_cls)

        # Connections: project 1 has WP, project 2 has telegram
        mock_conn = MagicMock()
        mock_conn.get_platform_types_by_project = AsyncMock(side_effect=[["wordpress"], ["telegram"]])
        mock_conn_cls.return_value = mock_conn

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
        assert result.has_wp is True
        assert result.has_social is True
        assert result.schedule_count == 2  # 2 enabled out of 3
        assert result.tokens_per_week == 3 * 320 + 1 * 40  # 3 WP posts/wk + 1 TG post/wk

    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_get_dashboard_data_wp_only_detected(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
        _mock_pub_repo(mock_pub_cls)

        mock_conn = MagicMock()
        mock_conn.get_platform_types_by_project = AsyncMock(return_value=["wordpress"])
        mock_conn_cls.return_value = mock_conn

        mock_cats_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_sched_cls.return_value.get_by_project = AsyncMock(return_value=[])

        result = await dash_svc.get_dashboard_data(42)

        assert result.has_wp is True
        assert result.has_social is False
        assert result.schedule_count == 0

    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_get_dashboard_data_no_connections_returns_false(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
        _mock_pub_repo(mock_pub_cls)

        mock_conn_cls.return_value.get_platform_types_by_project = AsyncMock(return_value=[])

        mock_cats_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_sched_cls.return_value.get_by_project = AsyncMock(return_value=[])

        result = await dash_svc.get_dashboard_data(42)

        assert result.has_wp is False
        assert result.has_social is False

    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    @patch(f"{_SVC_MODULE}.PublicationsRepository")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_get_platform_flags_parallel_fetches_all_projects(
        self,
        mock_proj_cls: MagicMock,
        mock_pub_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        """asyncio.gather fetches platform types for all projects in parallel."""
        projects = [MagicMock(id=1), MagicMock(id=2), MagicMock(id=3)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)
        _mock_pub_repo(mock_pub_cls)

        mock_conn = MagicMock()
        mock_conn.get_platform_types_by_project = AsyncMock(side_effect=[["wordpress", "telegram"], [], []])
        mock_conn_cls.return_value = mock_conn

        mock_cats_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_sched_cls.return_value.get_by_project = AsyncMock(return_value=[])

        result = await dash_svc.get_dashboard_data(42)

        assert result.has_wp is True
        assert result.has_social is True
        # All 3 projects fetched in parallel via asyncio.gather
        assert mock_conn.get_platform_types_by_project.await_count == 3
