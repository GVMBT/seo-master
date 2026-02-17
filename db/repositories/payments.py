"""Repository for payments and token_expenses tables."""

from db.models import (
    Payment,
    PaymentCreate,
    PaymentUpdate,
    TokenExpense,
    TokenExpenseCreate,
)
from db.repositories.base import BaseRepository

_PAYMENTS_TABLE = "payments"
_EXPENSES_TABLE = "token_expenses"


class PaymentsRepository(BaseRepository):
    """CRUD operations for payments + token_expenses tables."""

    # --- payments ---

    async def create(self, data: PaymentCreate) -> Payment:
        """Create a new payment record."""
        resp = await self._table(_PAYMENTS_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return Payment(**row)

    async def update(self, payment_id: int, data: PaymentUpdate) -> Payment | None:
        """Partial update of payment."""
        payload = data.model_dump(exclude_none=True)
        if not payload:
            return None
        resp = await self._table(_PAYMENTS_TABLE).update(payload).eq("id", payment_id).execute()
        row = self._first(resp)
        return Payment(**row) if row else None

    async def get_by_id(self, payment_id: int) -> Payment | None:
        """Get payment by ID."""
        resp = await self._table(_PAYMENTS_TABLE).select("*").eq("id", payment_id).maybe_single().execute()
        row = self._single(resp)
        return Payment(**row) if row else None

    async def get_by_user(self, user_id: int, limit: int = 20, offset: int = 0) -> list[Payment]:
        """Get payments for a user, newest first."""
        resp = (
            await self._table(_PAYMENTS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return [Payment(**row) for row in self._rows(resp)]

    async def get_active_subscription(self, user_id: int) -> Payment | None:
        """Get active subscription payment for a user."""
        resp = (
            await self._table(_PAYMENTS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("is_subscription", True)
            .eq("subscription_status", "active")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = self._rows(resp)
        return Payment(**rows[0]) if rows else None

    async def get_by_telegram_charge_id(self, charge_id: str) -> Payment | None:
        """Find payment by Telegram Stars charge ID (idempotency check, E06)."""
        resp = (
            await self._table(_PAYMENTS_TABLE)
            .select("*")
            .eq("telegram_payment_charge_id", charge_id)
            .maybe_single()
            .execute()
        )
        row = self._single(resp)
        return Payment(**row) if row else None

    async def get_by_yookassa_payment_id(self, payment_id: str) -> Payment | None:
        """Find payment by YooKassa payment ID (idempotency check)."""
        resp = (
            await self._table(_PAYMENTS_TABLE)
            .select("*")
            .eq("yookassa_payment_id", payment_id)
            .maybe_single()
            .execute()
        )
        row = self._single(resp)
        return Payment(**row) if row else None

    async def sum_revenue(self, days: int = 30) -> int:
        """Sum revenue (amount_rub) for completed payments within N days."""
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_PAYMENTS_TABLE)
            .select("amount_rub")
            .eq("status", "completed")
            .gte("created_at", cutoff)
            .execute()
        )
        rows = self._rows(resp)
        return sum(int(float(row.get("amount_rub") or 0)) for row in rows)

    async def get_expenses_summary(self, days: int = 7) -> dict[str, int]:
        """Aggregate token expenses by operation_type within N days."""
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = await self._table(_EXPENSES_TABLE).select("operation_type,amount").gte("created_at", cutoff).execute()
        summary: dict[str, int] = {}
        for row in self._rows(resp):
            op = row.get("operation_type", "unknown")
            amt = abs(int(row.get("amount", 0)))
            summary[op] = summary.get(op, 0) + amt
        return summary

    # --- token_expenses ---

    async def create_expense(self, data: TokenExpenseCreate) -> TokenExpense:
        """Create a token expense record."""
        resp = await self._table(_EXPENSES_TABLE).insert(data.model_dump()).execute()
        row = self._require_first(resp)
        return TokenExpense(**row)

    async def get_expenses_by_user(self, user_id: int, limit: int = 50, offset: int = 0) -> list[TokenExpense]:
        """Get token expenses for a user, newest first."""
        resp = (
            await self._table(_EXPENSES_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        return [TokenExpense(**row) for row in self._rows(resp)]

    async def sum_api_costs(self, days: int) -> float:
        """Sum API costs (cost_usd) for last N days. Admin use."""
        from datetime import UTC, datetime, timedelta
        from decimal import Decimal

        cutoff = (datetime.now(tz=UTC) - timedelta(days=days)).isoformat()
        resp = (
            await self._table(_EXPENSES_TABLE)
            .select("cost_usd")
            .gte("created_at", cutoff)
            .not_.is_("cost_usd", "null")
            .execute()
        )
        total = Decimal(0)
        for row in self._rows(resp):
            cost_val = row.get("cost_usd")
            if cost_val:
                total += Decimal(str(cost_val))
        return float(total)
