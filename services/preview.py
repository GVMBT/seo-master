"""Preview service — article generation + WP publishing.

Used by routers/publishing/pipeline/article.py (ArticlePipelineFSM).
Zero Telegram/Aiogram dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from bot.exceptions import AIGenerationError
from db.client import SupabaseClient
from db.repositories.audits import AuditsRepository
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.articles import RESEARCH_SCHEMA
from services.ai.orchestrator import AIOrchestrator, GenerationRequest
from services.external.firecrawl import FirecrawlClient
from services.external.serper import SerperClient
from services.research_helpers import gather_websearch_data
from services.storage import ImageStorage

if TYPE_CHECKING:
    import httpx

    from cache.client import RedisClient
    from db.models import ArticlePreview, PlatformConnection
    from services.publishers.base import PublishResult

log = structlog.get_logger()


@dataclass
class ArticleContent:
    """Result of article generation pipeline."""

    title: str
    content_html: str
    word_count: int
    images_count: int
    meta_description: str = ""
    stored_images: list[dict[str, Any]] = field(default_factory=list)


class PreviewService:
    """Article generation and publishing for manual (FSM) flow.

    Pipeline: ArticleService + ImageService in parallel → reconcile → store.
    """

    def __init__(
        self,
        ai_orchestrator: AIOrchestrator,
        db: SupabaseClient,
        image_storage: ImageStorage,
        http_client: httpx.AsyncClient,
        serper_client: SerperClient | None = None,
        firecrawl_client: FirecrawlClient | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self._orchestrator = ai_orchestrator
        self._db = db
        self._image_storage = image_storage
        self._http_client = http_client
        self._serper = serper_client
        self._firecrawl = firecrawl_client
        self._redis = redis

    async def generate_article_content(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        image_count: int | None = None,
    ) -> ArticleContent:
        """Run full article pipeline: websearch → text + images in parallel.

        Args:
            image_count: Override image count. If None, uses category settings.

        Returns ArticleContent with real AI-generated content.
        Raises on text generation failure (caller should refund).
        """
        from services.ai.articles import ArticleService, sanitize_html
        from services.ai.images import ImageService
        from services.ai.markdown_renderer import render_markdown
        from services.ai.reconciliation import (
            distribute_images,
            extract_block_contexts,
            reconcile_images,
            split_into_blocks,
        )

        article_service = ArticleService(self._orchestrator, self._db)
        image_service = ImageService(self._orchestrator)

        category = await CategoriesRepository(self._db).get_by_id(category_id)
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        if image_count is None:
            image_count = int((category.image_settings or {}).get("count", 4) if category else 4)

        # Phase 1: Gather websearch + research data (Serper PAA + Firecrawl + Sonar Pro)
        project_url = project.website_url if project else None
        websearch = await gather_websearch_data(
            keyword,
            project_url,
            serper=self._serper,
            firecrawl=self._firecrawl,
            orchestrator=self._orchestrator,
            redis=self._redis,
            specialization=(project.specialization or "") if project else "",
            company_name=(project.company_name or "") if project else "",
            geography=(project.company_city or "") if project else "",
            company_description_short=((project.description or "")[:200]) if project else "",
        )

        image_settings = (category.image_settings or {}) if category else {}
        image_context: dict[str, Any] = {
            "keyword": keyword,
            "content_type": "article",
            "company_name": (project.company_name or "") if project else "",
            "specialization": (project.specialization or "") if project else "",
            "image_settings": image_settings,
        }

        # Load branding colors for image prompt (image_v1.yaml)
        branding = None
        if project:
            try:
                branding = await AuditsRepository(self._db).get_branding_by_project(project.id)
            except Exception:
                log.warning("branding_load_failed", project_id=project.id, exc_info=True)
                branding = None
            if branding and branding.colors:
                colors = branding.colors
                if colors.get("primary"):
                    image_context["primary_color"] = colors["primary"]
                if colors.get("accent"):
                    image_context["accent_color"] = colors["accent"]
                if colors.get("background"):
                    image_context["background_color"] = colors["background"]

        # Phase 2: Text generation (outline → expand → quality → critique)
        text_result = await article_service.generate(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            image_count=image_count,
            serper_data=websearch["serper_data"],
            competitor_pages=websearch["competitor_pages"],
            competitor_analysis=websearch["competitor_analysis"],
            competitor_gaps=websearch["competitor_gaps"],
            internal_links=websearch.get("internal_links", ""),
            research_data=websearch.get("research_data"),
        )

        content = text_result.content if isinstance(text_result.content, dict) else {}
        title = content.get("title", keyword)
        content_markdown = content.get("content_markdown", "")
        meta_description: str = content.get("meta_description", "")
        images_meta: list[dict[str, str]] = content.get("images_meta", [])

        # Phase 3: Block-aware image generation (§7.4.1 + §7.4.2)
        # Images AFTER text — each prompt gets H2-section context + Director plans
        raw_images: list[bytes] = []
        director_result = None
        if image_count > 0:
            blocks = split_into_blocks(content_markdown)
            block_indices = distribute_images(blocks, image_count)
            block_contexts = extract_block_contexts(blocks, block_indices)
            log.info(
                "block_aware_images",
                blocks=len(blocks),
                indices=block_indices,
                image_count=image_count,
            )

            # Image Director: AI prompt engineering for targeted images (§7.4.2)
            from services.ai.image_director import ImageDirectorContext, ImageDirectorService
            from services.ai.niche_detector import detect_niche

            director_service = ImageDirectorService(self._orchestrator)
            target_sections = [
                {"index": idx, "heading": blocks[idx].heading, "context": blocks[idx].content[:300]}
                for idx in block_indices
                if idx < len(blocks)
            ]
            director_context = ImageDirectorContext(
                article_title=title,
                article_summary=content_markdown,
                company_name=(project.company_name or "") if project else "",
                niche=detect_niche((project.specialization or "") if project else ""),
                image_count=image_count,
                target_sections=target_sections,
                brand_colors=(branding.colors if branding and branding.colors else {}),
                image_style=image_settings.get("style", "photorealism, professional"),
                image_tone=image_settings.get("tone", "professional"),
            )
            director_result = await director_service.plan_images(director_context, user_id)
            director_plans = director_result.images if director_result else None

            if director_result:
                log.info("image_director_narrative", visual_narrative=director_result.visual_narrative)

            try:
                image_result = await image_service.generate(
                    user_id=user_id,
                    context=image_context,
                    count=image_count,
                    block_contexts=block_contexts,
                    director_plans=director_plans,
                )
                raw_images = [img.data for img in image_result]
            except AIGenerationError:
                log.warning("image_gen_failed", exc_info=True)

        # Reconcile images with text (E32-E35)
        images_for_reconcile: list[bytes | BaseException] = list(raw_images)
        processed_md, uploads = reconcile_images(
            content_markdown=content_markdown,
            images_meta=images_meta,
            generated_images=images_for_reconcile,
            title=title,
        )

        # Upload images to Supabase Storage BEFORE rendering markdown→HTML
        # so we can inject real URLs into {{RECONCILED_IMAGE_N}} placeholders
        stored_images: list[dict[str, Any]] = []
        for i, upload in enumerate(uploads):
            try:
                stored = await self._image_storage.upload(
                    upload.data,
                    user_id,
                    project_id,
                    i,
                )
                stored_images.append(
                    {
                        "url": stored.signed_url,
                        "storage_path": stored.path,
                        "alt_text": upload.alt_text,
                        "filename": upload.filename,
                        "caption": upload.caption,
                    }
                )
            except Exception:
                log.warning("image_upload_failed", index=i)

        # Replace {{RECONCILED_IMAGE_N}} with real Storage URLs in markdown
        for i, img_info in enumerate(stored_images):
            placeholder = f"{{{{RECONCILED_IMAGE_{i + 1}}}}}"
            processed_md = processed_md.replace(placeholder, img_info["url"])

        # Remove any unreplaced reconciled placeholders (upload failures)
        processed_md = re.sub(
            r"!\[[^\]]*\]\(\{\{RECONCILED_IMAGE_\d+\}\}[^)]*\)",
            "",
            processed_md,
        )
        processed_md = re.sub(r"\{\{RECONCILED_IMAGE_\d+\}\}", "", processed_md)

        # Render markdown→HTML with real image URLs embedded
        content_html = render_markdown(processed_md, branding={}, insert_toc=True)
        content_html = sanitize_html(content_html)

        word_count = len(content_markdown.split())
        return ArticleContent(
            title=title,
            content_html=content_html,
            word_count=word_count,
            images_count=len(stored_images),
            meta_description=meta_description,
            stored_images=stored_images,
        )

    async def warmup_research_schema(self) -> None:
        """Warm up Sonar Pro JSON Schema cache to avoid +30s on first user request.

        Called once on bot startup. Sends a minimal research request that
        compiles and caches the JSON Schema on Perplexity's side.
        """
        try:
            context = {
                "main_phrase": "SEO trends 2026",
                "specialization": "digital marketing",
                "company_name": "test",
                "language": "en",
            }
            request = GenerationRequest(
                task="article_research",
                context=context,
                user_id=0,
                response_schema=RESEARCH_SCHEMA,
            )
            await self._orchestrator.generate_without_rate_limit(request)
            log.info("research_schema_warmup_complete")
        except Exception:
            log.warning("research_schema_warmup_failed", exc_info=True)

    async def publish_to_wordpress(
        self,
        preview: ArticlePreview,
        connection: PlatformConnection,
    ) -> PublishResult:
        """Publish article preview to WordPress.

        Downloads images from Supabase Storage, uploads to WP.
        """
        from services.publishers.base import PublishRequest
        from services.publishers.wordpress import WordPressPublisher

        # Download images from Supabase Storage for WP upload
        image_bytes_list: list[bytes] = []
        images_meta_list: list[dict[str, str]] = []
        storage_urls: list[str] = []
        for img_info in preview.images or []:
            storage_path = img_info.get("storage_path")
            if storage_path:
                try:
                    img_data = await self._image_storage.download(storage_path)
                    image_bytes_list.append(img_data)
                    images_meta_list.append(
                        {
                            "alt": img_info.get("alt_text", ""),
                            "filename": img_info.get("filename", ""),
                            "figcaption": img_info.get("caption", ""),
                        }
                    )
                    storage_urls.append(img_info.get("url", ""))
                except Exception:
                    log.warning("image_download_failed", path=storage_path)

        publisher = WordPressPublisher(self._http_client)
        return await publisher.publish(
            PublishRequest(
                connection=connection,
                content=preview.content_html or "",
                content_type="html",
                title=preview.title or "",
                images=image_bytes_list,
                images_meta=images_meta_list,
                metadata={
                    "focus_keyword": preview.keyword or "",
                    "meta_description": preview.meta_description or "",
                    "storage_urls": storage_urls,
                },
            )
        )
