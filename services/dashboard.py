"""Dashboard data aggregation service.

Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from pydantic import BaseModel

from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from db.repositories.schedules import SchedulesRepository

# Average token cost per scheduled post, by platform type.
_PLATFORM_COST: dict[str, int] = {
    "wordpress": 320,
    "telegram": 40,
    "vk": 40,
    "pinterest": 40,
}
_DEFAULT_PLATFORM_COST = 40


class LastPublication(BaseModel, frozen=True):
    """Most recent publication summary for dashboard."""

    keyword: str
    content_type: str
    created_at: datetime


class DashboardData(BaseModel, frozen=True):
    """Aggregated data for the Dashboard screen."""

    project_count: int
    schedule_count: int
    has_wp: bool
    has_social: bool
    total_publications: int
    last_publication: LastPublication | None
    tokens_per_week: int
    tokens_per_month: int


class DashboardService:
    """Aggregates dashboard metrics from multiple repositories.

    Used by start.py _build_dashboard to replace direct repo calls.
    """

    def __init__(self, db: SupabaseClient, encryption_key: str = "") -> None:
        self._db = db
        self._encryption_key = encryption_key

    async def get_dashboard_data(self, user_id: int) -> DashboardData:
        """Aggregate dashboard data: projects, schedules, platform flags, publications."""
        projects_repo = ProjectsRepository(self._db)
        pub_repo = PublicationsRepository(self._db)

        projects, pub_stats, last_pubs = await asyncio.gather(
            projects_repo.get_by_user(user_id),
            pub_repo.get_stats_by_user(user_id),
            pub_repo.get_by_user(user_id, limit=1),
        )

        project_count = len(projects)
        project_ids = [p.id for p in projects]

        has_wp = False
        has_social = False
        schedule_count = 0
        tokens_per_week = 0
        if project_count > 0:
            (has_wp, has_social), (schedule_count, tokens_per_week) = await asyncio.gather(
                self._get_platform_flags(project_ids),
                self._get_schedule_stats(project_ids),
            )

        last_pub = None
        if last_pubs:
            lp = last_pubs[0]
            last_pub = LastPublication(
                keyword=lp.keyword or "",
                content_type=lp.content_type,
                created_at=lp.created_at or datetime.min,
            )

        return DashboardData(
            project_count=project_count,
            schedule_count=schedule_count,
            has_wp=has_wp,
            has_social=has_social,
            total_publications=pub_stats.get("total_publications", 0),
            last_publication=last_pub,
            tokens_per_week=tokens_per_week,
            tokens_per_month=tokens_per_week * 4,
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

        results = await asyncio.gather(*(conn_repo.get_platform_types_by_project(pid) for pid in project_ids))

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

    async def _get_schedule_stats(
        self,
        project_ids: list[int],
    ) -> tuple[int, int]:
        """Count enabled schedules and compute weekly token forecast.

        Returns: (schedule_count, tokens_per_week).
        """
        cats_repo = CategoriesRepository(self._db)
        sched_repo = SchedulesRepository(self._db)

        cat_lists = await asyncio.gather(*(cats_repo.get_by_project(pid) for pid in project_ids))

        all_cat_ids = [c.id for cats in cat_lists for c in cats]
        if not all_cat_ids:
            return 0, 0

        schedules = await sched_repo.get_by_project(all_cat_ids)

        schedule_count = 0
        tokens_per_week = 0
        for s in schedules:
            if s.enabled:
                schedule_count += 1
                days_count = len(s.schedule_days) if s.schedule_days else 7
                weekly_posts = s.posts_per_day * days_count
                avg_cost = _PLATFORM_COST.get(s.platform_type, _DEFAULT_PLATFORM_COST)
                tokens_per_week += weekly_posts * avg_cost

        return schedule_count, tokens_per_week
