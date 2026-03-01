"""Tests for AdminService (H23 Phase 5 + admin panel improvements)."""

from unittest.mock import AsyncMock, MagicMock

from services.admin import AdminPanelStats, AdminService, MonitoringStatus, UserCard


class TestGetUserCount:
    async def test_get_user_count_returns_value(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=42)
        result = await admin_svc.get_user_count()
        assert result == 42

    async def test_get_user_count_returns_zero(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=0)
        result = await admin_svc.get_user_count()
        assert result == 0


class TestCheckDbHealth:
    async def test_check_db_health_returns_true_on_success(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=10)
        result = await admin_svc.check_db_health()
        assert result is True

    async def test_check_db_health_returns_false_on_error(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(side_effect=Exception("DB down"))
        result = await admin_svc.check_db_health()
        assert result is False


class TestGetApiCosts:
    async def test_get_api_costs_returns_sum(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._payments = MagicMock()
        admin_svc._payments.sum_api_costs = AsyncMock(return_value=123.45)
        result = await admin_svc.get_api_costs(7)
        assert result == 123.45
        admin_svc._payments.sum_api_costs.assert_awaited_once_with(7)

    async def test_get_api_costs_different_days(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._payments = MagicMock()
        admin_svc._payments.sum_api_costs = AsyncMock(return_value=0.0)
        result = await admin_svc.get_api_costs(90)
        assert result == 0.0
        admin_svc._payments.sum_api_costs.assert_awaited_once_with(90)


class TestGetAudienceIds:
    async def test_get_audience_ids_returns_list(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.get_ids_by_audience = AsyncMock(return_value=[1, 2, 3])
        result = await admin_svc.get_audience_ids("active_7d")
        assert result == [1, 2, 3]

    async def test_get_audience_ids_returns_empty(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.get_ids_by_audience = AsyncMock(return_value=[])
        result = await admin_svc.get_audience_ids("paid")
        assert result == []


class TestGetPanelStats:
    async def test_get_panel_stats_aggregates_all_repos(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=100)
        admin_svc._users.count_paid = AsyncMock(return_value=15)
        admin_svc._projects = MagicMock()
        admin_svc._projects.count_all = AsyncMock(return_value=50)
        admin_svc._payments = MagicMock()
        admin_svc._payments.sum_api_costs = AsyncMock(return_value=200.50)
        admin_svc._publications = MagicMock()
        admin_svc._publications.count_recent = AsyncMock(return_value=30)

        stats = await admin_svc.get_panel_stats()

        assert isinstance(stats, AdminPanelStats)
        assert stats.total_users == 100
        assert stats.paid_users == 15
        assert stats.total_projects == 50
        assert stats.revenue_30d == 200.50
        assert stats.publications_7d == 30

    async def test_get_panel_stats_returns_zeros(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=0)
        admin_svc._users.count_paid = AsyncMock(return_value=0)
        admin_svc._projects = MagicMock()
        admin_svc._projects.count_all = AsyncMock(return_value=0)
        admin_svc._payments = MagicMock()
        admin_svc._payments.sum_api_costs = AsyncMock(return_value=0.0)
        admin_svc._publications = MagicMock()
        admin_svc._publications.count_recent = AsyncMock(return_value=0)

        stats = await admin_svc.get_panel_stats()
        assert stats.total_users == 0
        assert stats.publications_7d == 0


class TestGetMonitoringStatus:
    async def test_get_monitoring_status_all_healthy(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=1)
        admin_svc._schedules = MagicMock()
        admin_svc._schedules.count_active = AsyncMock(return_value=5)

        redis = MagicMock()
        redis.ping = AsyncMock(return_value=True)

        status = await admin_svc.get_monitoring_status(redis)

        assert isinstance(status, MonitoringStatus)
        assert status.db_ok is True
        assert status.redis_ok is True
        assert status.active_schedules == 5

    async def test_get_monitoring_status_redis_down(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.count_all = AsyncMock(return_value=1)
        admin_svc._schedules = MagicMock()
        admin_svc._schedules.count_active = AsyncMock(return_value=0)

        redis = MagicMock()
        redis.ping = AsyncMock(return_value=False)

        status = await admin_svc.get_monitoring_status(redis)
        assert status.db_ok is True
        assert status.redis_ok is False
        assert status.active_schedules == 0


class TestLookupUser:
    async def test_lookup_user_by_id(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        mock_user = MagicMock()
        mock_user.id = 123
        mock_user.first_name = "Test"
        mock_user.last_name = "User"
        mock_user.username = "testuser"
        mock_user.balance = 500
        mock_user.role = "user"
        mock_user.created_at = "2026-01-15T10:00:00"

        admin_svc._users = MagicMock()
        admin_svc._users.get_by_id = AsyncMock(return_value=mock_user)
        admin_svc._projects = MagicMock()
        admin_svc._projects.get_count_by_user = AsyncMock(return_value=3)

        card = await admin_svc.lookup_user(user_id=123)

        assert isinstance(card, UserCard)
        assert card.user_id == 123
        assert card.first_name == "Test"
        assert card.username == "testuser"
        assert card.balance == 500
        assert card.projects_count == 3
        admin_svc._users.get_by_id.assert_awaited_once_with(123)

    async def test_lookup_user_by_username(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        mock_user = MagicMock()
        mock_user.id = 456
        mock_user.first_name = "Alice"
        mock_user.last_name = None
        mock_user.username = "alice"
        mock_user.balance = 1500
        mock_user.role = "user"
        mock_user.created_at = "2026-02-01T12:00:00"

        admin_svc._users = MagicMock()
        admin_svc._users.get_by_username = AsyncMock(return_value=mock_user)
        admin_svc._projects = MagicMock()
        admin_svc._projects.get_count_by_user = AsyncMock(return_value=1)

        card = await admin_svc.lookup_user(username="@alice")
        assert card is not None
        assert card.user_id == 456
        assert card.first_name == "Alice"
        admin_svc._users.get_by_username.assert_awaited_once_with("@alice")

    async def test_lookup_user_not_found_returns_none(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        admin_svc._users = MagicMock()
        admin_svc._users.get_by_id = AsyncMock(return_value=None)

        card = await admin_svc.lookup_user(user_id=999)
        assert card is None

    async def test_lookup_user_no_args_returns_none(self) -> None:
        admin_svc = AdminService(db=MagicMock())
        card = await admin_svc.lookup_user()
        assert card is None
