"""Admin service — stats, monitoring, broadcast targeting, user lookup.

Extracts UsersRepository + PaymentsRepository usage from routers/admin/dashboard.py.
Zero Telegram/Aiogram dependencies.

Source of truth: ARCHITECTURE.md section 2 ("routers -> services -> repositories").
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from cache.client import RedisClient
from db.client import SupabaseClient
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
class MonitoringStatus:
    """Service health status for admin monitoring screen."""

    db_ok: bool
    redis_ok: bool
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
    created_at: str | None


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

    async def get_monitoring_status(self, redis: RedisClient) -> MonitoringStatus:
        """Check service health: DB, Redis, active QStash schedules."""
        db_ok, redis_ok, active_schedules = await asyncio.gather(
            self.check_db_health(),
            redis.ping(),
            self._schedules.count_active(),
        )
        return MonitoringStatus(
            db_ok=db_ok,
            redis_ok=redis_ok,
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

        projects_count = await self._projects.get_count_by_user(user.id)

        return UserCard(
            user_id=user.id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
            balance=user.balance,
            role=user.role,
            projects_count=projects_count,
            created_at=str(user.created_at) if user.created_at else None,
        )
