"""Tests for services/notifications.py — notification batch builder."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from db.models import User
from services.notifications import NotifyService

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_user(**overrides) -> User:
    defaults = {
        "id": 1,
        "balance": 50,
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
        "last_activity": datetime.now(tz=UTC),
    }
    defaults.update(overrides)
    return User(**defaults)


def _make_service() -> NotifyService:
    return NotifyService(db=MagicMock())


# ---------------------------------------------------------------------------
# low_balance
# ---------------------------------------------------------------------------


async def test_low_balance_returns_users() -> None:
    """Users below threshold with notify_balance=True are included."""
    svc = _make_service()
    svc._users.get_low_balance_users = AsyncMock(
        return_value=[
            _make_user(id=1, balance=50),
            _make_user(id=2, balance=80),
        ]
    )

    result = await svc.build_low_balance(threshold=100)

    assert len(result) == 2
    assert result[0][0] == 1
    assert "50 токенов" in result[0][1]


async def test_low_balance_empty() -> None:
    """No users below threshold returns empty list."""
    svc = _make_service()
    svc._users.get_low_balance_users = AsyncMock(return_value=[])

    result = await svc.build_low_balance()
    assert result == []


# ---------------------------------------------------------------------------
# weekly_digest
# ---------------------------------------------------------------------------


@patch("services.notifications.PublicationsRepository")
async def test_weekly_digest_builds(mock_pubs_cls: MagicMock) -> None:
    """Active users with notify_news get digest (H24: batch query)."""
    svc = _make_service()
    svc._users.get_active_users = AsyncMock(
        return_value=[
            _make_user(id=1, notify_news=True, balance=500),
        ]
    )

    mock_pubs = MagicMock()
    # H24: batch method returns {user_id: count}
    mock_pubs.get_stats_by_users_batch = AsyncMock(return_value={1: 42})
    mock_pubs_cls.return_value = mock_pubs

    result = await svc.build_weekly_digest()

    assert len(result) == 1
    assert "42" in result[0][1]
    assert "500 токенов" in result[0][1]


@patch("services.notifications.PublicationsRepository")
async def test_weekly_digest_skips_notify_off(mock_pubs_cls: MagicMock) -> None:
    """Users with notify_news=False are skipped."""
    svc = _make_service()
    svc._users.get_active_users = AsyncMock(
        return_value=[
            _make_user(id=1, notify_news=False),
        ]
    )

    result = await svc.build_weekly_digest()
    assert result == []


# ---------------------------------------------------------------------------
# reactivation
# ---------------------------------------------------------------------------


async def test_reactivation_returns_inactive() -> None:
    """Inactive users (>14 days) get reactivation message."""
    svc = _make_service()
    svc._users.get_inactive_users = AsyncMock(
        return_value=[
            _make_user(id=1, balance=200, last_activity=datetime.now(tz=UTC) - timedelta(days=20)),
        ]
    )

    result = await svc.build_reactivation()

    assert len(result) == 1
    assert "200 токенов" in result[0][1]
    assert "скучаем" in result[0][1].lower()


async def test_reactivation_empty() -> None:
    """No inactive users returns empty list."""
    svc = _make_service()
    svc._users.get_inactive_users = AsyncMock(return_value=[])

    result = await svc.build_reactivation()
    assert result == []
