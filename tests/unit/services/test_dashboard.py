"""Tests for services/dashboard.py — DashboardService.

Covers: dashboard data aggregation, platform flags, active schedules count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.dashboard import DashboardData, DashboardService

_SVC_MODULE = "services.dashboard"


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def dash_svc(mock_db: MagicMock) -> DashboardService:
    return DashboardService(db=mock_db, encryption_key="test-key")


# ---------------------------------------------------------------------------
# DashboardData is frozen
# ---------------------------------------------------------------------------


class TestDashboardData:
    def test_frozen(self) -> None:
        data = DashboardData(project_count=1, schedule_count=2, has_wp=True, has_social=False)
        with pytest.raises(AttributeError):
            data.project_count = 5  # type: ignore[misc]

    def test_fields(self) -> None:
        data = DashboardData(project_count=3, schedule_count=7, has_wp=True, has_social=True)
        assert data.project_count == 3
        assert data.schedule_count == 7
        assert data.has_wp is True
        assert data.has_social is True


# ---------------------------------------------------------------------------
# get_dashboard_data — no projects
# ---------------------------------------------------------------------------


class TestGetDashboardDataNoProjects:
    async def test_no_projects(self, dash_svc: DashboardService) -> None:
        dash_svc._db = MagicMock()

        with patch(f"{_SVC_MODULE}.ProjectsRepository") as mock_repo_cls:
            mock_repo_cls.return_value.get_by_user = AsyncMock(return_value=[])

            result = await dash_svc.get_dashboard_data(42)

        assert result.project_count == 0
        assert result.schedule_count == 0
        assert result.has_wp is False
        assert result.has_social is False


# ---------------------------------------------------------------------------
# get_dashboard_data — with projects
# ---------------------------------------------------------------------------


class TestGetDashboardDataWithProjects:
    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_with_wp_and_social(
        self,
        mock_proj_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1), MagicMock(id=2)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)

        # Connections: project 1 has WP, project 2 has telegram
        mock_conn = MagicMock()
        mock_conn.get_platform_types_by_project = AsyncMock(
            side_effect=[["wordpress"], ["telegram"]]
        )
        mock_conn_cls.return_value = mock_conn

        # Categories + schedules
        cat1 = MagicMock(id=10)
        cat2 = MagicMock(id=20)
        mock_cats = MagicMock()
        mock_cats.get_by_project = AsyncMock(
            side_effect=[[cat1], [cat2]]
        )
        mock_cats_cls.return_value = mock_cats

        sched1 = MagicMock(enabled=True)
        sched2 = MagicMock(enabled=False)
        sched3 = MagicMock(enabled=True)
        mock_sched = MagicMock()
        mock_sched.get_by_project = AsyncMock(
            side_effect=[[sched1, sched2], [sched3]]
        )
        mock_sched_cls.return_value = mock_sched

        result = await dash_svc.get_dashboard_data(42)

        assert result.project_count == 2
        assert result.has_wp is True
        assert result.has_social is True
        assert result.schedule_count == 2  # 2 enabled out of 3

    @patch(f"{_SVC_MODULE}.SchedulesRepository")
    @patch(f"{_SVC_MODULE}.CategoriesRepository")
    @patch(f"{_SVC_MODULE}.ConnectionsRepository")
    @patch(f"{_SVC_MODULE}.CredentialManager")
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_wp_only(
        self,
        mock_proj_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)

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
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_no_connections(
        self,
        mock_proj_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        projects = [MagicMock(id=1)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)

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
    @patch(f"{_SVC_MODULE}.ProjectsRepository")
    async def test_early_exit_when_both_flags_found(
        self,
        mock_proj_cls: MagicMock,
        _mock_cm_cls: MagicMock,
        mock_conn_cls: MagicMock,
        mock_cats_cls: MagicMock,
        mock_sched_cls: MagicMock,
        dash_svc: DashboardService,
    ) -> None:
        """Platform flags loop breaks early when both flags are True."""
        projects = [MagicMock(id=1), MagicMock(id=2), MagicMock(id=3)]
        mock_proj_cls.return_value.get_by_user = AsyncMock(return_value=projects)

        # First project has both — should break after 1st
        mock_conn = MagicMock()
        mock_conn.get_platform_types_by_project = AsyncMock(
            return_value=["wordpress", "telegram"]
        )
        mock_conn_cls.return_value = mock_conn

        mock_cats_cls.return_value.get_by_project = AsyncMock(return_value=[])
        mock_sched_cls.return_value.get_by_project = AsyncMock(return_value=[])

        result = await dash_svc.get_dashboard_data(42)

        assert result.has_wp is True
        assert result.has_social is True
        # Only 1 call because loop breaks early
        assert mock_conn.get_platform_types_by_project.await_count == 1
