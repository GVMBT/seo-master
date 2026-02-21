"""Auto-publish service — triggered by QStash webhook.

Executes the full publish pipeline: load data, rotate keyword,
check balance, charge, generate, validate, publish, log.
Parallel pipeline: text + images via asyncio.gather (96s→56s).
Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import sentry_sdk
import structlog

from api.models import PublishPayload
from bot.config import get_settings
from bot.exceptions import InsufficientBalanceError
from cache.client import RedisClient
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformScheduleUpdate, PublicationLogCreate
from db.repositories.audits import AuditsRepository
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.publications import PublicationsRepository
from db.repositories.schedules import SchedulesRepository
from db.repositories.users import UsersRepository
from services.ai.orchestrator import AIOrchestrator
from services.publishers.base import PublishRequest, PublishResult
from services.storage import ImageStorage
from services.tokens import TokenService, estimate_article_cost, estimate_cross_post_cost, estimate_social_post_cost

if TYPE_CHECKING:
    import httpx

    from services.scheduler import SchedulerService

log = structlog.get_logger()


@dataclass
class CrossPostResult:
    """Result of a single cross-post attempt."""

    connection_id: int
    platform: str
    status: str  # "ok", "error"
    post_url: str = ""
    error: str = ""
    tokens_spent: int = 0


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
    cross_post_results: list[CrossPostResult] = dataclasses_field(default_factory=list)


class PublishService:
    """Auto-publish pipeline — called by QStash webhook handler."""

    def __init__(
        self,
        db: SupabaseClient,
        redis: RedisClient,
        http_client: httpx.AsyncClient,
        ai_orchestrator: AIOrchestrator,
        image_storage: ImageStorage,
        admin_ids: list[int],
        scheduler_service: SchedulerService | None = None,
    ) -> None:
        self._db = db
        self._redis = redis
        self._http_client = http_client
        self._ai_orchestrator = ai_orchestrator
        self._image_storage = image_storage
        self._admin_ids = admin_ids
        self._scheduler_service = scheduler_service
        self._tokens = TokenService(db, admin_ids)
        self._users = UsersRepository(db)
        self._categories = CategoriesRepository(db)
        self._projects = ProjectsRepository(db)
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
            return PublishOutcome(
                status="error",
                reason="no_keywords",
                user_id=user_id,
                notify=user.notify_publications,
            )

        # 4. Load connection
        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        conn_repo = ConnectionsRepository(self._db, cm)
        connection = await conn_repo.get_by_id(payload.connection_id)
        if not connection or connection.status != "active":
            return PublishOutcome(
                status="error",
                reason="connection_inactive",
                user_id=user_id,
                notify=user.notify_publications,
            )

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

        # 7. Check balance (E01): pause schedule per EDGE_CASES.md
        if not await self._tokens.check_balance(user_id, estimated_cost):
            await self._pause_schedule_insufficient_balance(payload.schedule_id, user_id, estimated_cost)
            return PublishOutcome(
                status="error",
                reason="insufficient_balance",
                user_id=user_id,
                notify=user.notify_publications,
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

        # 9-10. Generate, publish, log, cross-post (with refund on error)
        return await self._publish_and_log(
            payload=payload,
            user=user,
            category=category,
            connection=connection,
            keyword=keyword,
            content_type=content_type,
            estimated_cost=estimated_cost,
        )

    async def _publish_and_log(
        self,
        payload: PublishPayload,
        user: Any,
        category: Any,
        connection: Any,
        keyword: str,
        content_type: str,
        estimated_cost: int,
    ) -> PublishOutcome:
        """Generate content, publish, log result, and execute cross-posts."""
        user_id = payload.user_id
        try:
            gen_result, pub_result, failed_images = await self._generate_and_publish(
                user_id=user_id,
                project_id=payload.project_id,
                category_id=payload.category_id,
                keyword=keyword,
                connection=connection,
                content_type=content_type,
                category=category,
            )

            # E34: refund for failed images (30 tokens per image)
            if failed_images > 0:
                image_refund = failed_images * 30
                try:
                    await self._tokens.refund(user_id, image_refund, reason="failed_images")
                    log.info("image_refund", user_id=user_id, failed=failed_images, refund=image_refund)
                except Exception:
                    log.warning("image_refund_failed", user_id=user_id, amount=image_refund)

            # Log publication
            images_count = 0
            if gen_result and isinstance(gen_result.content, dict):
                images_count = len(gen_result.content.get("images_meta", []))

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
                    images_count=images_count,
                    status="success",
                    post_url=pub_result.post_url or "",
                )
            )

            # Update schedule last_post_at
            await self._schedules.update(
                payload.schedule_id,
                PlatformScheduleUpdate(last_post_at=datetime.now(tz=UTC)),
            )

            # Execute cross-posts if configured (social posts only)
            cross_results: list[CrossPostResult] = []
            schedule = await self._schedules.get_by_id(payload.schedule_id)
            if (
                schedule
                and schedule.cross_post_connection_ids
                and payload.platform_type != "wordpress"
            ):
                lead_text = ""
                if isinstance(gen_result.content, dict):
                    lead_text = gen_result.content.get("text", "")
                if not lead_text:
                    log.warning(
                        "cross_post_skipped_empty_text",
                        schedule_id=payload.schedule_id,
                        platform=payload.platform_type,
                    )
                if lead_text:
                    cross_results = await self._execute_cross_posts(
                        user_id=user_id,
                        schedule=schedule,
                        keyword=keyword,
                        lead_text=lead_text,
                        lead_platform=payload.platform_type,
                        project_id=payload.project_id,
                        category_id=payload.category_id,
                    )

            total_cost = estimated_cost + sum(
                cr.tokens_spent for cr in cross_results if cr.tokens_spent
            )
            return PublishOutcome(
                status="ok",
                keyword=keyword,
                tokens_spent=total_cost,
                user_id=user_id,
                post_url=pub_log.post_url or "",
                notify=user.notify_publications,
                cross_post_results=cross_results,
            )

        except Exception as exc:
            log.exception("publish_generation_failed", user_id=user_id, keyword=keyword)
            try:
                await self._tokens.refund(user_id, estimated_cost, reason="auto_publish_error")
            except Exception as refund_exc:
                log.critical("refund_failed_after_charge", user_id=user_id, amount=estimated_cost)
                sentry_sdk.capture_exception(refund_exc)

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

    async def _pause_schedule_insufficient_balance(
        self,
        schedule_id: int,
        user_id: int,
        required: int,
    ) -> None:
        """E01: Disable schedule + delete QStash crons on insufficient balance."""
        log.warning("publish_insufficient_balance", user_id=user_id, required=required)
        schedule = await self._schedules.get_by_id(schedule_id)
        if schedule and schedule.qstash_schedule_ids and self._scheduler_service:
            await self._scheduler_service.delete_qstash_schedules(schedule.qstash_schedule_ids)
        await self._schedules.update(
            schedule_id,
            PlatformScheduleUpdate(status="error", enabled=False, qstash_schedule_ids=[]),
        )

    async def _generate_and_publish(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        connection: Any,
        content_type: str,
        category: Any,
    ) -> tuple[Any, PublishResult, int]:
        """Generate content + images in parallel, then publish.

        For articles: text and images are generated concurrently via asyncio.gather.
        For social posts: text generated first, then published with optional image.
        Returns (gen_result, pub_result, failed_image_count).
        """
        if content_type == "article":
            return await self._generate_article_parallel(
                user_id,
                project_id,
                category_id,
                keyword,
                connection,
                category,
            )

        result, pub = await self._generate_social_post(
            user_id,
            project_id,
            category_id,
            keyword,
            connection,
            category,
        )
        return result, pub, 0

    async def _generate_article_parallel(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        connection: Any,
        category: Any,
    ) -> tuple[Any, PublishResult, int]:
        """Parallel article pipeline: text + images via asyncio.gather (96s→56s).

        Returns (gen_result, pub_result, failed_image_count).
        """
        from services.ai.articles import ArticleService
        from services.ai.images import ImageService
        from services.publishers.wordpress import WordPressPublisher

        article_service = ArticleService(self._ai_orchestrator, self._db)
        image_service = ImageService(self._ai_orchestrator)
        publisher = WordPressPublisher(self._http_client)

        image_count = (category.image_settings or {}).get("count", 4)
        image_context: dict[str, Any] = {
            "keyword": keyword,
            "content_type": "article",
            "company_name": "",
            "specialization": "",
        }
        # Load project for company info
        project = await self._projects.get_by_id(project_id)
        if project:
            image_context["company_name"] = project.company_name or ""
            image_context["specialization"] = project.specialization or ""

        # Parallel: text + images
        text_task = article_service.generate(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
        )
        image_task = image_service.generate(
            user_id=user_id,
            context=image_context,
            count=image_count,
        )

        text_result, image_result = await asyncio.gather(text_task, image_task, return_exceptions=True)

        if isinstance(text_result, BaseException):
            raise text_result

        # Extract text content
        content_markdown = ""
        title = keyword
        meta_desc = ""
        images_meta: list[dict[str, str]] = []
        if isinstance(text_result.content, dict):
            content_markdown = text_result.content.get("content_markdown", "")
            title = text_result.content.get("title", keyword)
            meta_desc = text_result.content.get("meta_description", "")
            images_meta = text_result.content.get("images_meta", [])

        # Collect raw images (bytes or exceptions) for reconciliation
        raw_images: list[bytes | BaseException] = []
        failed_images = 0
        if isinstance(image_result, BaseException):
            log.warning("image_generation_failed", error=str(image_result))
            failed_images = image_count  # all images failed
        elif image_result:
            raw_images = [img.data for img in image_result]
            failed_images = image_count - len(image_result)
        else:
            failed_images = image_count

        # Validate images_meta before reconciliation (API_CONTRACTS.md §3.7)
        from services.ai.content_validator import ContentValidator

        validator = ContentValidator()
        meta_validation = validator.validate_images_meta(
            images_meta=images_meta,
            expected_count=image_count,
            main_phrase=keyword,
        )
        if meta_validation.warnings:
            log.warning("images_meta_validation_warnings", warnings=meta_validation.warnings)

        # Reconcile images with text (E32-E35)
        from services.ai.reconciliation import reconcile_images

        processed_md, uploads = reconcile_images(
            content_markdown=content_markdown,
            images_meta=images_meta,
            generated_images=raw_images,
            title=title,
        )

        # Re-render HTML from reconciled markdown (not pre-reconciliation content_html)
        # to ensure {{IMAGE_N}} placeholders are removed from final HTML.
        from services.ai.markdown_renderer import render_markdown

        branding_dict: dict[str, str] = {}
        audits_repo = AuditsRepository(self._db)
        branding = await audits_repo.get_branding_by_project(project_id)
        if branding and branding.colors:
            branding_dict = {
                "text": branding.colors.get("text", ""),
                "accent": branding.colors.get("accent", ""),
            }
        content_html = render_markdown(processed_md, branding=branding_dict, insert_toc=True)

        # Sanitize re-rendered HTML via nh3 (ARCHITECTURE.md §5.8)
        from services.ai.articles import sanitize_html

        content_html = sanitize_html(content_html)

        pub_result = await publisher.publish(
            PublishRequest(
                connection=connection,
                content=content_html,
                content_type="html",
                title=title,
                images=[u.data for u in uploads],
                images_meta=[{"alt": u.alt_text, "filename": u.filename, "figcaption": u.caption} for u in uploads],
                category=category,
                metadata={"seo_description": meta_desc, "focus_keyword": keyword},
            )
        )

        if not pub_result.success:
            raise RuntimeError(f"Publish failed: {pub_result.error}")

        return text_result, pub_result, failed_images

    async def _generate_social_post(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        connection: Any,
        category: Any,
    ) -> tuple[Any, PublishResult]:
        """Generate social post and publish."""
        from services.ai.social_posts import SocialPostService

        social_service = SocialPostService(self._ai_orchestrator, self._db)
        result = await social_service.generate(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            platform=connection.platform_type,
        )

        publisher = self._get_publisher(connection.platform_type)
        # Social post content is a dict {text, hashtags, pin_title} — extract text
        content = result.content.get("text", "") if isinstance(result.content, dict) else result.content

        # Validate content before publishing (placeholder detection + platform limits)
        from services.ai.content_validator import ContentValidator

        validator = ContentValidator()
        validation = validator.validate(content, "social_post", connection.platform_type)
        if not validation.is_valid:
            raise RuntimeError(f"Social post validation failed: {'; '.join(validation.errors)}")
        if validation.warnings:
            log.warning("social_post_validation_warnings", warnings=validation.warnings)
        ct: Literal["html", "telegram_html", "plain_text", "pin_text"] = self._get_content_type(
            connection.platform_type
        )  # type: ignore[assignment]

        pub_result = await publisher.publish(
            PublishRequest(
                connection=connection,
                content=content,
                content_type=ct,
                category=category,
            )
        )

        if not pub_result.success:
            raise RuntimeError(f"Publish failed: {pub_result.error}")

        return result, pub_result

    async def _execute_cross_posts(
        self,
        user_id: int,
        schedule: Any,
        keyword: str,
        lead_text: str,
        lead_platform: str,
        project_id: int,
        category_id: int,
    ) -> list[CrossPostResult]:
        """Execute cross-posts for dependent connections after lead publish."""
        from services.ai.social_posts import SocialPostService

        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        conn_repo = ConnectionsRepository(self._db, cm)
        social_service = SocialPostService(self._ai_orchestrator, self._db)
        category = await self._categories.get_by_id(category_id)
        results: list[CrossPostResult] = []

        for conn_id in schedule.cross_post_connection_ids:
            conn = await conn_repo.get_by_id(conn_id)
            # Verify connection exists, is active, and belongs to same project
            if not conn or conn.status != "active" or conn.project_id != project_id:
                results.append(
                    CrossPostResult(
                        connection_id=conn_id,
                        platform=conn.platform_type if conn else "unknown",
                        status="error",
                        error="connection_inactive",
                    )
                )
                continue

            cost = estimate_cross_post_cost()
            if not await self._tokens.check_balance(user_id, cost):
                results.append(
                    CrossPostResult(
                        connection_id=conn_id,
                        platform=conn.platform_type,
                        status="error",
                        error="insufficient_balance",
                    )
                )
                log.warning("cross_post_insufficient_balance", user_id=user_id, conn_id=conn_id)
                break  # stop remaining cross-posts

            try:
                await self._tokens.charge(user_id, cost, "cross_post", description=f"Cross-post: {keyword}")
            except InsufficientBalanceError:
                results.append(
                    CrossPostResult(
                        connection_id=conn_id,
                        platform=conn.platform_type,
                        status="error",
                        error="charge_failed",
                    )
                )
                break

            try:
                adapted = await social_service.adapt_for_platform(
                    original_text=lead_text,
                    source_platform=lead_platform,
                    target_platform=conn.platform_type,
                    user_id=user_id,
                    project_id=project_id,
                    keyword=keyword,
                )

                adapted_text = ""
                if isinstance(adapted.content, dict):
                    adapted_text = adapted.content.get("text", "")

                publisher = self._get_publisher(conn.platform_type)
                from services.ai.content_validator import ContentValidator

                validator = ContentValidator()
                validation = validator.validate(adapted_text, "social_post", conn.platform_type)
                if not validation.is_valid:
                    raise RuntimeError(f"Validation failed: {'; '.join(validation.errors)}")

                ct: Literal["html", "telegram_html", "plain_text", "pin_text"] = self._get_content_type(
                    conn.platform_type
                )  # type: ignore[assignment]
                pub_result = await publisher.publish(
                    PublishRequest(
                        connection=conn,
                        content=adapted_text,
                        content_type=ct,
                        category=category,
                    )
                )

                if not pub_result.success:
                    raise RuntimeError(f"Publish failed: {pub_result.error}")

                # Log cross-post publication
                await self._publications.create_log(
                    PublicationLogCreate(
                        user_id=user_id,
                        project_id=project_id,
                        category_id=category_id,
                        platform_type=conn.platform_type,
                        connection_id=conn_id,
                        keyword=keyword,
                        content_type="cross_post",
                        tokens_spent=cost,
                        status="success",
                        post_url=pub_result.post_url or "",
                    )
                )

                results.append(
                    CrossPostResult(
                        connection_id=conn_id,
                        platform=conn.platform_type,
                        status="ok",
                        post_url=pub_result.post_url or "",
                        tokens_spent=cost,
                    )
                )

            except Exception as exc:
                log.exception("cross_post_failed", conn_id=conn_id, keyword=keyword)
                try:
                    await self._tokens.refund(user_id, cost, reason="cross_post_error")
                except Exception as refund_exc:
                    log.critical("cross_post_refund_failed", user_id=user_id, conn_id=conn_id)
                    sentry_sdk.capture_exception(refund_exc)

                await self._publications.create_log(
                    PublicationLogCreate(
                        user_id=user_id,
                        project_id=project_id,
                        category_id=category_id,
                        platform_type=conn.platform_type,
                        connection_id=conn_id,
                        keyword=keyword,
                        content_type="cross_post",
                        tokens_spent=0,
                        status="error",
                        error_message=str(exc)[:500],
                    )
                )

                results.append(
                    CrossPostResult(
                        connection_id=conn_id,
                        platform=conn.platform_type,
                        status="error",
                        error=str(exc)[:200],
                    )
                )

        return results

    def _get_publisher(self, platform_type: str) -> Any:
        """Get publisher instance for platform type."""
        from services.publishers.pinterest import PinterestPublisher
        from services.publishers.telegram import TelegramPublisher
        from services.publishers.vk import VKPublisher
        from services.publishers.wordpress import WordPressPublisher

        publishers = {
            "wordpress": lambda: WordPressPublisher(self._http_client),
            "telegram": lambda: TelegramPublisher(self._http_client),
            "vk": lambda: VKPublisher(self._http_client),
            "pinterest": lambda: PinterestPublisher(http_client=self._http_client),
        }
        factory = publishers.get(platform_type)
        if not factory:
            msg = f"Unknown platform: {platform_type}"
            raise ValueError(msg)
        return factory()

    @staticmethod
    def _get_content_type(platform_type: str) -> str:
        """Map platform type to content type for PublishRequest."""
        content_types = {
            "wordpress": "html",
            "telegram": "telegram_html",
            "vk": "plain_text",
            "pinterest": "pin_text",
        }
        return content_types.get(platform_type, "plain_text")
