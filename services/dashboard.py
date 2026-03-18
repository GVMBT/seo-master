"""Dashboard data aggregation service.

Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime

from pydantic import BaseModel

from bot.texts.emoji import E
from bot.texts.strings import (
    BALANCE_ESTIMATE,
    BALANCE_ESTIMATE_FULL,
    BALANCE_NEGATIVE,
    BALANCE_ZERO,
    FORECAST,
    LAST_PUB,
    NO_PROJECTS,
    NO_PROJECTS_HINT,
    WELCOME_HINT,
    WELCOME_TEXT,
    WELCOME_TITLE,
)
from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
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

# Average article cost for "~N articles" estimate (UX_PIPELINE.md section 2.5)
_AVG_ARTICLE_COST = 320
# Average social post cost for "~N posts" estimate
_AVG_SOCIAL_COST = 40


class LastPublication(BaseModel, frozen=True):
    """Most recent publication summary for dashboard."""

    keyword: str
    content_type: str
    created_at: datetime | None = None


class DashboardData(BaseModel, frozen=True):
    """Aggregated data for the Dashboard screen."""

    project_count: int
    category_count: int
    schedule_count: int
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
        """Aggregate dashboard data: projects, schedules, publications."""
        projects_repo = ProjectsRepository(self._db)
        pub_repo = PublicationsRepository(self._db)

        projects, pub_stats, last_pub_row = await asyncio.gather(
            projects_repo.get_by_user(user_id),
            pub_repo.get_stats_by_user(user_id),
            pub_repo.get_last_successful(user_id),
        )

        project_count = len(projects)
        project_ids = [p.id for p in projects]

        category_count = 0
        schedule_count = 0
        tokens_per_week = 0
        if project_count > 0:
            category_count, schedule_count, tokens_per_week = await self._get_schedule_stats(project_ids)

        last_pub = None
        if last_pub_row:
            last_pub = LastPublication(
                keyword=last_pub_row.keyword or "",
                content_type=last_pub_row.content_type,
                created_at=last_pub_row.created_at,
            )

        return DashboardData(
            project_count=project_count,
            category_count=category_count,
            schedule_count=schedule_count,
            total_publications=pub_stats.get("total_publications", 0),
            last_publication=last_pub,
            tokens_per_week=tokens_per_week,
            tokens_per_month=tokens_per_week * 4,
        )

    async def _get_schedule_stats(
        self,
        project_ids: list[int],
    ) -> tuple[int, int, int]:
        """Count categories, enabled schedules and compute weekly token forecast.

        Returns: (category_count, schedule_count, tokens_per_week).
        """
        cats_repo = CategoriesRepository(self._db)
        sched_repo = SchedulesRepository(self._db)

        cat_lists = await asyncio.gather(*(cats_repo.get_by_project(pid) for pid in project_ids))

        all_cats = [c for cats in cat_lists for c in cats]
        category_count = len(all_cats)
        all_cat_ids = [c.id for c in all_cats]
        if not all_cat_ids:
            return category_count, 0, 0

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

        return category_count, schedule_count, tokens_per_week

    @staticmethod
    def build_text(
        first_name: str,
        balance: int,
        is_new_user: bool,
        data: DashboardData,
    ) -> str:
        """Build Dashboard text based on user state (UX_PIPELINE.md section 2.1-2.3, 2.7)."""
        from bot.texts.screens import Screen

        name = html.escape(first_name or "")

        # Balance warning overrides (section 2.7)
        if balance < 0:
            return (
                Screen(E.WARNING, f"Баланс: {balance} токенов")
                .blank()
                .line(BALANCE_NEGATIVE.format(debt=abs(balance)))
                .build()
            )
        if balance == 0:
            return (
                Screen(E.WALLET, "Баланс: 0 токенов")
                .blank()
                .line(BALANCE_ZERO)
                .build()
            )

        if is_new_user and data.project_count == 0:
            articles_est = balance // _AVG_ARTICLE_COST
            name_part = ", " + name if name else ""
            return (
                Screen(E.ROCKET, WELCOME_TITLE)
                .blank()
                .line(WELCOME_TEXT.format(name_part=name_part))
                .blank()
                .line(
                    f"{E.WALLET} <b>Баланс: {_format_balance(balance)} токенов</b>"
                )
                .line(BALANCE_ESTIMATE.format(articles=articles_est))
                .hint(WELCOME_HINT)
                .build()
            )

        articles_est = balance // _AVG_ARTICLE_COST
        posts_est = balance // _AVG_SOCIAL_COST

        s = Screen(E.WALLET, f"Баланс: {_format_balance(balance)} токенов")
        s.line(BALANCE_ESTIMATE_FULL.format(articles=articles_est, posts=posts_est))
        s.blank()

        if data.project_count > 0:
            s.field(E.FOLDER, "Проектов", data.project_count)
            s.field(E.HASHTAG, "Категорий", data.category_count)
            s.field(E.SCHEDULE, "Расписаний", data.schedule_count)
            if data.total_publications > 0:
                s.field(E.ANALYTICS, "Публикаций", data.total_publications)

            # Last publication
            if data.last_publication and data.last_publication.keyword:
                lp = data.last_publication
                date_str = lp.created_at.strftime("%d.%m") if lp.created_at else ""
                kw_short = html.escape(
                    lp.keyword[:30] + "\u2026" if len(lp.keyword) > 30 else lp.keyword,
                )
                suffix = f" {date_str}" if date_str else ""
                s.blank()
                s.line(f"{E.DOC} " + LAST_PUB.format(keyword=kw_short, suffix=suffix))

            # Forecast
            if data.tokens_per_week > 0:
                s.separator()
                s.line(
                    f"{E.CHART} "
                    + FORECAST.format(
                        weekly=_format_balance(data.tokens_per_week),
                        monthly=_format_balance(data.tokens_per_month),
                    )
                )
        else:
            s.line(NO_PROJECTS)
            s.line(f"{E.ROCKET} " + NO_PROJECTS_HINT)

        return s.build()


def _format_balance(balance: int) -> str:
    """Format balance with space-separated thousands."""
    return f"{balance:,}".replace(",", " ")
