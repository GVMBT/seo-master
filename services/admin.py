"""Admin service — stats, monitoring, broadcast targeting, user lookup, user management.

Extracts UsersRepository + PaymentsRepository usage from routers/admin/dashboard.py.
Zero Telegram/Aiogram dependencies.

Source of truth: ARCHITECTURE.md section 2 ("routers -> services -> repositories").
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

import httpx
import structlog

from bot.exceptions import AppError
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import PublicationLog, TokenExpenseCreate, UserUpdate
from db.repositories.payments import PaymentsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from db.repositories.schedules import SchedulesRepository
from db.repositories.users import UsersRepository

log = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class AdminPanelStats:
    """Aggregated stats for admin panel main screen."""

    total_users: int
    paid_users: int
    total_projects: int
    revenue_30d: float
    publications_7d: int


@dataclass(frozen=True, slots=True)
class APIStatusReport:
    """Service health status with latency and credits info."""

    db_ok: bool
    db_latency_ms: int
    redis_ok: bool
    redis_latency_ms: int
    openrouter_ok: bool
    openrouter_credits: float | None
    qstash_ok: bool
    active_schedules: int


@dataclass(frozen=True, slots=True)
class UserCard:
    """User info card for admin user lookup."""

    user_id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    balance: int
    role: str
    projects_count: int
    publications_count: int
    last_activity: str | None
    created_at: str | None


@dataclass(frozen=True, slots=True)
class BalanceAdjustResult:
    """Result of admin balance adjustment."""

    new_balance: int
    expense_recorded: bool


class AdminService:
    """Admin-panel business logic.

    Provides ownership-free admin operations (callers must verify admin role).
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._users = UsersRepository(db)
        self._payments = PaymentsRepository(db)
        self._projects = ProjectsRepository(db)
        self._publications = PublicationsRepository(db)
        self._schedules = SchedulesRepository(db)

    async def get_user_count(self) -> int:
        """Count total registered users."""
        return await self._users.count_all()

    async def check_db_health(self) -> bool:
        """Quick health check: try a DB query. Returns True if OK."""
        try:
            await self._users.count_all()
            return True
        except Exception:
            log.exception("admin_db_health_check_failed")
            return False

    async def get_api_costs(self, days: int) -> float:
        """Sum API costs for the last N days."""
        return await self._payments.sum_api_costs(days)

    async def get_audience_ids(self, audience_key: str) -> list[int]:
        """Get user IDs for broadcast audience segmentation."""
        return await self._users.get_ids_by_audience(audience_key)

    async def get_panel_stats(self) -> AdminPanelStats:
        """Aggregated stats for admin panel (asyncio.gather for speed)."""
        total_users, paid_users, total_projects, revenue_30d, pubs_7d = await asyncio.gather(
            self._users.count_all(),
            self._users.count_paid(),
            self._projects.count_all(),
            self._payments.sum_api_costs(30),
            self._publications.count_recent(7),
        )
        return AdminPanelStats(
            total_users=total_users,
            paid_users=paid_users,
            total_projects=total_projects,
            revenue_30d=revenue_30d,
            publications_7d=pubs_7d,
        )

    async def get_api_status(
        self,
        redis: RedisClient,
        http_client: httpx.AsyncClient,
        openrouter_api_key: str,
        qstash_token: str,
    ) -> APIStatusReport:
        """Check all external services: DB, Redis, OpenRouter, QStash."""
        # DB check with latency
        db_ok = False
        t0 = time.monotonic()
        try:
            await self._users.count_all()
            db_ok = True
        except Exception:
            log.exception("admin_api_status_db_failed")
        db_latency_ms = round((time.monotonic() - t0) * 1000)

        # Redis check with latency
        redis_ok = False
        t0 = time.monotonic()
        try:
            redis_ok = await redis.ping()
        except Exception:
            log.exception("admin_api_status_redis_failed")
        redis_latency_ms = round((time.monotonic() - t0) * 1000)

        # OpenRouter credits check
        openrouter_ok = False
        openrouter_credits: float | None = None
        try:
            resp = await http_client.get(
                "https://openrouter.ai/api/v1/auth/key",
                headers={"Authorization": f"Bearer {openrouter_api_key}"},
                timeout=5.0,
            )
            if resp.status_code == 200:
                openrouter_ok = True
                data = resp.json().get("data", {})
                limit = data.get("limit")
                usage = data.get("usage", 0)
                if limit is not None:
                    openrouter_credits = round(limit - usage, 2)
        except Exception:
            log.warning("admin_api_status_openrouter_failed", exc_info=True)

        # QStash check + active schedules
        qstash_ok = False
        active_schedules = 0
        try:
            from qstash import QStash

            def _qstash_check() -> int:
                q = QStash(token=qstash_token)
                schedules = q.schedule.list()
                return len(schedules)

            active_schedules = await asyncio.to_thread(_qstash_check)
            qstash_ok = True
        except Exception:  # noqa: BLE001 — health check, any failure = service down
            log.warning("admin_api_status_qstash_failed", exc_info=True)
            with contextlib.suppress(Exception):
                active_schedules = await self._schedules.count_active()

        return APIStatusReport(
            db_ok=db_ok,
            db_latency_ms=db_latency_ms,
            redis_ok=redis_ok,
            redis_latency_ms=redis_latency_ms,
            openrouter_ok=openrouter_ok,
            openrouter_credits=openrouter_credits,
            qstash_ok=qstash_ok,
            active_schedules=active_schedules,
        )

    async def lookup_user(
        self,
        *,
        user_id: int | None = None,
        username: str | None = None,
    ) -> UserCard | None:
        """Find user by ID or username and build admin card."""
        user = None
        if user_id is not None:
            user = await self._users.get_by_id(user_id)
        elif username is not None:
            user = await self._users.get_by_username(username)

        if user is None:
            return None

        projects_count, publications_count = await asyncio.gather(
            self._projects.get_count_by_user(user.id),
            self._publications.count_by_user(user.id),
        )

        return UserCard(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            balance=user.balance,
            role=user.role,
            projects_count=projects_count,
            publications_count=publications_count,
            last_activity=str(user.last_activity) if user.last_activity else None,
            created_at=str(user.created_at) if user.created_at else None,
        )

    async def change_user_role(
        self,
        target_id: int,
        new_role: str,
        admin_ids: list[int],
        redis: RedisClient,
    ) -> str:
        """Change user role with safety checks. Returns new role."""
        _ALLOWED_ROLES = {"user", "blocked"}
        if new_role not in _ALLOWED_ROLES:
            raise AppError(f"Недопустимая роль: {new_role}")
        if target_id in admin_ids:
            raise AppError("Нельзя менять роль администратора")

        user = await self._users.get_by_id(target_id)
        if user is None:
            raise AppError("Пользователь не найден")

        await self._users.update(target_id, UserUpdate(role=new_role))
        # Invalidate user cache so middleware picks up the new role
        await redis.delete(CacheKeys.user_cache(target_id))

        log.info("admin_role_changed", target_id=target_id, new_role=new_role)
        return new_role

    async def adjust_balance(
        self,
        target_id: int,
        amount: int,
        is_credit: bool,
        admin_id: int,
        redis: RedisClient,
    ) -> BalanceAdjustResult:
        """Credit or debit user balance with audit trail."""
        if amount <= 0:
            raise AppError("Сумма должна быть положительным числом")
        user = await self._users.get_by_id(target_id)
        if user is None:
            raise AppError("Пользователь не найден")

        if is_credit:
            new_balance = await self._users.credit_balance(target_id, amount)
            op_type = "admin_credit"
        else:
            new_balance = await self._users.force_debit_balance(target_id, amount)
            op_type = "admin_debit"

        # Audit trail
        expense = TokenExpenseCreate(
            user_id=target_id,
            amount=amount if is_credit else -amount,
            operation_type=op_type,
            description=f"Admin #{admin_id}",
        )
        await self._payments.create_expense(expense)

        # Invalidate user cache
        await redis.delete(CacheKeys.user_cache(target_id))

        log.info(
            "admin_balance_adjusted",
            target_id=target_id,
            amount=amount,
            is_credit=is_credit,
            admin_id=admin_id,
            new_balance=new_balance,
        )
        return BalanceAdjustResult(new_balance=new_balance, expense_recorded=True)

    async def get_recent_publications(self, user_id: int, limit: int = 5) -> list[PublicationLog]:
        """Get recent publications for a user."""
        return await self._publications.get_by_user(user_id, limit=limit)
