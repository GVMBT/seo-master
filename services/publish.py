"""Auto-publish service — triggered by QStash webhook.

Executes the full publish pipeline: load data, rotate keyword,
check balance, charge, generate, validate, publish, log.
Sequential pipeline: text → Image Director → images (§7.4.2).
Web research: Serper + Firecrawl + Perplexity in parallel (C1).
Cluster context: matching cluster from category.keywords (C2).
Zero dependencies on Telegram/Aiogram.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

import structlog

from api.models import PublishPayload
from bot.config import get_settings
from bot.exceptions import AIGenerationError, InsufficientBalanceError
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
from services.research_helpers import gather_websearch_data
from services.storage import ImageStorage
from services.tokens import TokenService, estimate_article_cost, estimate_cross_post_cost, estimate_social_post_cost

if TYPE_CHECKING:
    import httpx

    from bot.config import Settings
    from services.external.firecrawl import FirecrawlClient
    from services.external.serper import SerperClient
    from services.scheduler import SchedulerService

log = structlog.get_logger()

_PINTEREST_MIN_IMAGES = 1


def _effective_social_image_count(image_settings: dict[str, Any] | None, platform_type: str) -> int:
    """Get image count for social posts, enforcing Pinterest minimum."""
    raw = (image_settings or {}).get("count", 1)
    try:
        count = max(0, int(raw))
    except (ValueError, TypeError):
        count = 1
    if platform_type == "pinterest":
        return max(count, _PINTEREST_MIN_IMAGES)
    return count


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
        serper_client: SerperClient | None = None,
        firecrawl_client: FirecrawlClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._redis = redis
        self._http_client = http_client
        self._ai_orchestrator = ai_orchestrator
        self._image_storage = image_storage
        self._admin_ids = admin_ids
        self._scheduler_service = scheduler_service
        self._serper = serper_client
        self._firecrawl = firecrawl_client
        self._settings = settings
        self._tokens = TokenService(db, admin_ids)
        self._users = UsersRepository(db)
        self._categories = CategoriesRepository(db)
        self._projects = ProjectsRepository(db)
        self._publications = PublicationsRepository(db)
        self._schedules = SchedulesRepository(db)

    async def execute(self, payload: PublishPayload) -> PublishOutcome:
        """Execute auto-publish pipeline.

        Flow: check schedule (H13) -> load data -> check connection ->
        check keywords (E17) -> rotate keyword (E22/E23) ->
        check balance (E01) -> charge -> generate -> publish -> log -> return.
        """
        user_id = payload.user_id

        # 0. Check schedule enabled (H13: QStash cron may fire after user disabled schedule)
        schedule = await self._schedules.get_by_id(payload.schedule_id)
        if not schedule or not schedule.enabled:
            log.warning(
                "schedule_disabled_or_missing",
                schedule_id=payload.schedule_id,
                user_id=user_id,
            )
            return PublishOutcome(status="skipped", reason="schedule_disabled", user_id=user_id)

        # 1. Load user
        user = await self._users.get_by_id(user_id)
        if not user:
            return PublishOutcome(status="error", reason="user_not_found", user_id=user_id)

        # 2. Load category
        category = await self._categories.get_by_id(payload.category_id)
        if not category:
            return PublishOutcome(
                status="error",
                reason="category_not_found",
                user_id=user_id,
                notify=user.notify_publications,
            )

        # 2b. Load project (needed for settings fallback: project → category)
        project = await self._projects.get_by_id(payload.project_id)

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
            return PublishOutcome(
                status="error",
                reason="no_available_keyword",
                user_id=user_id,
                notify=user.notify_publications,
            )

        if low_pool:
            log.warning("publish_low_keyword_pool", category_id=payload.category_id, keyword=keyword)

        # 5b. Find matching cluster for keyword context (C2)
        cluster = self._find_matching_cluster(keyword, category.keywords)
        if cluster:
            log.info(
                "publish_cluster_found",
                keyword=keyword,
                cluster_name=cluster.get("cluster_name", ""),
            )

        # 6. Estimate cost
        if content_type == "article":
            estimated_cost = estimate_article_cost()
        else:
            image_settings = (project.image_settings if project else None) or category.image_settings
            social_image_count = _effective_social_image_count(image_settings, payload.platform_type)
            estimated_cost = estimate_social_post_cost(images_count=social_image_count)

        # 7. Check balance (E01): pause schedule per EDGE_CASES.md
        if not await self._tokens.check_balance(user_id, estimated_cost):
            await self._disable_schedule(
                schedule, "publish_insufficient_balance", user_id=user_id, required=estimated_cost
            )
            return PublishOutcome(
                status="error",
                reason="insufficient_balance",
                user_id=user_id,
                notify=user.notify_publications,
            )

        # 8-9. Generate, publish, charge on success (charge-after-result)
        return await self._publish_and_log(
            payload=payload,
            user=user,
            category=category,
            connection=connection,
            keyword=keyword,
            content_type=content_type,
            estimated_cost=estimated_cost,
            schedule=schedule,
            cluster=cluster,
            project=project,
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
        schedule: Any,
        cluster: dict[str, Any] | None = None,
        project: Any = None,
    ) -> PublishOutcome:
        """Generate content, publish, then charge on success (charge-after-result)."""
        user_id = payload.user_id
        charged = False
        actual_cost = 0
        try:
            gen_result, pub_result, failed_images = await self._generate_and_publish(
                user_id=user_id,
                project_id=payload.project_id,
                category_id=payload.category_id,
                keyword=keyword,
                connection=connection,
                content_type=content_type,
                category=category,
                cluster=cluster,
                project=project,
            )

            # E34: deduct cost for failed images (30 tokens per image)
            actual_cost = estimated_cost
            if failed_images > 0:
                actual_cost -= failed_images * 30
                log.info("image_cost_reduced", user_id=user_id, failed=failed_images, actual_cost=actual_cost)
            actual_cost = max(actual_cost, 0)

            # Charge tokens AFTER successful generation + publish
            try:
                await self._tokens.charge(
                    user_id, actual_cost, f"auto_{content_type}", description=f"Auto-publish: {keyword}"
                )
                charged = True
            except InsufficientBalanceError:
                log.warning("charge_after_publish_insufficient", user_id=user_id, cost=actual_cost)
            except Exception:
                log.exception("charge_after_publish_failed", user_id=user_id, cost=actual_cost)

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
                    tokens_spent=actual_cost if charged else 0,
                    images_count=images_count,
                    status="success",
                    post_url=pub_result.post_url or "",
                )
            )

            # Update schedule last_post_at + reset error counter on success
            await self._mark_schedule_success(payload.schedule_id, schedule.id)

            # Execute cross-posts if configured (social posts only)
            cross_results: list[CrossPostResult] = []
            if schedule.cross_post_connection_ids and payload.platform_type != "wordpress":
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

            total_cost = actual_cost + sum(cr.tokens_spent for cr in cross_results if cr.tokens_spent)
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

            # Track consecutive platform errors for schedule pause
            # Wrapped in try/except: Redis failure must NOT prevent refund/logging below
            if schedule:
                try:
                    counter_key = f"schedule_errors:{schedule.id}"
                    count = await self._redis.incr(counter_key)
                    await self._redis.expire(counter_key, 86400)  # 24h TTL
                    if count >= 3:
                        await self._disable_schedule(
                            schedule, "publish_platform_errors_threshold", reason=str(exc)[:200]
                        )
                        await self._redis.delete(counter_key)
                except Exception:
                    log.exception("publish_error_counter_failed", schedule_id=schedule.id)

            # Refund if charge was already made (post-charge failure)
            if charged and actual_cost > 0:
                try:
                    await self._tokens.refund(
                        user_id=user_id,
                        amount=actual_cost,
                        reason="refund",
                        description=f"Refund auto-publish error: {keyword}",
                    )
                except Exception:
                    log.exception("publish_refund_failed", user_id=user_id, cost=actual_cost)

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

            return PublishOutcome(
                status="error",
                reason=str(exc),
                user_id=user_id,
                notify=user.notify_publications,
            )

    async def _mark_schedule_success(self, schedule_id: int, schedule_pk: int) -> None:
        """Update schedule last_post_at and reset error counter on success."""
        await self._schedules.update(
            schedule_id,
            PlatformScheduleUpdate(last_post_at=datetime.now(tz=UTC)),
        )
        try:
            await self._redis.delete(f"schedule_errors:{schedule_pk}")
        except Exception:
            log.exception("publish_error_counter_reset_failed", schedule_id=schedule_pk)

    async def _disable_schedule(self, schedule: Any, log_event: str, **log_kwargs: Any) -> None:
        """Disable schedule + delete QStash crons (shared by E01 insufficient balance & E55 platform errors)."""
        log.warning(log_event, schedule_id=schedule.id, **log_kwargs)
        if schedule.qstash_schedule_ids and self._scheduler_service:
            await self._scheduler_service.delete_qstash_schedules(schedule.qstash_schedule_ids)
        await self._schedules.update(
            schedule.id,
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
        cluster: dict[str, Any] | None = None,
        project: Any = None,
    ) -> tuple[Any, PublishResult, int]:
        """Generate content + images, then publish.

        For articles: text → Director → images sequentially (§7.4.2).
        For social posts: text generated first, then published with optional image.
        Returns (gen_result, pub_result, failed_image_count).
        """
        if content_type == "article":
            return await self._generate_article(
                user_id,
                project_id,
                category_id,
                keyword,
                connection,
                category,
                cluster=cluster,
                project=project,
            )

        return await self._generate_social_post(
            user_id,
            project_id,
            category_id,
            keyword,
            connection,
            category,
            project=project,
        )

    async def _generate_article(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        connection: Any,
        category: Any,
        cluster: dict[str, Any] | None = None,
        project: Any = None,
    ) -> tuple[Any, PublishResult, int]:
        """Sequential article pipeline: websearch → text → Director → images (C1, C2, §7.4.2).

        Phase 1: Gather web research (Serper + Firecrawl + Perplexity) in parallel.
        Phase 2: Generate text (needs article for Director context).
        Phase 3: Image Director + Image Generation (Director needs article text).
        Returns (gen_result, pub_result, failed_image_count).
        """
        from services.ai.articles import ArticleService
        from services.ai.images import ImageService
        from services.publishers.wordpress import WordPressPublisher

        # Auto-publish is a system cron (QStash), not user UI — bypass rate limits
        article_service = ArticleService(self._ai_orchestrator, self._db, skip_rate_limit=True)
        image_service = ImageService(self._ai_orchestrator)
        publisher = WordPressPublisher(self._http_client)

        # Resolve WP category (auto-map bot category → WP category)
        wp_category_id: int | None = None
        if category.name:
            cached_wp_cats: dict[str, int] = (connection.metadata or {}).get("wp_categories", {})
            if category.name in cached_wp_cats:
                wp_category_id = cached_wp_cats[category.name]
                log.info("wp_category_cache_hit", name=category.name, wp_id=wp_category_id)
            else:
                base_url = WordPressPublisher._base_url(connection.credentials)
                auth = WordPressPublisher._auth(connection.credentials)
                wp_category_id = await publisher.resolve_wp_category(base_url, auth, category.name)
                if wp_category_id is not None:
                    settings = get_settings()
                    cm = CredentialManager(settings.encryption_key.get_secret_value())
                    conn_repo = ConnectionsRepository(self._db, cm)
                    await conn_repo.merge_metadata(
                        connection.id,
                        {"wp_categories": {**cached_wp_cats, category.name: wp_category_id}},
                    )

        image_settings = (project.image_settings if project else None) or category.image_settings or {}
        image_count = image_settings.get("count", 4)
        image_context: dict[str, Any] = {
            "keyword": keyword,
            "content_type": "article",
            "company_name": "",
            "specialization": "",
            "image_settings": image_settings,
        }
        # Use pre-loaded project for company info (loaded in execute())
        if project:
            image_context["company_name"] = project.company_name or ""
            image_context["specialization"] = project.specialization or ""

        # Phase 1: Gather web research data (C1 — Serper + Firecrawl + Perplexity)
        project_url = project.website_url if project else None
        # Use cached internal links from site analysis (PRD §7.1) if available
        cached_links = (connection.metadata or {}).get("internal_links") if connection else None
        websearch = await gather_websearch_data(
            keyword=keyword,
            project_url=project_url,
            serper=self._serper,
            firecrawl=self._firecrawl,
            orchestrator=self._ai_orchestrator,
            redis=self._redis,
            specialization=(project.specialization or "") if project else "",
            company_name=(project.company_name or "") if project else "",
            geography=(project.company_city or "") if project else "",
            company_description_short=((project.description or "")[:200]) if project else "",
            internal_links_cache=cached_links,
        )

        # Data readiness gate: if all external sources failed, skip this slot
        # (article quality will be too low without competitor/research data)
        serper_empty = not websearch.get("serper_data") or not websearch["serper_data"].get("organic")
        research_empty = not websearch.get("research_data")
        if serper_empty and research_empty:
            log.warning(
                "publish_skipped_no_external_data",
                keyword=keyword,
                user_id=user_id,
                has_serper=not serper_empty,
                has_research=not research_empty,
                reason="both_empty",
            )
            raise RuntimeError("External data unavailable (Serper + Research empty), skipping slot")

        # Phase 2: Text generation (sequential — Director needs article text)
        text_result = await article_service.generate(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            cluster=cluster,
            serper_data=websearch["serper_data"],
            competitor_pages=websearch["competitor_pages"],
            competitor_analysis=websearch["competitor_analysis"],
            competitor_gaps=websearch["competitor_gaps"],
            internal_links=websearch.get("internal_links", ""),
            research_data=websearch.get("research_data"),
            news_data=websearch.get("news_data"),
            autocomplete_suggestions=websearch.get("autocomplete_suggestions"),
        )

        # Extract text content
        content_markdown = ""
        title = keyword
        meta_desc = ""
        seo_title = ""
        images_meta: list[dict[str, str]] = []
        if isinstance(text_result.content, dict):
            content_markdown = text_result.content.get("content_markdown", "")
            title = text_result.content.get("title", keyword)
            seo_title = text_result.content.get("seo_title", "")
            meta_desc = text_result.content.get("meta_description", "")
            images_meta = text_result.content.get("images_meta", [])

        # Safety-net truncation for SEO fields
        from services.ai.articles import truncate_seo_fields

        seo_title, meta_desc = truncate_seo_fields(seo_title or title[:60], meta_desc)

        # Phase 3: Image Director + Image Generation (§7.4.2)
        from services.ai.image_director import ImageDirectorContext, ImageDirectorService
        from services.ai.niche_detector import detect_niche
        from services.ai.reconciliation import distribute_images, extract_block_contexts, split_into_blocks

        director_plans = None
        block_contexts_list: list[str] | None = None
        branding = None
        blocks = split_into_blocks(content_markdown) if content_markdown else []
        if blocks and image_count > 0:
            block_indices = distribute_images(blocks, image_count)
            block_contexts_list = extract_block_contexts(blocks, block_indices)

            # Load branding for Director
            branding_colors: dict[str, str] = {}
            audits_repo = AuditsRepository(self._db)
            branding = await audits_repo.get_branding_by_project(project_id)
            if branding and branding.colors:
                branding_colors = branding.colors

            target_sections = [
                {"index": idx, "heading": blocks[idx].heading, "context": blocks[idx].content[:300]}
                for idx in block_indices
                if idx < len(blocks)
            ]
            director_service = ImageDirectorService(self._ai_orchestrator, skip_rate_limit=True)
            director_ctx = ImageDirectorContext(
                article_title=title,
                article_summary=content_markdown,
                company_name=(project.company_name or "") if project else "",
                niche=detect_niche((project.specialization or "") if project else ""),
                image_count=image_count,
                target_sections=target_sections,
                brand_colors=branding_colors,
                image_style=image_settings.get("style", "photorealism, professional"),
                image_tone=image_settings.get("tone", "professional"),
            )
            director_result = await director_service.plan_images(director_ctx, user_id)
            if director_result:
                director_plans = director_result.images
                log.info("image_director_narrative", visual_narrative=director_result.visual_narrative)

        # Generate images (with Director plans or mechanical fallback)
        raw_images: list[bytes | BaseException] = []
        failed_images = 0
        try:
            image_result_list = await image_service.generate(
                user_id=user_id,
                context=image_context,
                count=image_count,
                block_contexts=block_contexts_list,
                director_plans=director_plans,
            )
            raw_images = [img.data for img in image_result_list]
            failed_images = image_count - len(image_result_list)
        except AIGenerationError:
            log.warning("image_generation_failed", exc_info=True)
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
        if branding is None:
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

        # Build reconciled placeholder URLs so WP publisher can replace them
        # with real WP media URLs after upload (preview flow uses Supabase Storage
        # URLs; auto-publish skips Storage and passes placeholders directly).
        reconciled_urls = [f"{{{{RECONCILED_IMAGE_{i + 1}}}}}" for i in range(len(uploads))]

        pub_result = await publisher.publish(
            PublishRequest(
                connection=connection,
                content=content_html,
                content_type="html",
                title=title,
                images=[u.data for u in uploads],
                images_meta=[{"alt": u.alt_text, "filename": u.filename, "figcaption": u.caption} for u in uploads],
                category=category,
                metadata={
                    "seo_title": seo_title,
                    "meta_description": meta_desc,
                    "focus_keyword": keyword,
                    "storage_urls": reconciled_urls,
                    **({"wp_category_id": wp_category_id} if wp_category_id else {}),
                },
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
        project: Any = None,
    ) -> tuple[Any, PublishResult, int]:
        """Generate social post with images and publish.

        Returns (gen_result, pub_result, failed_image_count).
        """
        from services.ai.social_posts import SocialPostService

        social_service = SocialPostService(self._ai_orchestrator, self._db, skip_rate_limit=True)
        result = await social_service.generate(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            platform=connection.platform_type,
        )

        publisher = self._get_publisher(connection.platform_type, connection.id)
        # Social post content is a dict {text, hashtags, pin_title} — extract text
        content = result.content.get("text", "") if isinstance(result.content, dict) else result.content

        # Append hashtags for all social platforms (Pinterest includes in description)
        if isinstance(result.content, dict) and connection.platform_type in ("vk", "telegram", "pinterest"):
            hashtags = result.content.get("hashtags", [])
            if hashtags:
                tags_str = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
                content = f"{content}\n\n{tags_str}"

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

        # Build metadata for Pinterest (board_id, pin_title)
        metadata: dict[str, str] = {}
        if connection.platform_type == "pinterest" and isinstance(result.content, dict):
            metadata["pin_title"] = result.content.get("pin_title", "")[:100]

        # Generate images for social posts
        eff_image_settings = (project.image_settings if project else None) or category.image_settings
        image_count = _effective_social_image_count(eff_image_settings, connection.platform_type)

        images: list[bytes] = []
        failed_images = 0
        if image_count > 0:
            try:
                from services.ai.images import ImageService

                image_service = ImageService(self._ai_orchestrator)
                img_settings = dict(eff_image_settings or {})
                # Pinterest: vertical 2:3 aspect ratio
                if connection.platform_type == "pinterest":
                    img_settings["formats"] = ["2:3"]
                image_context: dict[str, Any] = {
                    "keyword": keyword,
                    "content_type": "social_post",
                    "company_name": (project.company_name or "") if project else "",
                    "specialization": (project.specialization or "") if project else "",
                    "image_settings": img_settings,
                }
                image_results = await image_service.generate(
                    user_id=user_id,
                    context=image_context,
                    count=image_count,
                )
                images = [img.data for img in image_results]
                failed_images = image_count - len(image_results)
            except Exception:
                log.warning("social_image_generation_failed", exc_info=True)
                failed_images = image_count
                # Graceful degradation: TG/VK publish without images, Pinterest will fail

        pub_result = await publisher.publish(
            PublishRequest(
                connection=connection,
                content=content,
                content_type=ct,
                images=images,
                category=category,
                metadata=metadata,
            )
        )

        if not pub_result.success:
            raise RuntimeError(f"Publish failed: {pub_result.error}")

        return result, pub_result, failed_images

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
        social_service = SocialPostService(self._ai_orchestrator, self._db, skip_rate_limit=True)
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

                # Append hashtags for all social platforms
                if isinstance(adapted.content, dict) and conn.platform_type in ("vk", "telegram", "pinterest"):
                    hashtags = adapted.content.get("hashtags", [])
                    if hashtags:
                        tags_str = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
                        adapted_text = f"{adapted_text}\n\n{tags_str}"

                publisher = self._get_publisher(conn.platform_type, conn.id)
                from services.ai.content_validator import ContentValidator

                validator = ContentValidator()
                validation = validator.validate(adapted_text, "social_post", conn.platform_type)
                if not validation.is_valid:
                    raise RuntimeError(f"Validation failed: {'; '.join(validation.errors)}")

                ct: Literal["html", "telegram_html", "plain_text", "pin_text"] = self._get_content_type(
                    conn.platform_type
                )  # type: ignore[assignment]

                # Build metadata for Pinterest
                xp_metadata: dict[str, str] = {}
                if conn.platform_type == "pinterest" and isinstance(adapted.content, dict):
                    xp_metadata["pin_title"] = adapted.content.get("pin_title", "")[:100]

                pub_result = await publisher.publish(
                    PublishRequest(
                        connection=conn,
                        content=adapted_text,
                        content_type=ct,
                        category=category,
                        metadata=xp_metadata,
                    )
                )

                if not pub_result.success:
                    raise RuntimeError(f"Publish failed: {pub_result.error}")

                # Charge AFTER successful cross-post (charge-after-result)
                try:
                    await self._tokens.charge(user_id, cost, "cross_post", description=f"Cross-post: {keyword}")
                except Exception:
                    log.warning("cross_post_charge_failed", user_id=user_id, conn_id=conn_id, cost=cost)

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
                # No charge was made — no refund needed (charge-after-result)
                log.exception("cross_post_failed", conn_id=conn_id, keyword=keyword)

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

    @staticmethod
    def _find_matching_cluster(
        keyword: str,
        keywords: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Find cluster in category.keywords where keyword matches main_phrase or phrases.

        category.keywords is a JSON array of clusters:
        [{cluster_name, cluster_type, main_phrase, phrases: [{phrase, volume, ...}]}]
        """
        keyword_lower = keyword.lower()
        for cluster in keywords:
            if not isinstance(cluster, dict):
                continue
            # Match main_phrase
            if cluster.get("main_phrase", "").lower() == keyword_lower:
                return cluster
            # Match in phrases array
            for phrase_entry in cluster.get("phrases", []):
                if isinstance(phrase_entry, dict) and phrase_entry.get("phrase", "").lower() == keyword_lower:
                    return cluster
        return None

    def _make_token_refresh_cb(self, connection_id: int) -> Any:
        """Build callback to persist refreshed credentials in DB."""
        from services.publishers.factory import make_token_refresh_cb

        enc_key = (self._settings or get_settings()).encryption_key.get_secret_value()
        return make_token_refresh_cb(self._db, connection_id, enc_key)

    def _get_publisher(self, platform_type: str, connection_id: int = 0) -> Any:
        """Get publisher instance for platform type with token refresh callback."""
        from services.publishers.factory import create_publisher

        settings = self._settings or get_settings()
        on_refresh = self._make_token_refresh_cb(connection_id) if connection_id else None
        return create_publisher(platform_type, self._http_client, settings, on_token_refresh=on_refresh)

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
