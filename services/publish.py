"""Auto-publish service — triggered by QStash webhook.

Executes the full publish pipeline: load data, rotate keyword,
check balance, charge, generate, validate, publish, log.
Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import sentry_sdk
import structlog

from api.models import PublishPayload
from bot.config import get_settings
from bot.exceptions import InsufficientBalanceError
from cache.client import RedisClient
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformScheduleUpdate, PublicationLogCreate
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.publications import PublicationsRepository
from db.repositories.schedules import SchedulesRepository
from db.repositories.users import UsersRepository
from services.storage import ImageStorage
from services.tokens import TokenService, estimate_article_cost, estimate_social_post_cost

log = structlog.get_logger()


@dataclass
class PublishOutcome:
    """Result of auto-publish pipeline."""

    status: str  # "ok", "error", "skipped"
    reason: str = ""
    post_url: str = ""
    keyword: str = ""
    tokens_spent: int = 0
    user_id: int = 0
    notify: bool = False


class PublishService:
    """Auto-publish pipeline — called by QStash webhook handler."""

    def __init__(
        self,
        db: SupabaseClient,
        redis: RedisClient,
        http_client: object,
        ai_orchestrator: object,
        image_storage: ImageStorage,
        admin_id: int,
    ) -> None:
        self._db = db
        self._redis = redis
        self._http_client = http_client
        self._ai_orchestrator = ai_orchestrator
        self._image_storage = image_storage
        self._admin_id = admin_id
        self._tokens = TokenService(db, admin_id)
        self._users = UsersRepository(db)
        self._categories = CategoriesRepository(db)
        self._publications = PublicationsRepository(db)
        self._schedules = SchedulesRepository(db)

    async def execute(self, payload: PublishPayload) -> PublishOutcome:
        """Execute auto-publish pipeline.

        Flow: load data -> check connection -> check keywords (E17) ->
        rotate keyword (E22/E23) -> check balance (E01) -> charge ->
        generate -> publish -> log -> return.
        """
        user_id = payload.user_id

        # 1. Load user
        user = await self._users.get_by_id(user_id)
        if not user:
            return PublishOutcome(status="error", reason="user_not_found", user_id=user_id)

        # 2. Load category
        category = await self._categories.get_by_id(payload.category_id)
        if not category:
            return PublishOutcome(status="error", reason="category_not_found", user_id=user_id)

        # 3. Check keywords (E17: no keywords configured)
        if not category.keywords:
            log.warning("publish_no_keywords", category_id=payload.category_id, user_id=user_id)
            return PublishOutcome(status="error", reason="no_keywords", user_id=user_id)

        # 4. Load connection
        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        conn_repo = ConnectionsRepository(self._db, cm)
        connection = await conn_repo.get_by_id(payload.connection_id)
        if not connection or connection.status != "active":
            return PublishOutcome(status="error", reason="connection_inactive", user_id=user_id)

        # 5. Rotate keyword (E22/E23: low pool warning)
        content_type = "article" if payload.platform_type == "wordpress" else "social_post"
        keyword, low_pool = await self._publications.get_rotation_keyword(
            payload.category_id, category.keywords, content_type
        )
        if not keyword:
            log.warning("publish_no_available_keyword", category_id=payload.category_id)
            return PublishOutcome(status="error", reason="no_available_keyword", user_id=user_id)

        if low_pool:
            log.warning("publish_low_keyword_pool", category_id=payload.category_id, keyword=keyword)

        # 6. Estimate cost
        estimated_cost = estimate_article_cost() if content_type == "article" else estimate_social_post_cost()

        # 7. Check balance (E01)
        if not await self._tokens.check_balance(user_id, estimated_cost):
            log.warning("publish_insufficient_balance", user_id=user_id, required=estimated_cost)
            # P1-13: mark schedule as error to flag in UI
            await self._schedules.update(
                payload.schedule_id,
                PlatformScheduleUpdate(status="error"),
            )
            return PublishOutcome(
                status="error",
                reason="insufficient_balance",
                user_id=user_id,
                notify=user.notify_balance,
            )

        # 8. Charge tokens
        try:
            await self._tokens.charge(
                user_id, estimated_cost, f"auto_{content_type}", description=f"Auto-publish: {keyword}"
            )
        except InsufficientBalanceError:
            return PublishOutcome(status="error", reason="insufficient_balance", user_id=user_id)
        except Exception:
            log.exception("publish_charge_failed", user_id=user_id)
            return PublishOutcome(status="error", reason="charge_failed", user_id=user_id)

        # 9. Generate + publish (with refund on error)
        try:
            # TODO Phase 10: actual AI generation + publisher call
            # For now, log the intent (generation pipeline not yet integrated)
            log.info(
                "publish_pipeline_placeholder",
                user_id=user_id,
                keyword=keyword,
                platform=payload.platform_type,
                connection_id=payload.connection_id,
            )

            # Log publication
            pub_log = await self._publications.create_log(
                PublicationLogCreate(
                    user_id=user_id,
                    project_id=payload.project_id,
                    category_id=payload.category_id,
                    platform_type=payload.platform_type,
                    connection_id=payload.connection_id,
                    keyword=keyword,
                    content_type=content_type,
                    tokens_spent=estimated_cost,
                    status="success",
                )
            )

            # Update schedule last_post_at
            await self._schedules.update(
                payload.schedule_id,
                PlatformScheduleUpdate(last_post_at=datetime.now(tz=UTC)),
            )

            return PublishOutcome(
                status="ok",
                keyword=keyword,
                tokens_spent=estimated_cost,
                user_id=user_id,
                post_url=pub_log.post_url or "",
                notify=user.notify_publications,
            )

        except Exception as exc:
            # Refund on any error after charge
            log.exception("publish_generation_failed", user_id=user_id, keyword=keyword)
            try:
                await self._tokens.refund(user_id, estimated_cost, reason="auto_publish_error")
            except Exception:
                log.critical("refund_failed_after_charge", user_id=user_id, amount=estimated_cost)
                sentry_sdk.capture_exception(exc)

            # Log failed publication
            await self._publications.create_log(
                PublicationLogCreate(
                    user_id=user_id,
                    project_id=payload.project_id,
                    category_id=payload.category_id,
                    platform_type=payload.platform_type,
                    connection_id=payload.connection_id,
                    keyword=keyword,
                    content_type=content_type,
                    tokens_spent=0,
                    status="error",
                    error_message=str(exc)[:500],
                )
            )

            return PublishOutcome(status="error", reason=str(exc), user_id=user_id)
