"""Tests for AdminService (H23 Phase 5)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.admin import AdminService


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def admin_service(mock_db: MagicMock) -> AdminService:
    return AdminService(db=mock_db)


class TestGetUserCount:
    @pytest.mark.asyncio
    async def test_returns_count(self, admin_service: AdminService) -> None:
        with patch.object(admin_service, "_users") as mock_users:
            mock_users.count_all = AsyncMock(return_value=42)
            result = await admin_service.get_user_count()
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_zero(self, admin_service: AdminService) -> None:
        with patch.object(admin_service, "_users") as mock_users:
            mock_users.count_all = AsyncMock(return_value=0)
            result = await admin_service.get_user_count()
        assert result == 0


class TestCheckDbHealth:
    @pytest.mark.asyncio
    async def test_healthy(self, admin_service: AdminService) -> None:
        with patch.object(admin_service, "_users") as mock_users:
            mock_users.count_all = AsyncMock(return_value=10)
            result = await admin_service.check_db_health()
        assert result is True

    @pytest.mark.asyncio
    async def test_unhealthy(self, admin_service: AdminService) -> None:
        with patch.object(admin_service, "_users") as mock_users:
            mock_users.count_all = AsyncMock(side_effect=Exception("DB down"))
            result = await admin_service.check_db_health()
        assert result is False


class TestGetApiCosts:
    @pytest.mark.asyncio
    async def test_returns_cost(self, admin_service: AdminService) -> None:
        with patch(
            "services.admin.PaymentsRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.sum_api_costs = AsyncMock(return_value=123.45)
            result = await admin_service.get_api_costs(7)
        assert result == 123.45
        mock_repo.sum_api_costs.assert_awaited_once_with(7)

    @pytest.mark.asyncio
    async def test_different_days(self, admin_service: AdminService) -> None:
        with patch(
            "services.admin.PaymentsRepository"
        ) as mock_repo_cls:
            mock_repo = mock_repo_cls.return_value
            mock_repo.sum_api_costs = AsyncMock(return_value=0.0)
            result = await admin_service.get_api_costs(90)
        assert result == 0.0
        mock_repo.sum_api_costs.assert_awaited_once_with(90)


class TestGetAudienceIds:
    @pytest.mark.asyncio
    async def test_returns_ids(self, admin_service: AdminService) -> None:
        with patch.object(admin_service, "_users") as mock_users:
            mock_users.get_ids_by_audience = AsyncMock(return_value=[1, 2, 3])
            result = await admin_service.get_audience_ids("active_7d")
        assert result == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_returns_empty(self, admin_service: AdminService) -> None:
        with patch.object(admin_service, "_users") as mock_users:
            mock_users.get_ids_by_audience = AsyncMock(return_value=[])
            result = await admin_service.get_audience_ids("paid")
        assert result == []
