"""Admin service — stats, monitoring, broadcast targeting.

Extracts UsersRepository + PaymentsRepository usage from routers/admin/dashboard.py.
Zero Telegram/Aiogram dependencies.

Source of truth: ARCHITECTURE.md section 2 ("routers -> services -> repositories").
"""

from __future__ import annotations

import structlog

from db.client import SupabaseClient
from db.repositories.payments import PaymentsRepository
from db.repositories.users import UsersRepository

log = structlog.get_logger()


class AdminService:
    """Admin-panel business logic.

    Provides ownership-free admin operations (callers must verify admin role).
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._users = UsersRepository(db)

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
        repo = PaymentsRepository(self._db)
        return await repo.sum_api_costs(days)

    async def get_audience_ids(self, audience_key: str) -> list[int]:
        """Get user IDs for broadcast audience segmentation."""
        return await self._users.get_ids_by_audience(audience_key)
