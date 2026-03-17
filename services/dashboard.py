"""Dashboard data aggregation service.

Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import asyncio
import html
from datetime import datetime

from pydantic import BaseModel

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


class LastPublication(BaseModel, frozen=True):
    """Most recent publication summary for dashboard."""

    keyword: str
    content_type: str
    created_at: datetime | None = None


class DashboardData(BaseModel, frozen=True):
    """Aggregated data for the Dashboard screen."""

    project_count: int
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

        schedule_count = 0
        tokens_per_week = 0
        if project_count > 0:
            schedule_count, tokens_per_week = await self._get_schedule_stats(project_ids)

        last_pub = None
        if last_pub_row:
            last_pub = LastPublication(
                keyword=last_pub_row.keyword or "",
                content_type=last_pub_row.content_type,
                created_at=last_pub_row.created_at,
            )

        return DashboardData(
            project_count=project_count,
            schedule_count=schedule_count,
            total_publications=pub_stats.get("total_publications", 0),
            last_publication=last_pub,
            tokens_per_week=tokens_per_week,
            tokens_per_month=tokens_per_week * 4,
        )

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

    @staticmethod
    def build_text(
        first_name: str,
        balance: int,
        is_new_user: bool,
        data: DashboardData,
    ) -> str:
        """Build Dashboard text based on user state (UX_PIPELINE.md section 2.1-2.3, 2.7)."""
        # Plain Unicode — text is used as edit_screen caption (no <tg-emoji>)
        name = html.escape(first_name or "")

        # Balance warning overrides (section 2.7)
        if balance < 0:
            return (
                f"\u26a0 <b>Баланс: {balance} токенов</b>\n\n"
                f"Долг {abs(balance)} токенов будет списан при следующей покупке.\n"
                "Для генерации контента пополните баланс."
            )
        if balance == 0:
            return "\U0001f4b0 <b>Баланс: 0 токенов</b>\n\nДля генерации контента нужно пополнить баланс."

        if is_new_user and data.project_count == 0:
            articles_est = balance // _AVG_ARTICLE_COST
            return (
                f"Привет{', ' + name if name else ''}! "
                "Я помогу создать и опубликовать SEO-контент.\n\n"
                f"\U0001f4b0 <b>Баланс: {_format_balance(balance)} токенов</b>"
                f" (~{articles_est} статей)\n\n"
                "Что хотите сделать?"
            )

        articles_est = balance // _AVG_ARTICLE_COST
        lines: list[str] = []

        # Balance
        lines.append(f"\U0001f4b0 <b>Баланс: {_format_balance(balance)} токенов</b> (~{articles_est} статей)")
        lines.append("")

        if data.project_count > 0:
            # Stats
            lines.append(
                f"\U0001f4c1 Проектов: {data.project_count}  \u00b7  "
                f"\U0001f4c5 Расписаний: {data.schedule_count}"
            )
            if data.total_publications > 0:
                lines.append(f"\U0001f4ca Публикаций: {data.total_publications}")

            # Last publication
            if data.last_publication and data.last_publication.keyword:
                lp = data.last_publication
                label = "Статья" if lp.content_type == "article" else "Пост"
                date_str = lp.created_at.strftime("%d.%m") if lp.created_at else ""
                kw_short = html.escape(
                    lp.keyword[:40] + "\u2026" if len(lp.keyword) > 40 else lp.keyword,
                )
                suffix = f" \u2014 {date_str}" if date_str else ""
                lines.append(f"\U0001f4c4 {label}: \u00ab{kw_short}\u00bb{suffix}")

            # Forecast
            if data.tokens_per_week > 0:
                lines.append("")
                lines.append(
                    f"\U0001f4c8 Расход: ~{_format_balance(data.tokens_per_week)}/нед"
                    f"  \u00b7  ~{_format_balance(data.tokens_per_month)}/мес"
                )
        else:
            lines.append("У вас пока нет проектов.")
            lines.append("\U0001f680 Создайте первый \u2014 это займёт 30 секунд.")

        return "\n".join(lines)


def _format_balance(balance: int) -> str:
    """Format balance with space-separated thousands."""
    return f"{balance:,}".replace(",", " ")
