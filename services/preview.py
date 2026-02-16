"""Preview service — article generation + WP publishing for manual flow.

Used by routers/publishing/preview.py (ArticlePublishFSM).
Zero Telegram/Aiogram dependencies.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.orchestrator import AIOrchestrator
from services.storage import ImageStorage

if TYPE_CHECKING:
    import httpx

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
    ) -> None:
        self._orchestrator = ai_orchestrator
        self._db = db
        self._image_storage = image_storage
        self._http_client = http_client

    async def generate_article_content(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
    ) -> ArticleContent:
        """Run full article pipeline: text + images in parallel.

        Returns ArticleContent with real AI-generated content.
        Raises on text generation failure (caller should refund).
        """
        from services.ai.articles import ArticleService, sanitize_html
        from services.ai.images import ImageService
        from services.ai.markdown_renderer import render_markdown
        from services.ai.reconciliation import reconcile_images

        article_service = ArticleService(self._orchestrator, self._db)
        image_service = ImageService(self._orchestrator)

        category = await CategoriesRepository(self._db).get_by_id(category_id)
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        image_count = (category.image_settings or {}).get("count", 4) if category else 4

        image_context: dict[str, Any] = {
            "keyword": keyword,
            "content_type": "article",
            "company_name": (project.company_name or "") if project else "",
            "specialization": (project.specialization or "") if project else "",
        }

        # Parallel: text + images (API_CONTRACTS.md parallel pipeline)
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
        text_result, image_result = await asyncio.gather(
            text_task,
            image_task,
            return_exceptions=True,
        )

        if isinstance(text_result, BaseException):
            raise text_result

        content = text_result.content if isinstance(text_result.content, dict) else {}
        title = content.get("title", keyword)
        content_markdown = content.get("content_markdown", "")
        images_meta: list[dict[str, str]] = content.get("images_meta", [])

        # Process images
        raw_images: list[bytes] = []
        if isinstance(image_result, BaseException):
            log.warning("image_gen_failed", error=str(image_result))
        elif image_result:
            raw_images = [img.data for img in image_result]

        # Reconcile images with text (E32-E35)
        images_for_reconcile: list[bytes | BaseException] = list(raw_images)
        processed_md, uploads = reconcile_images(
            content_markdown=content_markdown,
            images_meta=images_meta,
            generated_images=images_for_reconcile,
            title=title,
        )

        # Re-render after reconciliation
        content_html = render_markdown(processed_md, branding={}, insert_toc=True)
        content_html = sanitize_html(content_html)

        # Upload images to Supabase Storage
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

        word_count = len(content_markdown.split())
        return ArticleContent(
            title=title,
            content_html=content_html,
            word_count=word_count,
            images_count=len(stored_images),
            stored_images=stored_images,
        )

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
                metadata={"focus_keyword": preview.keyword or ""},
            )
        )
