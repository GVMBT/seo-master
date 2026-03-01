"""Tests for AdminService (H23 Phase 5)."""

from unittest.mock import AsyncMock, MagicMock, patch

from services.admin import AdminService


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
