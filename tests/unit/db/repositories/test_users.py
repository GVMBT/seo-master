"""Tests for db/repositories/users.py."""

import pytest

from bot.exceptions import AppError, InsufficientBalanceError
from db.models import User, UserCreate, UserUpdate
from db.repositories.users import UsersRepository

from .conftest import MockResponse, MockSupabaseClient


@pytest.fixture
def user_row() -> dict:
    return {
        "id": 123456789,
        "username": "testuser",
        "first_name": "Test",
        "last_name": "User",
        "balance": 1500,
        "language": "ru",
        "role": "user",
        "referrer_id": None,
        "notify_publications": True,
        "notify_balance": True,
        "notify_news": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "last_activity": None,
    }


@pytest.fixture
def repo(mock_db: MockSupabaseClient) -> UsersRepository:
    return UsersRepository(mock_db)  # type: ignore[arg-type]


class TestGetById:
    async def test_returns_user_when_found(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        mock_db.set_response("users", MockResponse(data=user_row))
        user = await repo.get_by_id(123456789)
        assert user is not None
        assert isinstance(user, User)
        assert user.id == 123456789
        assert user.username == "testuser"

    async def test_returns_none_when_not_found(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("users", MockResponse(data=None))
        user = await repo.get_by_id(999)
        assert user is None


class TestGetOrCreate:
    async def test_returns_existing_user_no_changes(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        mock_db.set_response("users", MockResponse(data=user_row))
        data = UserCreate(id=123456789, username="testuser", first_name="Test", last_name="User")
        user, is_new = await repo.get_or_create(data)
        assert isinstance(user, User)
        assert user.id == 123456789
        assert is_new is False

    async def test_updates_changed_fields(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        updated_row = {**user_row, "username": "newname"}
        # First call: get_by_id returns existing, second call: update returns updated
        mock_db.set_responses("users", [
            MockResponse(data=user_row),  # get_by_id (maybe_single)
            MockResponse(data=updated_row),  # update (no maybe_single)
        ])
        data = UserCreate(id=123456789, username="newname", first_name="Test", last_name="User")
        user, is_new = await repo.get_or_create(data)
        assert is_new is False
        assert user.username == "newname"

    async def test_creates_new_user(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # First call: get_by_id returns None, second call: insert returns new row
        mock_db.set_responses("users", [
            MockResponse(data=None),  # get_by_id (maybe_single) → None
            MockResponse(data=user_row),  # insert (no maybe_single) → [user_row]
        ])
        data = UserCreate(id=123456789, username="testuser", first_name="Test")
        user, is_new = await repo.get_or_create(data)
        assert isinstance(user, User)
        assert is_new is True
        assert user.id == 123456789

    async def test_never_overwrites_referrer_id(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        row_with_referrer = {**user_row, "referrer_id": 999}
        mock_db.set_response("users", MockResponse(data=row_with_referrer))
        data = UserCreate(id=123456789, username="testuser", first_name="Test", last_name="User")
        user, is_new = await repo.get_or_create(data)
        assert user.referrer_id == 999
        assert is_new is False


class TestUpdate:
    async def test_partial_update(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        updated_row = {**user_row, "language": "en"}
        mock_db.set_response("users", MockResponse(data=[updated_row]))
        user = await repo.update(123456789, UserUpdate(language="en"))
        assert user is not None
        assert user.language == "en"

    async def test_empty_update_returns_current(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        mock_db.set_response("users", MockResponse(data=user_row))
        user = await repo.update(123456789, UserUpdate())
        assert user is not None
        assert user.id == 123456789


class TestChargeBalance:
    async def test_rpc_success(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_rpc_response("charge_balance", [1000])
        result = await repo.charge_balance(123456789, 500)
        assert result == 1000

    async def test_rpc_success_dict_format(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        # PostgREST may return [{"charge_balance": 1000}]
        mock_db.set_rpc_response("charge_balance", [{"charge_balance": 1000}])
        result = await repo.charge_balance(123456789, 500)
        assert result == 1000

    async def test_rpc_insufficient_balance_raises(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        # Simulate PostgreSQL RAISE EXCEPTION 'insufficient_balance'
        mock_db._rpc_responses["charge_balance"] = None  # type: ignore[assignment]

        class FakeRPCError(Exception):
            def __str__(self) -> str:
                return "insufficient_balance"

        original_rpc = mock_db.rpc

        async def rpc_raise(fn_name: str, params: dict | None = None) -> list:
            if fn_name == "charge_balance":
                raise FakeRPCError()
            return await original_rpc(fn_name, params)

        mock_db.rpc = rpc_raise  # type: ignore[assignment]
        with pytest.raises(InsufficientBalanceError):
            await repo.charge_balance(123456789, 9999)

    async def test_fallback_success_first_attempt(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # No RPC configured -> fallback retry loop: first attempt succeeds
        charged_row = {**user_row, "balance": 1000}
        mock_db.set_responses("users", [
            MockResponse(data=user_row),            # get_by_id (attempt 1)
            MockResponse(data=[charged_row]),        # CAS update succeeds
        ])
        result = await repo.charge_balance(123456789, 500)
        assert result == 1000

    async def test_fallback_success_second_attempt(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # No RPC -> fallback: first CAS fails, second attempt succeeds
        charged_row = {**user_row, "balance": 1000}
        mock_db.set_responses("users", [
            MockResponse(data=user_row),            # get_by_id (attempt 1)
            MockResponse(data=[]),                   # CAS update fails (race)
            MockResponse(data=user_row),            # get_by_id (attempt 2)
            MockResponse(data=[charged_row]),        # CAS update succeeds
        ])
        result = await repo.charge_balance(123456789, 500)
        assert result == 1000

    async def test_fallback_insufficient_raises(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # No RPC configured, balance 1500 < 2000
        mock_db.set_response("users", MockResponse(data=user_row))
        with pytest.raises(InsufficientBalanceError):
            await repo.charge_balance(123456789, 2000)

    async def test_fallback_race_exhausts_retries(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # Fallback: all 3 CAS attempts fail (persistent concurrent conflict)
        mock_db.set_responses("users", [
            MockResponse(data=user_row),       # get_by_id (attempt 1)
            MockResponse(data=[]),             # CAS fails
            MockResponse(data=user_row),       # get_by_id (attempt 2)
            MockResponse(data=[]),             # CAS fails
            MockResponse(data=user_row),       # get_by_id (attempt 3)
            MockResponse(data=[]),             # CAS fails
        ])
        with pytest.raises(InsufficientBalanceError):
            await repo.charge_balance(123456789, 500)

    async def test_fallback_missing_user_raises(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("users", MockResponse(data=None))
        with pytest.raises(AppError, match="not found"):
            await repo.charge_balance(999, 100)


class TestRefundBalance:
    async def test_rpc_success(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_rpc_response("refund_balance", [1800])
        result = await repo.refund_balance(123456789, 300)
        assert result == 1800

    async def test_fallback_success(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # No RPC -> fallback CAS retry loop: first attempt succeeds
        refunded_row = {**user_row, "balance": 1800}
        mock_db.set_responses("users", [
            MockResponse(data=user_row),           # get_by_id (attempt 1)
            MockResponse(data=[refunded_row]),     # CAS update succeeds
        ])
        result = await repo.refund_balance(123456789, 300)
        assert result == 1800

    async def test_fallback_conflict_exhausts_retries(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # CAS conflict on all 3 attempts
        mock_db.set_responses("users", [
            MockResponse(data=user_row),   # get_by_id (attempt 1)
            MockResponse(data=[]),         # CAS fails
            MockResponse(data=user_row),   # get_by_id (attempt 2)
            MockResponse(data=[]),         # CAS fails
            MockResponse(data=user_row),   # get_by_id (attempt 3)
            MockResponse(data=[]),         # CAS fails
        ])
        with pytest.raises(AppError, match="conflict"):
            await repo.refund_balance(123456789, 300)

    async def test_fallback_success_on_retry(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # First CAS fails, second succeeds
        refunded_row = {**user_row, "balance": 1800}
        mock_db.set_responses("users", [
            MockResponse(data=user_row),           # get_by_id (attempt 1)
            MockResponse(data=[]),                  # CAS fails
            MockResponse(data=user_row),           # get_by_id (attempt 2)
            MockResponse(data=[refunded_row]),     # CAS succeeds
        ])
        result = await repo.refund_balance(123456789, 300)
        assert result == 1800

    async def test_fallback_missing_user_raises(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("users", MockResponse(data=None))
        with pytest.raises(AppError, match="not found"):
            await repo.refund_balance(999, 100)


class TestCreditBalance:
    async def test_rpc_success(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_rpc_response("credit_balance", [2500])
        result = await repo.credit_balance(123456789, 1000)
        assert result == 2500

    async def test_fallback_success(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        # No RPC -> fallback CAS retry loop: first attempt succeeds
        credited_row = {**user_row, "balance": 2500}
        mock_db.set_responses("users", [
            MockResponse(data=user_row),           # get_by_id (attempt 1)
            MockResponse(data=[credited_row]),     # CAS update succeeds
        ])
        result = await repo.credit_balance(123456789, 1000)
        assert result == 2500


class TestForceDebitBalance:
    async def test_uses_charge_if_balance_sufficient(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        """When balance >= amount, uses normal charge_balance."""
        mock_db.set_rpc_response("charge_balance", [500])
        result = await repo.force_debit_balance(123456789, 1000)
        assert result == 500

    async def test_forces_negative_on_insufficient(
        self, repo: UsersRepository, mock_db: MockSupabaseClient, user_row: dict
    ) -> None:
        """When InsufficientBalanceError, forces negative balance via CAS."""
        # RPC raises insufficient
        mock_db.set_rpc_error("charge_balance", "insufficient_balance")
        # Fallback: get_by_id → CAS update
        negative_row = {**user_row, "balance": -500}
        mock_db.set_responses("users", [
            MockResponse(data=user_row),            # get_by_id
            MockResponse(data=[negative_row]),       # CAS update succeeds
        ])
        result = await repo.force_debit_balance(123456789, 2000)
        assert result == -500


class TestExtractBalance:
    def test_scalar_int(self) -> None:
        assert UsersRepository._extract_balance(1500) == 1500

    def test_list_of_int(self) -> None:
        assert UsersRepository._extract_balance([1000]) == 1000

    def test_list_of_dict(self) -> None:
        # PostgREST wraps scalar RPC results as [{"function_name": value}]
        assert UsersRepository._extract_balance([{"charge_balance": 800}]) == 800

    def test_empty_list_raises(self) -> None:
        with pytest.raises(AppError, match="unexpected"):
            UsersRepository._extract_balance([])

    def test_none_raises(self) -> None:
        with pytest.raises(AppError, match="unexpected"):
            UsersRepository._extract_balance(None)


class TestGetReferralCount:
    async def test_returns_count(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("users", MockResponse(data=[], count=5))
        count = await repo.get_referral_count(123456789)
        assert count == 5

    async def test_returns_zero_when_none(
        self, repo: UsersRepository, mock_db: MockSupabaseClient
    ) -> None:
        mock_db.set_response("users", MockResponse(data=[], count=None))
        count = await repo.get_referral_count(123456789)
        assert count == 0
