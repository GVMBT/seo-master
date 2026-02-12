"""Repository for users table."""

from datetime import UTC, datetime
from typing import Any

import structlog

from bot.exceptions import AppError, InsufficientBalanceError
from db.models import User, UserCreate, UserUpdate
from db.repositories.base import BaseRepository

log = structlog.get_logger()

_TABLE = "users"


class UsersRepository(BaseRepository):
    """CRUD operations for users table."""

    async def get_by_id(self, user_id: int) -> User | None:
        """Get user by Telegram ID. Returns None if not found."""
        resp = await self._table(_TABLE).select("*").eq("id", user_id).maybe_single().execute()
        row = self._single(resp)
        return User(**row) if row else None

    async def get_or_create(self, data: UserCreate) -> tuple[User, bool]:
        """Get existing user or create new. Returns (user, is_new).

        On existing user: updates only username, first_name, last_name if changed.
        Never overwrites referrer_id, balance, role, or notification settings.
        """
        existing = await self.get_by_id(data.id)
        if existing is not None:
            # Update only Telegram-mutable fields if they changed
            changes: dict[str, str | None] = {}
            if data.username != existing.username:
                changes["username"] = data.username
            if data.first_name != existing.first_name:
                changes["first_name"] = data.first_name
            if data.last_name != existing.last_name:
                changes["last_name"] = data.last_name
            if changes:
                changes["last_activity"] = datetime.now(tz=UTC).isoformat()
                resp = await self._table(_TABLE).update(changes).eq("id", data.id).execute()
                row = self._first(resp)
                return (User(**row), False) if row else (existing, False)
            # No changes — still update activity
            await self.update_activity(data.id)
            return existing, False

        # New user — insert with all fields including referrer_id
        insert_data = data.model_dump()
        insert_data["last_activity"] = datetime.now(tz=UTC).isoformat()
        resp = await self._table(_TABLE).insert(insert_data).execute()
        row = self._require_first(resp)
        return User(**row), True

    async def update(self, user_id: int, data: UserUpdate) -> User | None:
        """Partial update. Returns None if user not found."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return await self.get_by_id(user_id)
        resp = await self._table(_TABLE).update(payload).eq("id", user_id).execute()
        row = self._first(resp)
        return User(**row) if row else None

    async def charge_balance(self, user_id: int, amount: int) -> int:
        """Atomically deduct tokens. Raises InsufficientBalanceError if balance < amount.

        Uses RPC charge_balance (ARCHITECTURE.md §5.5) with read-modify-write fallback.
        """
        try:
            result = await self._db.rpc(
                "charge_balance", {"p_user_id": user_id, "p_amount": amount}
            )
            return self._extract_balance(result)
        except InsufficientBalanceError:
            raise
        except Exception as exc:
            if "insufficient_balance" in str(exc):
                raise InsufficientBalanceError() from exc
            log.warning("rpc_unavailable", fn="charge_balance", user_id=user_id, exc_info=True)

        # Fallback: atomic update with balance guard
        user = await self.get_by_id(user_id)
        if user is None:
            raise AppError(f"User {user_id} not found")
        if user.balance < amount:
            msg = f"Недостаточно токенов. Нужно {amount}, у вас {user.balance}."  # noqa: RUF001
            raise InsufficientBalanceError(user_message=msg)
        resp = await (
            self._table(_TABLE)
            .update({"balance": user.balance - amount})
            .eq("id", user_id)
            .gte("balance", amount)
            .execute()
        )
        rows = self._rows(resp)
        if not rows:
            msg = f"Недостаточно токенов. Нужно {amount}, у вас {user.balance}."  # noqa: RUF001
            raise InsufficientBalanceError(user_message=msg)
        return int(rows[0]["balance"])

    async def refund_balance(self, user_id: int, amount: int) -> int:
        """Atomically return tokens (error recovery, cancellation).

        Uses RPC refund_balance (ARCHITECTURE.md §5.5) with fallback.
        """
        return await self._add_balance("refund_balance", user_id, amount)

    async def credit_balance(self, user_id: int, amount: int) -> int:
        """Atomically add tokens (purchase, referral bonus).

        Uses RPC credit_balance (ARCHITECTURE.md §5.5) with fallback.
        """
        return await self._add_balance("credit_balance", user_id, amount)

    async def _add_balance(self, fn_name: str, user_id: int, amount: int) -> int:
        """Shared implementation for refund_balance and credit_balance."""
        try:
            result = await self._db.rpc(fn_name, {"p_user_id": user_id, "p_amount": amount})
            return self._extract_balance(result)
        except Exception:
            log.warning("rpc_unavailable", fn=fn_name, user_id=user_id, exc_info=True)

        # Fallback: optimistic CAS (compare-and-swap) on balance
        user = await self.get_by_id(user_id)
        if not user:
            raise AppError(f"User {user_id} not found")
        new_balance = user.balance + amount
        resp = await (
            self._table(_TABLE)
            .update({"balance": new_balance})
            .eq("id", user_id)
            .eq("balance", user.balance)
            .execute()
        )
        rows = self._rows(resp)
        if not rows:
            raise AppError("Balance update conflict, retry required")
        return int(rows[0]["balance"])

    @staticmethod
    def _extract_balance(rpc_result: Any) -> int:
        """Extract integer balance from RPC result.

        PostgREST may return:
        - int directly (scalar)
        - [int] (single-element list)
        - [{"function_name": int}] (wrapped scalar)
        """
        if isinstance(rpc_result, int):
            return rpc_result
        if isinstance(rpc_result, list) and rpc_result:
            val = rpc_result[0]
            if isinstance(val, int):
                return val
            if isinstance(val, dict):
                return int(next(iter(val.values())))
            return int(val)
        raise AppError("Balance RPC returned unexpected result")

    async def update_activity(self, user_id: int) -> None:
        """Update last_activity timestamp to current UTC time."""
        now = datetime.now(tz=UTC).isoformat()
        await self._table(_TABLE).update({"last_activity": now}).eq("id", user_id).execute()

    async def get_referral_count(self, user_id: int) -> int:
        """Count users who have this user as referrer."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("referrer_id", user_id)
            .execute()
        )
        return self._count(resp)
