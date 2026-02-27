"""Tests for UsersRepository — account deletion and anonymization methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from db.repositories.users import UsersRepository

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_db() -> MagicMock:
    """Mock SupabaseClient with chained table calls."""
    db = MagicMock()
    return db


@pytest.fixture
def repo(mock_db: MagicMock) -> UsersRepository:
    return UsersRepository(mock_db)


# ---------------------------------------------------------------------------
# anonymize_financial_records
# ---------------------------------------------------------------------------


class TestAnonymizeFinancialRecords:
    async def test_anonymize_updates_both_tables(
        self,
        repo: UsersRepository,
        mock_db: MagicMock,
    ) -> None:
        """Both token_expenses and payments are updated."""
        # Mock token_expenses update chain
        exp_chain = MagicMock()
        exp_chain.update.return_value = exp_chain
        exp_chain.eq.return_value = exp_chain
        exp_chain.execute = AsyncMock(return_value=MagicMock(data=[{"id": 1}, {"id": 2}]))

        # Mock payments update chain
        pay_chain = MagicMock()
        pay_chain.update.return_value = pay_chain
        pay_chain.eq.return_value = pay_chain
        pay_chain.execute = AsyncMock(return_value=MagicMock(data=[{"id": 3}]))

        mock_db.table = MagicMock(side_effect=lambda name: exp_chain if name == "token_expenses" else pay_chain)

        expenses, payments = await repo.anonymize_financial_records(user_id=123)

        assert expenses == 2
        assert payments == 1

    async def test_anonymize_no_records(
        self,
        repo: UsersRepository,
        mock_db: MagicMock,
    ) -> None:
        """Returns (0, 0) when user has no financial records."""
        chain = MagicMock()
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute = AsyncMock(return_value=MagicMock(data=[]))

        mock_db.table = MagicMock(return_value=chain)

        expenses, payments = await repo.anonymize_financial_records(user_id=999)

        assert expenses == 0
        assert payments == 0


# ---------------------------------------------------------------------------
# delete_user
# ---------------------------------------------------------------------------


class TestDeleteUser:
    async def test_delete_returns_true(
        self,
        repo: UsersRepository,
        mock_db: MagicMock,
    ) -> None:
        """Returns True when user row is deleted."""
        chain = MagicMock()
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute = AsyncMock(return_value=MagicMock(data=[{"id": 123}]))

        mock_db.table = MagicMock(return_value=chain)

        result = await repo.delete_user(123)
        assert result is True

    async def test_delete_returns_false_not_found(
        self,
        repo: UsersRepository,
        mock_db: MagicMock,
    ) -> None:
        """Returns False when user row not found."""
        chain = MagicMock()
        chain.delete.return_value = chain
        chain.eq.return_value = chain
        chain.execute = AsyncMock(return_value=MagicMock(data=[]))

        mock_db.table = MagicMock(return_value=chain)

        result = await repo.delete_user(999)
        assert result is False
