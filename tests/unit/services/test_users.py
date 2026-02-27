"""Tests for services/users.py — UsersService.

Covers: link_referrer (CR-77b) — self-referral, invalid referrer, success, cache invalidation.
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
