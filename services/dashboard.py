"""Dashboard data aggregation service.

Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel

from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.schedules import SchedulesRepository


class DashboardData(BaseModel, frozen=True):
    """Aggregated data for the Dashboard screen."""

    project_count: int
    schedule_count: int
    has_wp: bool
    has_social: bool


class DashboardService:
    """Aggregates dashboard metrics from multiple repositories.

    Used by start.py _build_dashboard to replace direct repo calls.
    """

    def __init__(self, db: SupabaseClient, encryption_key: str = "") -> None:
        self._db = db
        self._encryption_key = encryption_key

    async def get_dashboard_data(self, user_id: int) -> DashboardData:
        """Aggregate dashboard data: projects, schedules, platform flags."""
        projects_repo = ProjectsRepository(self._db)
        projects = await projects_repo.get_by_user(user_id)
        project_count = len(projects)
        project_ids = [p.id for p in projects]

        has_wp = False
        has_social = False
        schedule_count = 0
        if project_count > 0:
            (has_wp, has_social), schedule_count = await asyncio.gather(
                self._get_platform_flags(project_ids),
                self._count_active_schedules(project_ids),
            )

        return DashboardData(
            project_count=project_count,
            schedule_count=schedule_count,
            has_wp=has_wp,
            has_social=has_social,
        )

    async def _get_platform_flags(
        self,
        project_ids: list[int],
    ) -> tuple[bool, bool]:
        """Return (has_wp, has_social) across given projects.

        Uses asyncio.gather to fetch platform types for all projects in parallel.
        """
        cm = CredentialManager(self._encryption_key)
        conn_repo = ConnectionsRepository(self._db, cm)

        results = await asyncio.gather(
            *(conn_repo.get_platform_types_by_project(pid) for pid in project_ids)
        )

        has_wp = False
        has_social = False
        for ptypes in results:
            if "wordpress" in ptypes:
                has_wp = True
            if any(p in ptypes for p in ("telegram", "vk", "pinterest")):
                has_social = True
            if has_wp and has_social:
                break
        return has_wp, has_social

    async def _count_active_schedules(
        self,
        project_ids: list[int],
    ) -> int:
        """Count enabled schedules across given projects.

        Uses asyncio.gather to fetch categories for all projects in parallel.
        """
        cats_repo = CategoriesRepository(self._db)
        sched_repo = SchedulesRepository(self._db)

        cat_lists = await asyncio.gather(
            *(cats_repo.get_by_project(pid) for pid in project_ids)
        )

        all_cat_ids = [c.id for cats in cat_lists for c in cats]
        if not all_cat_ids:
            return 0

        schedules = await sched_repo.get_by_project(all_cat_ids)
        return sum(1 for s in schedules if s.enabled)
