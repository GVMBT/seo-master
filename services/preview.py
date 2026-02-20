"""Preview service — article generation + WP publishing.

Used by routers/publishing/pipeline/article.py (ArticlePipelineFSM).
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
from services.external.firecrawl import FirecrawlClient
from services.external.serper import SerperClient
from services.storage import ImageStorage

if TYPE_CHECKING:
    import httpx

    from db.models import ArticlePreview, PlatformConnection
    from services.publishers.base import PublishResult

log = structlog.get_logger()

# Max competitor pages to scrape (cost: 1 Firecrawl credit each)
_MAX_COMPETITOR_SCRAPE = 3


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
        serper_client: SerperClient | None = None,
        firecrawl_client: FirecrawlClient | None = None,
    ) -> None:
        self._orchestrator = ai_orchestrator
        self._db = db
        self._image_storage = image_storage
        self._http_client = http_client
        self._serper = serper_client
        self._firecrawl = firecrawl_client

    async def _gather_websearch_data(
        self,
        keyword: str,
        project_url: str | None,
    ) -> dict[str, Any]:
        """Gather Serper PAA + Firecrawl competitor data in parallel.

        Returns dict with keys: serper_data, competitor_pages, competitor_analysis,
        competitor_gaps. All values gracefully degrade to empty on failure.
        Cost: ~$0.001 (Serper) + ~$0.03 (3 Firecrawl scrapes).
        """
        result: dict[str, Any] = {
            "serper_data": None,
            "competitor_pages": [],
            "competitor_analysis": "",
            "competitor_gaps": "",
        }

        tasks: dict[str, Any] = {}

        # Serper: PAA + organic results for the keyword
        if self._serper:
            tasks["serper"] = self._serper.search(keyword, num=10)

        # Firecrawl: internal links for the project site (if URL provided)
        if self._firecrawl and project_url:
            tasks["map"] = self._firecrawl.map_site(project_url, limit=100)

        if not tasks:
            return result

        task_keys = list(tasks.keys())
        task_coros = list(tasks.values())
        gathered = await asyncio.gather(*task_coros, return_exceptions=True)
        responses = dict(zip(task_keys, gathered, strict=True))

        # Process Serper results
        serper_result = responses.get("serper")
        if serper_result and not isinstance(serper_result, BaseException):
            result["serper_data"] = {
                "organic": serper_result.organic,
                "people_also_ask": serper_result.people_also_ask,
                "related_searches": serper_result.related_searches,
            }

            # Scrape top-3 competitor pages via Firecrawl
            # Filter own site first, then slice to ensure full count
            if self._firecrawl and serper_result.organic:
                competitor_urls = [
                    r["link"]
                    for r in serper_result.organic
                    if r.get("link") and not _is_own_site(r["link"], project_url)
                ][:_MAX_COMPETITOR_SCRAPE]
                if competitor_urls:
                    scrape_tasks = [self._firecrawl.scrape_content(url) for url in competitor_urls]
                    scrape_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)
                    pages: list[dict[str, Any]] = []
                    for sr in scrape_results:
                        if sr and not isinstance(sr, BaseException):
                            pages.append(
                                {
                                    "url": sr.url,
                                    "word_count": sr.word_count,
                                    "headings": sr.headings,
                                    "summary": sr.summary or "",
                                }
                            )
                    result["competitor_pages"] = pages

                    # Format competitor analysis for prompt
                    if pages:
                        result["competitor_analysis"] = _format_competitor_analysis(pages)
                        result["competitor_gaps"] = _identify_gaps(pages)
        elif isinstance(serper_result, BaseException):
            log.warning("websearch_serper_failed", error=str(serper_result))

        # Format internal links
        map_result = responses.get("map")
        if map_result and not isinstance(map_result, BaseException):
            urls = [u.get("url", "") for u in map_result.urls[:20] if u.get("url")]
            result["internal_links"] = "\n".join(urls) if urls else ""
        elif isinstance(map_result, BaseException):
            log.warning("websearch_map_failed", error=str(map_result))

        log.info(
            "websearch_data_gathered",
            has_serper=result["serper_data"] is not None,
            competitor_count=len(result["competitor_pages"]),
            has_internal_links=bool(result.get("internal_links")),
        )
        return result

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
        from services.ai.reconciliation import reconcile_images

        article_service = ArticleService(self._orchestrator, self._db)
        image_service = ImageService(self._orchestrator)

        category = await CategoriesRepository(self._db).get_by_id(category_id)
        project = await ProjectsRepository(self._db).get_by_id(project_id)
        if image_count is None:
            image_count = (category.image_settings or {}).get("count", 4) if category else 4

        # Phase 1: Gather websearch data (Serper PAA + Firecrawl competitors)
        project_url = project.website_url if project else None
        websearch = await self._gather_websearch_data(keyword, project_url)

        image_context: dict[str, Any] = {
            "keyword": keyword,
            "content_type": "article",
            "company_name": (project.company_name or "") if project else "",
            "specialization": (project.specialization or "") if project else "",
        }

        # Phase 2: Parallel text + images (API_CONTRACTS.md parallel pipeline)
        text_task = article_service.generate(
            user_id=user_id,
            project_id=project_id,
            category_id=category_id,
            keyword=keyword,
            serper_data=websearch["serper_data"],
            competitor_pages=websearch["competitor_pages"],
            competitor_analysis=websearch["competitor_analysis"],
            competitor_gaps=websearch["competitor_gaps"],
            internal_links=websearch.get("internal_links", ""),
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


def _is_own_site(url: str, project_url: str | None) -> bool:
    """Check if a URL belongs to the project's own site (skip in competitor scraping)."""
    if not project_url:
        return False
    try:
        from urllib.parse import urlparse

        own_domain = urlparse(project_url).netloc.lower().replace("www.", "")
        url_domain = urlparse(url).netloc.lower().replace("www.", "")
        return own_domain == url_domain
    except ValueError, AttributeError:
        return False


def _format_competitor_analysis(pages: list[dict[str, Any]]) -> str:
    """Format competitor scrape results into a text block for AI prompt."""
    lines: list[str] = []
    for i, page in enumerate(pages, 1):
        h2_headings = [h["text"] for h in page.get("headings", []) if h.get("level") == 2]
        lines.append(f"Конкурент {i} ({page.get('url', '')}):")
        lines.append(f"  Объём: ~{page.get('word_count', 0)} слов")
        if page.get("summary"):
            lines.append(f"  Тема: {page['summary'][:200]}")
        if h2_headings:
            lines.append(f"  H2: {', '.join(h2_headings[:8])}")
        lines.append("")
    return "\n".join(lines)


def _identify_gaps(pages: list[dict[str, Any]]) -> str:
    """Summarize competitor structure for AI to identify gaps.

    Instead of naive Counter-based comparison (which fails for semantically
    different headings like blogs), we pass raw competitor headings to the AI
    outline prompt and let it determine real content gaps.
    """
    if not pages:
        return ""

    lines: list[str] = []
    for i, page in enumerate(pages, 1):
        h2_list = [str(h.get("text", "")) for h in page.get("headings", []) if h.get("level") == 2]
        if h2_list:
            lines.append(f"Конкурент {i}: {', '.join(h2_list[:8])}")

    if not lines:
        return ""

    return (
        "Структура H2 конкурентов (определи, какие темы НЕ раскрыты "
        "ни одним конкурентом — это твоя уникальная ценность):\n" + "\n".join(lines)
    )
