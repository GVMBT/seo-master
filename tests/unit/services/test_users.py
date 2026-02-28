"""Tests for services/users.py — UsersService.

Covers: link_referrer (CR-77b), toggle_notification, get_referral_count.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.users import UsersService


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_redis() -> MagicMock:
    redis = MagicMock()
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def mock_users_repo() -> AsyncMock:
    repo = AsyncMock()
    return repo


@pytest.fixture
def service(mock_db: MagicMock, mock_users_repo: AsyncMock) -> UsersService:
    svc = UsersService.__new__(UsersService)
    svc._db = mock_db
    svc._users = mock_users_repo
    return svc


# ---------------------------------------------------------------------------
# UsersService.link_referrer
# ---------------------------------------------------------------------------


class TestLinkReferrer:
    async def test_successful_link(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Valid referrer is linked and cache invalidated."""
        mock_users_repo.get_by_id.return_value = MagicMock(id=999)
        mock_users_repo.update.return_value = MagicMock()

        result = await service.link_referrer(123, 999, mock_redis)

        assert result is True
        mock_users_repo.get_by_id.assert_awaited_once_with(999)
        mock_users_repo.update.assert_awaited_once()
        # Verify update called with correct UserUpdate containing referrer_id
        update_arg = mock_users_repo.update.call_args[0][1]
        assert update_arg.referrer_id == 999
        mock_redis.delete.assert_awaited_once()

    async def test_self_referral_blocked(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Self-referral returns False without any DB calls."""
        result = await service.link_referrer(123, 123, mock_redis)

        assert result is False
        mock_users_repo.get_by_id.assert_not_awaited()
        mock_users_repo.update.assert_not_awaited()

    async def test_invalid_referrer_not_found(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Non-existent referrer returns False."""
        mock_users_repo.get_by_id.return_value = None

        result = await service.link_referrer(123, 999, mock_redis)

        assert result is False
        mock_users_repo.get_by_id.assert_awaited_once_with(999)
        mock_users_repo.update.assert_not_awaited()

    async def test_cache_invalidated_on_success(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """User cache key is deleted after successful link."""
        mock_users_repo.get_by_id.return_value = MagicMock(id=999)
        mock_users_repo.update.return_value = MagicMock()

        await service.link_referrer(42, 999, mock_redis)

        # Cache key should be user:42
        mock_redis.delete.assert_awaited_once_with("user:42")


# ---------------------------------------------------------------------------
# UsersService.toggle_notification
# ---------------------------------------------------------------------------


class TestToggleNotification:
    async def test_toggle_publications(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Toggle publications from True to False."""
        updated_user = MagicMock(notify_publications=False, notify_balance=True, notify_news=True)
        mock_users_repo.update.return_value = MagicMock()
        mock_users_repo.get_by_id.return_value = updated_user

        result = await service.toggle_notification(42, "publications", True, mock_redis)

        assert result is updated_user
        update_arg = mock_users_repo.update.call_args[0][1]
        assert update_arg.notify_publications is False

    async def test_toggle_balance(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Toggle balance from False to True."""
        updated_user = MagicMock(notify_balance=True)
        mock_users_repo.update.return_value = MagicMock()
        mock_users_repo.get_by_id.return_value = updated_user

        result = await service.toggle_notification(42, "balance", False, mock_redis)

        assert result is updated_user
        update_arg = mock_users_repo.update.call_args[0][1]
        assert update_arg.notify_balance is True

    async def test_toggle_news(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Toggle news field."""
        updated_user = MagicMock(notify_news=False)
        mock_users_repo.update.return_value = MagicMock()
        mock_users_repo.get_by_id.return_value = updated_user

        result = await service.toggle_notification(42, "news", True, mock_redis)

        assert result is updated_user
        update_arg = mock_users_repo.update.call_args[0][1]
        assert update_arg.notify_news is False

    async def test_cache_invalidated(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """User cache is invalidated after toggle."""
        mock_users_repo.update.return_value = MagicMock()
        mock_users_repo.get_by_id.return_value = MagicMock()

        await service.toggle_notification(42, "publications", True, mock_redis)

        mock_redis.delete.assert_awaited_once_with("user:42")

    async def test_cache_invalidation_failure_tolerated(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Cache invalidation failure is tolerated (best-effort)."""
        mock_users_repo.update.return_value = MagicMock()
        mock_users_repo.get_by_id.return_value = MagicMock()
        mock_redis.delete = AsyncMock(side_effect=Exception("Redis down"))

        result = await service.toggle_notification(42, "balance", False, mock_redis)

        assert result is not None

    async def test_returns_none_when_user_disappears(
        self, service: UsersService, mock_users_repo: AsyncMock, mock_redis: MagicMock
    ) -> None:
        """Returns None if user disappears after update."""
        mock_users_repo.update.return_value = MagicMock()
        mock_users_repo.get_by_id.return_value = None

        result = await service.toggle_notification(42, "publications", True, mock_redis)

        assert result is None


# ---------------------------------------------------------------------------
# UsersService.get_referral_count
# ---------------------------------------------------------------------------


class TestGetReferralCount:
    async def test_returns_count(
        self, service: UsersService, mock_users_repo: AsyncMock
    ) -> None:
        """Delegates to UsersRepository.get_referral_count."""
        mock_users_repo.get_referral_count.return_value = 5

        result = await service.get_referral_count(42)

        assert result == 5
        mock_users_repo.get_referral_count.assert_awaited_once_with(42)

    async def test_returns_zero(
        self, service: UsersService, mock_users_repo: AsyncMock
    ) -> None:
        """Returns 0 when no referrals."""
        mock_users_repo.get_referral_count.return_value = 0

        result = await service.get_referral_count(42)

        assert result == 0
