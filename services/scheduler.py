"""QStash schedule management service.

Creates/deletes/toggles QStash cron schedules for auto-publishing.
Also provides ownership-verified data loading for scheduler UI (H23 Phase 4).
Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import structlog
from qstash import QStash

from bot.exceptions import ScheduleError
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import (
    Category,
    PlatformConnection,
    PlatformSchedule,
    PlatformScheduleCreate,
    PlatformScheduleUpdate,
    Project,
)
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.schedules import SchedulesRepository
from services.tokens import estimate_article_cost, estimate_social_post_cost

log = structlog.get_logger()

# Cron DOW mapping per API_CONTRACTS.md §1.8
_DAY_MAP = {"mon": "1", "tue": "2", "wed": "3", "thu": "4", "fri": "5", "sat": "6", "sun": "0"}

_SOCIAL_PLATFORM_TYPES = {"telegram", "vk", "pinterest"}


@dataclass(frozen=True, slots=True)
class SchedulerContext:
    """Ownership-verified category + project pair."""

    category: Category
    project: Project


@dataclass(frozen=True, slots=True)
class ApplyScheduleResult:
    """Result of applying a schedule (preset or manual)."""

    connection: PlatformConnection
    weekly_cost: int


@dataclass(frozen=True, slots=True)
class CrosspostConfig:
    """Data needed to render cross-post configuration screen."""

    lead_connection: PlatformConnection
    social_connections: list[PlatformConnection]
    selected_ids: list[int]


@dataclass(frozen=True, slots=True)
class UpdateCrosspostResult:
    """Result of saving cross-post configuration."""

    count: int
    schedule: PlatformSchedule
    has_other_social: bool


class SchedulerService:
    """Manages QStash cron schedules and scheduler UI data loading."""

    def __init__(
        self,
        db: SupabaseClient,
        qstash_token: str,
        base_url: str,
        encryption_key: str = "",
    ) -> None:
        self._db = db
        self._qstash = QStash(token=qstash_token)
        self._base_url = base_url.rstrip("/")
        self._encryption_key = encryption_key
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
        days_cron = ",".join(_DAY_MAP.get(d, d) for d in schedule.schedule_days) if schedule.schedule_days else "*"

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
                sid = str(getattr(result, "schedule_id", None) or result)
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
        # Social auto-publish does not generate images
        if platform_type == "wordpress":
            cost_per_post = estimate_article_cost()
        else:
            cost_per_post = estimate_social_post_cost(images_count=0)
        return days * posts_per_day * cost_per_post

    # ------------------------------------------------------------------
    # Private helpers (H23 Phase 4)
    # ------------------------------------------------------------------

    async def verify_category_ownership(
        self,
        cat_id: int,
        user_id: int,
    ) -> SchedulerContext | None:
        """Load category -> project, verify ownership. Returns None if invalid."""
        cat = await CategoriesRepository(self._db).get_by_id(cat_id)
        if not cat:
            return None
        project = await ProjectsRepository(self._db).get_by_id(cat.project_id)
        if not project or project.user_id != user_id:
            return None
        return SchedulerContext(category=cat, project=project)

    def _conn_repo(self) -> ConnectionsRepository:
        """Create ConnectionsRepository with CredentialManager."""
        cm = CredentialManager(self._encryption_key)
        return ConnectionsRepository(self._db, cm)

    @staticmethod
    def _filter_social(conns: list[PlatformConnection]) -> list[PlatformConnection]:
        """Filter active social connections."""
        return [c for c in conns if c.platform_type in _SOCIAL_PLATFORM_TYPES and c.status == "active"]

    # ------------------------------------------------------------------
    # Data loading for scheduler UI (H23 Phase 4)
    # ------------------------------------------------------------------

    async def get_user_projects(self, user_id: int) -> list[Project]:
        """List all projects for user."""
        return await ProjectsRepository(self._db).get_by_user(user_id)

    async def get_project_categories(
        self,
        project_id: int,
        user_id: int,
    ) -> list[Category] | None:
        """List categories for an owned project. Returns None if not owned."""
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        if not project or project.user_id != user_id:
            return None
        return await CategoriesRepository(self._db).get_by_project(project_id)

    async def get_project_connections(
        self,
        project_id: int,
        user_id: int,
    ) -> list[PlatformConnection] | None:
        """List connections for an owned project. Returns None if not owned."""
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        if not project or project.user_id != user_id:
            return None
        return await self._conn_repo().get_by_project(project_id)

    async def get_social_connections(
        self,
        project_id: int,
        user_id: int,
    ) -> list[PlatformConnection] | None:
        """List active social connections for an owned project. Returns None if not owned."""
        conns = await self.get_project_connections(project_id, user_id)
        if conns is None:
            return None
        return self._filter_social(conns)

    async def get_social_connections_by_category(
        self,
        cat_id: int,
        user_id: int,
    ) -> list[PlatformConnection] | None:
        """List social connections resolving project from category. Returns None if not owned."""
        ctx = await self.verify_category_ownership(cat_id, user_id)
        if not ctx:
            return None
        conns = await self._conn_repo().get_by_project(ctx.project.id)
        return self._filter_social(conns)

    async def get_category_schedules_map(
        self,
        cat_id: int,
    ) -> dict[int, PlatformSchedule]:
        """Get schedules for category indexed by connection_id."""
        schedules = await self._schedules.get_by_category(cat_id)
        return {s.connection_id: s for s in schedules}

    # ------------------------------------------------------------------
    # Combined operations (H23 Phase 4)
    # ------------------------------------------------------------------

    async def apply_schedule(
        self,
        cat_id: int,
        conn_id: int,
        user_id: int,
        days: list[str],
        times: list[str],
        posts_per_day: int,
    ) -> ApplyScheduleResult | None:
        """Verify ownership, delete existing schedule, create new one.

        Returns ApplyScheduleResult with connection and weekly cost,
        or None if ownership/connection verification fails.
        """
        ctx = await self.verify_category_ownership(cat_id, user_id)
        if not ctx:
            return None

        conn = await self._conn_repo().get_by_id(conn_id)
        if not conn or conn.project_id != ctx.project.id:
            return None

        # Delete existing schedule for this category+connection
        existing = await self._schedules.get_by_category(cat_id)
        for s in existing:
            if s.connection_id == conn_id:
                await self.delete_schedule(s.id)

        await self.create_schedule(
            category_id=cat_id,
            connection_id=conn_id,
            platform_type=conn.platform_type,
            days=days,
            times=times,
            posts_per_day=posts_per_day,
            user_id=user_id,
            project_id=ctx.project.id,
            timezone=ctx.project.timezone or "UTC",
        )

        weekly_cost = self.estimate_weekly_cost(len(days), posts_per_day, conn.platform_type)
        return ApplyScheduleResult(connection=conn, weekly_cost=weekly_cost)

    async def disable_connection_schedule(
        self,
        cat_id: int,
        conn_id: int,
        user_id: int,
    ) -> bool:
        """Verify ownership and delete schedule for category+connection.

        Returns True if ownership valid (even if no schedule existed).
        """
        ctx = await self.verify_category_ownership(cat_id, user_id)
        if not ctx:
            return False

        existing = await self._schedules.get_by_category(cat_id)
        for s in existing:
            if s.connection_id == conn_id:
                await self.delete_schedule(s.id)
        return True

    async def has_active_schedule(self, cat_id: int, conn_id: int) -> bool:
        """Check if an active schedule exists for category+connection."""
        schedules = await self._schedules.get_by_category(cat_id)
        return any(s.connection_id == conn_id and s.enabled for s in schedules)

    async def get_crosspost_config(
        self,
        cat_id: int,
        conn_id: int,
        user_id: int,
    ) -> CrosspostConfig | None:
        """Load cross-post configuration data. Returns None if not owned."""
        ctx = await self.verify_category_ownership(cat_id, user_id)
        if not ctx:
            return None

        lead_conn = await self._conn_repo().get_by_id(conn_id)
        if not lead_conn:
            return None

        conns = await self._conn_repo().get_by_project(ctx.project.id)
        social_conns = self._filter_social(conns)

        schedules = await self._schedules.get_by_category(cat_id)
        existing = next((s for s in schedules if s.connection_id == conn_id), None)
        selected_ids = existing.cross_post_connection_ids if existing else []

        return CrosspostConfig(
            lead_connection=lead_conn,
            social_connections=social_conns,
            selected_ids=selected_ids,
        )

    async def update_crosspost(
        self,
        cat_id: int,
        conn_id: int,
        user_id: int,
        selected_ids: list[int],
    ) -> UpdateCrosspostResult | None:
        """Validate and save cross_post_connection_ids. Returns None if not owned."""
        ctx = await self.verify_category_ownership(cat_id, user_id)
        if not ctx:
            return None

        # Validate selected IDs belong to project's social connections
        conns = await self._conn_repo().get_by_project(ctx.project.id)
        social_conns = self._filter_social(conns)
        valid_ids = {c.id for c in social_conns}
        selected_ids = [cid for cid in selected_ids if cid in valid_ids]

        # Find existing schedule for this connection
        schedules = await self._schedules.get_by_category(cat_id)
        existing = next((s for s in schedules if s.connection_id == conn_id), None)
        if not existing:
            return None

        await self._schedules.update(
            existing.id,
            PlatformScheduleUpdate(cross_post_connection_ids=selected_ids),
        )

        return UpdateCrosspostResult(
            count=len(selected_ids),
            schedule=existing,
            has_other_social=len(social_conns) > 1,
        )
