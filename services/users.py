"""User service — referral linking, account deletion, user-level business logic.

Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.users import UsersRepository
from services.scheduler import SchedulerService
from services.tokens import TokenService

log = structlog.get_logger()


@dataclass
class DeleteAccountResult:
    """Structured result of account deletion for logging and response."""

    success: bool = False
    schedules_cancelled: int = 0
    previews_refunded: int = 0
    expenses_anonymized: int = 0
    payments_anonymized: int = 0
    redis_keys_deleted: int = 0
    errors: list[str] = field(default_factory=list)


class UsersService:
    """Business logic for user operations.

    Thin router rule: routers call UsersService instead of
    accessing UsersRepository directly (CR-77b).
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._users = UsersRepository(db)

    async def link_referrer(
        self,
        user_id: int,
        referrer_id: int,
        redis: RedisClient,
    ) -> bool:
        """Link a referrer to a newly created user.

        Validates:
        - Not self-referral
        - Referrer exists

        On success: updates user.referrer_id, invalidates user cache.
        Returns True if referrer was linked, False otherwise.
        """
        if referrer_id == user_id:
            log.warning("referral_self_referral_blocked", user_id=user_id)
            return False

        referrer = await self._users.get_by_id(referrer_id)
        if not referrer:
            log.warning("referral_invalid_referrer", referrer_id=referrer_id)
            return False

        await self._users.update(user_id, UserUpdate(referrer_id=referrer_id))

        # Invalidate cached user so downstream sees referrer_id
        await redis.delete(CacheKeys.user_cache(user_id))

        log.info("referral_linked", user_id=user_id, referrer_id=referrer_id)
        return True

    async def toggle_notification(
        self,
        user_id: int,
        field: str,
        current_value: bool,
        redis: RedisClient,
    ) -> User | None:
        """Toggle a notification setting, invalidate cache, return refreshed user.

        Args:
            user_id: Telegram user ID.
            field: One of "publications", "balance", "news".
            current_value: Current boolean value of the field (will be negated).
            redis: Redis client for cache invalidation.

        Returns:
            Updated User or None if user disappeared.
        """
        if field == "publications":
            update = UserUpdate(notify_publications=not current_value)
        elif field == "balance":
            update = UserUpdate(notify_balance=not current_value)
        else:  # "news"
            update = UserUpdate(notify_news=not current_value)

        await self._users.update(user_id, update)

        # Invalidate user cache so next navigation shows fresh data (best-effort)
        try:
            await redis.delete(CacheKeys.user_cache(user_id))
        except Exception:
            log.warning("user_cache_invalidate_failed", user_id=user_id)

        return await self._users.get_by_id(user_id)

    async def get_referral_count(self, user_id: int) -> int:
        """Count users who have this user as referrer."""
        return await self._users.get_referral_count(user_id)

    async def delete_account(
        self,
        user_id: int,
        redis: RedisClient,
        scheduler_service: SchedulerService,
        admin_ids: list[int],
    ) -> DeleteAccountResult:
        """Delete user account and all associated data (152-FZ compliance).

        Execution order is CRITICAL due to FK constraints:
        1. Cancel QStash schedules (E11, E24) -- before CASCADE delete
        2. Refund active article previews (E42)
        3. Anonymize token_expenses and payments (NO ACTION FK)
        4. Delete user row (CASCADE: projects, categories, connections, etc.)
        5. Clear Redis keys (FSM, cache, pipeline checkpoint, rate limits)
        """
        result = DeleteAccountResult()

        # Step 1: Cancel all QStash schedules for all user projects
        projects = await ProjectsRepository(self._db).get_by_user(user_id)
        for project in projects:
            try:
                await scheduler_service.cancel_schedules_for_project(project.id)
                result.schedules_cancelled += 1
            except Exception:
                log.exception(
                    "delete_account_schedule_cancel_failed",
                    user_id=user_id,
                    project_id=project.id,
                )
                result.errors.append(f"schedule_cancel_project_{project.id}")

        log.info(
            "delete_account_step1_schedules",
            user_id=user_id,
            projects=len(projects),
            cancelled=result.schedules_cancelled,
        )

        # Step 2: Refund active article previews (E42)
        token_service = TokenService(db=self._db, admin_ids=admin_ids)
        previews_repo = PreviewsRepository(self._db)
        for project in projects:
            try:
                active_previews = await previews_repo.get_active_drafts_by_project(project.id)
                if active_previews:
                    count = await token_service.refund_active_previews(
                        active_previews,
                        user_id,
                        "account_deletion",
                    )
                    result.previews_refunded += count
            except Exception:
                log.exception(
                    "delete_account_preview_refund_failed",
                    user_id=user_id,
                    project_id=project.id,
                )
                result.errors.append(f"preview_refund_project_{project.id}")

        log.info(
            "delete_account_step2_previews",
            user_id=user_id,
            refunded=result.previews_refunded,
        )

        # Step 3: Anonymize financial records (token_expenses, payments)
        try:
            expenses, payments = await self._users.anonymize_financial_records(user_id)
            result.expenses_anonymized = expenses
            result.payments_anonymized = payments
        except Exception:
            log.exception("delete_account_anonymize_failed", user_id=user_id)
            result.errors.append("anonymize_financial")

        log.info(
            "delete_account_step3_anonymize",
            user_id=user_id,
            expenses=result.expenses_anonymized,
            payments=result.payments_anonymized,
        )

        # Step 4: Delete user row (CASCADE removes projects, categories, etc.)
        try:
            deleted = await self._users.delete_user(user_id)
            if not deleted:
                log.error("delete_account_user_not_found", user_id=user_id)
                result.errors.append("user_not_found")
                return result
        except Exception:
            log.exception("delete_account_delete_user_failed", user_id=user_id)
            result.errors.append("delete_user_row")
            return result

        log.info("delete_account_step4_user_deleted", user_id=user_id)

        # Step 5: Clear Redis keys (best-effort, non-blocking)
        result.redis_keys_deleted = await self._cleanup_redis(user_id, redis)

        log.info(
            "delete_account_step5_redis",
            user_id=user_id,
            keys_deleted=result.redis_keys_deleted,
        )

        result.success = True
        log.info(
            "delete_account_completed",
            user_id=user_id,
            schedules_cancelled=result.schedules_cancelled,
            previews_refunded=result.previews_refunded,
            expenses_anonymized=result.expenses_anonymized,
            payments_anonymized=result.payments_anonymized,
            redis_keys_deleted=result.redis_keys_deleted,
            errors=result.errors,
        )
        return result

    @staticmethod
    async def _cleanup_redis(user_id: int, redis: RedisClient) -> int:
        """Remove all Redis keys associated with the user. Best-effort."""
        deleted = 0
        # Known key patterns for this user
        known_keys = [
            CacheKeys.user_cache(user_id),
            CacheKeys.pipeline_state(user_id),
        ]
        for key in known_keys:
            try:
                deleted += await redis.delete(key)
            except Exception:
                log.warning("delete_account_redis_key_failed", key=key)

        # Scan-based cleanup for FSM and throttle keys
        for pattern in [f"fsm:{user_id}:*", f"throttle:{user_id}:*", f"rate:{user_id}:*"]:
            try:
                keys = await redis.scan_keys(pattern)
                if keys:
                    deleted += await redis.delete(*keys)
            except Exception:
                log.warning("delete_account_redis_scan_failed", pattern=pattern)

        return deleted
