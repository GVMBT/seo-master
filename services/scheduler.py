"""QStash schedule management service.

Creates/deletes/toggles QStash cron schedules for auto-publishing.
Zero dependencies on Telegram/Aiogram.
"""

import asyncio
import json

import structlog
from qstash import QStash

from bot.exceptions import ScheduleError
from db.client import SupabaseClient
from db.models import PlatformSchedule, PlatformScheduleCreate, PlatformScheduleUpdate
from db.repositories.categories import CategoriesRepository
from db.repositories.schedules import SchedulesRepository
from services.tokens import estimate_article_cost, estimate_social_post_cost

log = structlog.get_logger()

# Cron DOW mapping per API_CONTRACTS.md §1.8
_DAY_MAP = {"mon": "1", "tue": "2", "wed": "3", "thu": "4", "fri": "5", "sat": "6", "sun": "0"}


class SchedulerService:
    """Manages QStash cron schedules for auto-publishing."""

    def __init__(self, db: SupabaseClient, qstash_token: str, base_url: str) -> None:
        self._db = db
        self._qstash = QStash(token=qstash_token)
        self._base_url = base_url.rstrip("/")
        self._schedules = SchedulesRepository(db)

    async def create_qstash_schedules(
        self,
        schedule: PlatformSchedule,
        user_id: int,
        project_id: int,
        timezone: str,
    ) -> list[str]:
        """Create QStash cron schedules for each time slot.

        Returns list of QStash schedule IDs.
        Cron format: CRON_TZ={timezone} {min} {hour} * * {days}
        On partial failure, cleans up already-created schedules before raising.
        """
        schedule_ids: list[str] = []
        days_cron = (
            ",".join(_DAY_MAP.get(d, d) for d in schedule.schedule_days)
            if schedule.schedule_days
            else "*"
        )

        for time_slot in schedule.schedule_times:
            hour, minute = time_slot.split(":")
            cron = f"CRON_TZ={timezone} {int(minute)} {int(hour)} * * {days_cron}"

            body = {
                "schedule_id": schedule.id,
                "category_id": schedule.category_id,
                "connection_id": schedule.connection_id,
                "platform_type": schedule.platform_type,
                "user_id": user_id,
                "project_id": project_id,
                "idempotency_key": f"pub_{schedule.id}_{time_slot}",
            }

            try:
                result = await asyncio.to_thread(
                    self._qstash.schedule.create,
                    destination=f"{self._base_url}/api/publish",
                    cron=cron,
                    body=json.dumps(body),
                    headers={"Content-Type": "application/json"},
                )
                sid = result.schedule_id if hasattr(result, "schedule_id") else str(result)
                schedule_ids.append(sid)
                log.info(
                    "qstash_schedule_created",
                    schedule_id=schedule.id,
                    qstash_id=sid,
                    cron=cron,
                )
            except Exception as exc:
                log.exception("qstash_schedule_create_failed", schedule_id=schedule.id, cron=cron)
                # Clean up already-created schedules on partial failure
                if schedule_ids:
                    await self.delete_qstash_schedules(schedule_ids)
                raise ScheduleError(message=f"Failed to create QStash schedule: {cron}") from exc

        return schedule_ids

    async def delete_qstash_schedules(self, schedule_ids: list[str]) -> None:
        """Delete QStash schedules. Ignores 404 (already deleted)."""
        for sid in schedule_ids:
            try:
                await asyncio.to_thread(self._qstash.schedule.delete, sid)
                log.info("qstash_schedule_deleted", qstash_id=sid)
            except Exception:
                log.warning("qstash_schedule_delete_failed", qstash_id=sid, exc_info=True)

    async def toggle_schedule(
        self,
        schedule_id: int,
        enabled: bool,
        user_id: int,
        project_id: int,
        timezone: str,
    ) -> PlatformSchedule | None:
        """Enable or disable a schedule. Creates/deletes QStash accordingly."""
        schedule = await self._schedules.get_by_id(schedule_id)
        if not schedule:
            return None

        if enabled and not schedule.enabled:
            # Create QStash schedules
            qstash_ids = await self.create_qstash_schedules(schedule, user_id, project_id, timezone)
            return await self._schedules.update(
                schedule_id,
                PlatformScheduleUpdate(enabled=True, qstash_schedule_ids=qstash_ids, status="active"),
            )
        elif not enabled and schedule.enabled:
            # Delete QStash schedules
            await self.delete_qstash_schedules(schedule.qstash_schedule_ids)
            return await self._schedules.update(
                schedule_id,
                PlatformScheduleUpdate(enabled=False, qstash_schedule_ids=[], status="active"),
            )

        return schedule

    async def cancel_schedules_for_category(self, category_id: int) -> None:
        """Cancel all QStash schedules for a category (E24)."""
        schedules = await self._schedules.get_by_category(category_id)
        for s in schedules:
            if s.qstash_schedule_ids:
                await self.delete_qstash_schedules(s.qstash_schedule_ids)
                await self._schedules.update(
                    s.id,
                    PlatformScheduleUpdate(qstash_schedule_ids=[], enabled=False),
                )
        log.info("schedules_cancelled_for_category", category_id=category_id, count=len(schedules))

    async def cancel_schedules_for_project(self, project_id: int) -> None:
        """Cancel all QStash schedules for a project (E11)."""
        categories = await CategoriesRepository(self._db).get_by_project(project_id)
        cat_ids = [c.id for c in categories]
        if not cat_ids:
            return
        schedules = await self._schedules.get_by_project(cat_ids)
        for s in schedules:
            if s.qstash_schedule_ids:
                await self.delete_qstash_schedules(s.qstash_schedule_ids)
                await self._schedules.update(
                    s.id,
                    PlatformScheduleUpdate(qstash_schedule_ids=[], enabled=False),
                )
        log.info("schedules_cancelled_for_project", project_id=project_id, count=len(schedules))

    async def cancel_schedules_for_connection(self, connection_id: int) -> None:
        """Cancel all QStash schedules for a connection."""
        schedules = await self._schedules.get_by_connection(connection_id)
        for s in schedules:
            if s.qstash_schedule_ids:
                await self.delete_qstash_schedules(s.qstash_schedule_ids)
                await self._schedules.update(
                    s.id,
                    PlatformScheduleUpdate(qstash_schedule_ids=[], enabled=False),
                )
        log.info("schedules_cancelled_for_connection", connection_id=connection_id, count=len(schedules))

    async def create_schedule(
        self,
        category_id: int,
        connection_id: int,
        platform_type: str,
        days: list[str],
        times: list[str],
        posts_per_day: int,
        user_id: int,
        project_id: int,
        timezone: str,
    ) -> PlatformSchedule:
        """Create a new schedule with QStash cron jobs."""
        db_schedule = await self._schedules.create(
            PlatformScheduleCreate(
                category_id=category_id,
                platform_type=platform_type,
                connection_id=connection_id,
                schedule_days=days,
                schedule_times=times,
                posts_per_day=posts_per_day,
            )
        )

        try:
            qstash_ids = await self.create_qstash_schedules(db_schedule, user_id, project_id, timezone)
        except Exception:
            # Clean up orphaned DB row if QStash creation fails
            log.exception("qstash_schedule_creation_failed", schedule_id=db_schedule.id)
            await self._schedules.delete(db_schedule.id)
            raise
        updated = await self._schedules.update(
            db_schedule.id,
            PlatformScheduleUpdate(enabled=True, qstash_schedule_ids=qstash_ids, status="active"),
        )
        return updated or db_schedule

    async def delete_schedule(self, schedule_id: int) -> bool:
        """Delete schedule: cancel QStash first, then delete DB row."""
        schedule = await self._schedules.get_by_id(schedule_id)
        if not schedule:
            return False
        if schedule.qstash_schedule_ids:
            await self.delete_qstash_schedules(schedule.qstash_schedule_ids)
        return await self._schedules.delete(schedule_id)

    @staticmethod
    def estimate_weekly_cost(days: int, posts_per_day: int, platform_type: str) -> int:
        """Estimate weekly token cost for a schedule."""
        cost_per_post = estimate_article_cost() if platform_type == "wordpress" else estimate_social_post_cost()
        return days * posts_per_day * cost_per_post
