"""Repository for users table."""

from datetime import UTC, datetime, timedelta
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

        Primary path: RPC charge_balance (ARCHITECTURE.md section 5.5).
        Fallback (RPC unavailable only): retry loop with re-read to handle concurrent updates.
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

        # Fallback: retry loop with fresh balance read on each attempt.
        # Re-reading prevents writing a stale absolute value after concurrent changes.
        _MAX_RETRIES = 3
        for attempt in range(_MAX_RETRIES):
            user = await self.get_by_id(user_id)
            if user is None:
                raise AppError(f"User {user_id} not found")
            if user.balance < amount:
                msg = f"Недостаточно токенов. Нужно {amount}, у вас {user.balance}."
                raise InsufficientBalanceError(user_message=msg)
            new_balance = user.balance - amount
            rows = self._rows(
                await self._force_update_balance(user_id, user.balance, new_balance)
            )
            if rows:
                return int(rows[0]["balance"])
            log.info(
                "charge_balance_retry",
                user_id=user_id,
                attempt=attempt + 1,
                max_retries=_MAX_RETRIES,
            )
        # All retries exhausted — balance may have been drained concurrently
        raise InsufficientBalanceError(
            user_message=f"Не удалось списать {amount} токенов. Попробуйте ещё раз."
        )

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

    async def force_debit_balance(self, user_id: int, amount: int) -> int:
        """Deduct tokens, allowing negative balance (refund scenario).

        First tries charge_balance. On InsufficientBalanceError,
        forces the deduction anyway (balance may go negative).
        Per API_CONTRACTS.md §2.3: refund can produce negative balance.
        """
        try:
            return await self.charge_balance(user_id, amount)
        except InsufficientBalanceError:
            pass

        # Insufficient balance — force negative via CAS retry
        _MAX_RETRIES = 3
        for attempt in range(_MAX_RETRIES):
            user = await self.get_by_id(user_id)
            if not user:
                raise AppError(f"User {user_id} not found")
            new_balance = user.balance - amount
            rows = self._rows(
                await self._force_update_balance(user_id, user.balance, new_balance)
            )
            if rows:
                return int(rows[0]["balance"])
            log.info("force_debit_retry", user_id=user_id, attempt=attempt + 1)
        raise AppError(f"Force debit conflict after {_MAX_RETRIES} retries")

    async def _add_balance(self, fn_name: str, user_id: int, amount: int) -> int:
        """Shared implementation for refund_balance and credit_balance.

        Primary path: RPC (ARCHITECTURE.md section 5.5).
        Fallback (RPC unavailable only): CAS retry loop with fresh balance read.
        """
        try:
            result = await self._db.rpc(fn_name, {"p_user_id": user_id, "p_amount": amount})
            return self._extract_balance(result)
        except Exception:
            log.warning("rpc_unavailable", fn=fn_name, user_id=user_id, exc_info=True)

        # Fallback: CAS retry loop — re-read balance on each attempt to avoid stale writes.
        _MAX_RETRIES = 3
        for attempt in range(_MAX_RETRIES):
            user = await self.get_by_id(user_id)
            if not user:
                raise AppError(f"User {user_id} not found")
            new_balance = user.balance + amount
            rows = self._rows(
                await self._force_update_balance(user_id, user.balance, new_balance)
            )
            if rows:
                return int(rows[0]["balance"])
            log.info(
                "add_balance_retry",
                fn=fn_name,
                user_id=user_id,
                attempt=attempt + 1,
                max_retries=_MAX_RETRIES,
            )
        raise AppError(f"Balance update conflict after {_MAX_RETRIES} retries")

    async def _force_update_balance(
        self, user_id: int, expected_balance: int, new_balance: int
    ) -> Any:
        """Low-level CAS update for balance, bypassing UserUpdate model.

        This is intentionally private. All public balance mutations go through
        RPC functions; this is ONLY used as a fallback when RPC is unavailable.
        The `.eq("balance", expected_balance)` acts as a CAS guard.
        Returns raw PostgREST response (caller checks _rows for empty = CAS miss).
        """
        return await (
            self._table(_TABLE)
            .update({"balance": new_balance})
            .eq("id", user_id)
            .eq("balance", expected_balance)
            .execute()
        )

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

    async def get_low_balance_users(self, threshold: int = 100) -> list[User]:
        """Get users with balance below threshold and notify_balance=True."""
        resp = (
            await self._table(_TABLE)
            .select("*")
            .lt("balance", threshold)
            .eq("notify_balance", True)
            .execute()
        )
        return [User(**row) for row in self._rows(resp)]

    async def get_inactive_users(self, days: int = 14) -> list[User]:
        """Get users inactive for more than N days."""
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("*")
            .lt("last_activity", cutoff)
            .execute()
        )
        return [User(**row) for row in self._rows(resp)]

    async def get_active_users(self, days: int = 30) -> list[User]:
        """Get users active within the last N days."""
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("*")
            .gte("last_activity", cutoff)
            .execute()
        )
        return [User(**row) for row in self._rows(resp)]

    async def count_all(self) -> int:
        """Count all users."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .execute()
        )
        return self._count(resp)

    async def count_active(self, days: int = 7) -> int:
        """Count users active within the last N days."""
        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .gte("last_activity", cutoff)
            .execute()
        )
        return self._count(resp)

    async def get_ids_by_audience(self, audience: str) -> list[int]:
        """Get user IDs by audience type for broadcast.

        Audiences: all, active_7d, active_30d, paid.
        """
        if audience == "active_7d":
            users = await self.get_active_users(days=7)
            return [u.id for u in users]
        if audience == "active_30d":
            users = await self.get_active_users(days=30)
            return [u.id for u in users]
        if audience == "paid":
            # Users who have at least one payment
            resp = (
                await self._db.table("payments")
                .select("user_id")
                .eq("status", "completed")
                .execute()
            )
            rows = self._rows(resp)
            return sorted({int(row["user_id"]) for row in rows})
        # "all"
        resp = await self._table(_TABLE).select("id").execute()
        return [int(row["id"]) for row in self._rows(resp)]

    async def get_referral_count(self, user_id: int) -> int:
        """Count users who have this user as referrer."""
        resp = (
            await self._table(_TABLE)
            .select("id", count="exact")  # type: ignore[arg-type]
            .eq("referrer_id", user_id)
            .execute()
        )
        return self._count(resp)
