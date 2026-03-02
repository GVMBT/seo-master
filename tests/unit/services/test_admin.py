"""Tests for AdminService (H23 Phase 5 + admin panel improvements)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.exceptions import AppError
from services.admin import (
    APIStatusReport,
    AdminPanelStats,
    AdminService,
    BalanceAdjustResult,
    UserCard,
)


def _make_admin_service() -> AdminService:
    svc = AdminService(db=MagicMock())
    svc._users = MagicMock()
    svc._payments = MagicMock()
    svc._projects = MagicMock()
    svc._publications = MagicMock()
    svc._schedules = MagicMock()
    return svc


def _make_mock_user(
    user_id: int = 123,
    role: str = "user",
    balance: int = 500,
    last_activity: str | None = "2026-03-01T10:00:00",
) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "testuser"
    user.balance = balance
    user.role = role
    user.created_at = "2026-01-15T10:00:00"
    user.last_activity = last_activity
    return user


class TestGetUserCount:
    async def test_get_user_count_returns_value(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(return_value=42)
        result = await svc.get_user_count()
        assert result == 42

    async def test_get_user_count_returns_zero(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(return_value=0)
        result = await svc.get_user_count()
        assert result == 0


class TestCheckDbHealth:
    async def test_check_db_health_returns_true_on_success(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(return_value=10)
        result = await svc.check_db_health()
        assert result is True

    async def test_check_db_health_returns_false_on_error(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(side_effect=Exception("DB down"))
        result = await svc.check_db_health()
        assert result is False


class TestGetApiCosts:
    async def test_get_api_costs_returns_sum(self) -> None:
        svc = _make_admin_service()
        svc._payments.sum_api_costs = AsyncMock(return_value=123.45)
        result = await svc.get_api_costs(7)
        assert result == 123.45
        svc._payments.sum_api_costs.assert_awaited_once_with(7)

    async def test_get_api_costs_different_days(self) -> None:
        svc = _make_admin_service()
        svc._payments.sum_api_costs = AsyncMock(return_value=0.0)
        result = await svc.get_api_costs(90)
        assert result == 0.0
        svc._payments.sum_api_costs.assert_awaited_once_with(90)


class TestGetAudienceIds:
    async def test_get_audience_ids_returns_list(self) -> None:
        svc = _make_admin_service()
        svc._users.get_ids_by_audience = AsyncMock(return_value=[1, 2, 3])
        result = await svc.get_audience_ids("active_7d")
        assert result == [1, 2, 3]

    async def test_get_audience_ids_returns_empty(self) -> None:
        svc = _make_admin_service()
        svc._users.get_ids_by_audience = AsyncMock(return_value=[])
        result = await svc.get_audience_ids("paid")
        assert result == []


class TestGetPanelStats:
    async def test_get_panel_stats_aggregates_all_repos(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(return_value=100)
        svc._users.count_paid = AsyncMock(return_value=15)
        svc._projects.count_all = AsyncMock(return_value=50)
        svc._payments.sum_api_costs = AsyncMock(return_value=200.50)
        svc._publications.count_recent = AsyncMock(return_value=30)

        stats = await svc.get_panel_stats()

        assert isinstance(stats, AdminPanelStats)
        assert stats.total_users == 100
        assert stats.paid_users == 15
        assert stats.total_projects == 50
        assert stats.revenue_30d == 200.50
        assert stats.publications_7d == 30
        svc._payments.sum_api_costs.assert_awaited_once_with(30)

    async def test_get_panel_stats_returns_zeros(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(return_value=0)
        svc._users.count_paid = AsyncMock(return_value=0)
        svc._projects.count_all = AsyncMock(return_value=0)
        svc._payments.sum_api_costs = AsyncMock(return_value=0.0)
        svc._publications.count_recent = AsyncMock(return_value=0)

        stats = await svc.get_panel_stats()
        assert stats.total_users == 0
        assert stats.publications_7d == 0


class TestLookupUser:
    async def test_lookup_user_by_id(self) -> None:
        svc = _make_admin_service()
        mock_user = _make_mock_user()
        svc._users.get_by_id = AsyncMock(return_value=mock_user)
        svc._projects.get_count_by_user = AsyncMock(return_value=3)
        svc._publications.count_by_user = AsyncMock(return_value=12)

        card = await svc.lookup_user(user_id=123)

        assert isinstance(card, UserCard)
        assert card.user_id == 123
        assert card.first_name == "Test"
        assert card.username == "testuser"
        assert card.balance == 500
        assert card.projects_count == 3
        assert card.publications_count == 12
        assert card.last_activity is not None
        svc._users.get_by_id.assert_awaited_once_with(123)

    async def test_lookup_user_by_username(self) -> None:
        svc = _make_admin_service()
        mock_user = _make_mock_user(user_id=456)
        mock_user.first_name = "Alice"
        mock_user.last_name = None
        mock_user.username = "alice"
        svc._users.get_by_username = AsyncMock(return_value=mock_user)
        svc._projects.get_count_by_user = AsyncMock(return_value=1)
        svc._publications.count_by_user = AsyncMock(return_value=0)

        card = await svc.lookup_user(username="@alice")
        assert card is not None
        assert card.user_id == 456
        assert card.first_name == "Alice"
        svc._users.get_by_username.assert_awaited_once_with("@alice")

    async def test_lookup_user_not_found_returns_none(self) -> None:
        svc = _make_admin_service()
        svc._users.get_by_id = AsyncMock(return_value=None)
        card = await svc.lookup_user(user_id=999)
        assert card is None

    async def test_lookup_user_no_args_returns_none(self) -> None:
        svc = _make_admin_service()
        card = await svc.lookup_user()
        assert card is None


class TestChangeUserRole:
    async def test_change_role_succeeds(self) -> None:
        svc = _make_admin_service()
        svc._users.get_by_id = AsyncMock(return_value=_make_mock_user())
        svc._users.update = AsyncMock()
        redis = MagicMock()
        redis.delete = AsyncMock()

        result = await svc.change_user_role(123, "blocked", admin_ids=[999], redis=redis)

        assert result == "blocked"
        svc._users.update.assert_awaited_once()
        redis.delete.assert_awaited_once()

    async def test_change_role_rejects_admin(self) -> None:
        svc = _make_admin_service()
        redis = MagicMock()

        with pytest.raises(AppError, match="администратора"):
            await svc.change_user_role(999, "blocked", admin_ids=[999], redis=redis)

    async def test_change_role_user_not_found(self) -> None:
        svc = _make_admin_service()
        svc._users.get_by_id = AsyncMock(return_value=None)
        redis = MagicMock()

        with pytest.raises(AppError, match="не найден"):
            await svc.change_user_role(123, "blocked", admin_ids=[999], redis=redis)


class TestAdjustBalance:
    async def test_credit_balance(self) -> None:
        svc = _make_admin_service()
        svc._users.get_by_id = AsyncMock(return_value=_make_mock_user())
        svc._users.credit_balance = AsyncMock(return_value=1500)
        svc._payments.create_expense = AsyncMock()
        redis = MagicMock()
        redis.delete = AsyncMock()

        result = await svc.adjust_balance(
            target_id=123, amount=1000, is_credit=True, admin_id=999, redis=redis,
        )

        assert isinstance(result, BalanceAdjustResult)
        assert result.new_balance == 1500
        assert result.expense_recorded is True
        svc._users.credit_balance.assert_awaited_once_with(123, 1000)
        svc._payments.create_expense.assert_awaited_once()

    async def test_debit_balance(self) -> None:
        svc = _make_admin_service()
        svc._users.get_by_id = AsyncMock(return_value=_make_mock_user(balance=1000))
        svc._users.force_debit_balance = AsyncMock(return_value=0)
        svc._payments.create_expense = AsyncMock()
        redis = MagicMock()
        redis.delete = AsyncMock()

        result = await svc.adjust_balance(
            target_id=123, amount=1000, is_credit=False, admin_id=999, redis=redis,
        )

        assert result.new_balance == 0
        svc._users.force_debit_balance.assert_awaited_once_with(123, 1000)

    async def test_adjust_balance_user_not_found(self) -> None:
        svc = _make_admin_service()
        svc._users.get_by_id = AsyncMock(return_value=None)
        redis = MagicMock()

        with pytest.raises(AppError, match="не найден"):
            await svc.adjust_balance(
                target_id=999, amount=100, is_credit=True, admin_id=1, redis=redis,
            )


class TestGetRecentPublications:
    async def test_returns_publications(self) -> None:
        svc = _make_admin_service()
        mock_pubs = [MagicMock(), MagicMock()]
        svc._publications.get_by_user = AsyncMock(return_value=mock_pubs)

        result = await svc.get_recent_publications(123, limit=5)

        assert len(result) == 2
        svc._publications.get_by_user.assert_awaited_once_with(123, limit=5)

    async def test_returns_empty_list(self) -> None:
        svc = _make_admin_service()
        svc._publications.get_by_user = AsyncMock(return_value=[])

        result = await svc.get_recent_publications(123)
        assert result == []


class TestGetApiStatus:
    async def test_all_services_healthy(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(return_value=1)

        redis = MagicMock()
        redis.ping = AsyncMock(return_value=True)

        http_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"limit_remaining": 127.5}}
        http_client.get = AsyncMock(return_value=mock_resp)

        svc._schedules.count_active = AsyncMock(return_value=5)

        with pytest.MonkeyPatch.context() as mp:
            # Mock QStash SDK
            mock_qstash_cls = MagicMock()
            mock_qstash_cls.return_value.schedule.list.return_value = [1, 2, 3, 4, 5]
            mp.setattr("services.admin.asyncio.to_thread", AsyncMock(return_value=5))

            status = await svc.get_api_status(
                redis=redis,
                http_client=http_client,
                openrouter_api_key="test-key",
                qstash_token="test-token",
            )

        assert isinstance(status, APIStatusReport)
        assert status.db_ok is True
        assert status.redis_ok is True
        assert status.openrouter_ok is True
        assert status.openrouter_credits == 127.5
        assert status.active_schedules == 5

    async def test_db_down(self) -> None:
        svc = _make_admin_service()
        svc._users.count_all = AsyncMock(side_effect=Exception("DB down"))

        redis = MagicMock()
        redis.ping = AsyncMock(return_value=True)

        http_client = MagicMock()
        http_client.get = AsyncMock(side_effect=Exception("timeout"))

        svc._schedules.count_active = AsyncMock(return_value=0)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("services.admin.asyncio.to_thread", AsyncMock(side_effect=Exception("QStash down")))

            status = await svc.get_api_status(
                redis=redis,
                http_client=http_client,
                openrouter_api_key="test-key",
                qstash_token="test-token",
            )

        assert status.db_ok is False
        assert status.redis_ok is True
        assert status.openrouter_ok is False
        assert status.openrouter_credits is None
