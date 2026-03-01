"""Tests for services/preview.py — PreviewService.

Coverage: generate_article_content(), _gather_websearch_data(), publish_to_wordpress(),
error handling, image flows, token charging/refund on error.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.exceptions import AIGenerationError
from services.ai.orchestrator import GenerationResult
from services.preview import ArticleContent, PreviewService
from services.research_helpers import gather_websearch_data

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------


def _gen_result(content: dict[str, Any] | str) -> GenerationResult:
    return GenerationResult(
        content=content,
        model_used="anthropic/claude-sonnet-4.5",
        prompt_version="v1",
        fallback_used=False,
        input_tokens=1000,
        output_tokens=2000,
        cost_usd=0.12,
        generation_time_ms=5000,
    )


_ARTICLE_CONTENT = {
    "title": "SEO Guide 2026",
    "content_markdown": "## Introduction\n\nSome article text about SEO.",
    "meta_description": "Learn SEO in 2026.",
    "images_meta": [
        {"alt_text": "SEO diagram", "filename": "seo-diagram", "caption": "Figure 1"},
    ],
}

_SERPER_ORGANIC = [
    {"title": "Competitor 1", "link": "https://competitor1.com/seo", "snippet": "..."},
    {"title": "Competitor 2", "link": "https://competitor2.com/seo", "snippet": "..."},
]

_RESEARCH_DATA = {
    "facts": [{"claim": "SEO is important", "source": "Moz", "year": "2025"}],
    "trends": [],
    "statistics": [],
    "summary": "SEO trends summary",
}


@dataclass
class _MockSerperResult:
    organic: list[dict[str, Any]]
    people_also_ask: list[dict[str, Any]]
    related_searches: list[str]


@dataclass
class _MockScrapeResult:
    url: str
    markdown: str
    summary: str | None
    word_count: int
    headings: list[dict[str, str | int]]
    meta_title: str | None
    meta_description: str | None


@dataclass
class _MockMapResult:
    urls: list[dict[str, str]]


@dataclass
class _MockImageResult:
    data: bytes


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    orch = AsyncMock()
    orch.generate = AsyncMock(return_value=_gen_result(_ARTICLE_CONTENT))
    orch.generate_without_rate_limit = AsyncMock(return_value=_gen_result(_RESEARCH_DATA))
    return orch


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_image_storage() -> AsyncMock:
    storage = AsyncMock()
    storage.upload = AsyncMock(
        return_value=MagicMock(
            path="123/1/12345_0.webp",
            signed_url="https://storage.example.com/signed/12345_0.webp",
        )
    )
    storage.download = AsyncMock(return_value=b"fake_image_bytes")
    return storage


@pytest.fixture
def mock_http_client() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_serper() -> AsyncMock:
    serper = AsyncMock()
    serper.search = AsyncMock(
        return_value=_MockSerperResult(
            organic=_SERPER_ORGANIC,
            people_also_ask=[{"question": "What is SEO?", "snippet": "...", "link": "..."}],
            related_searches=["seo tools"],
        )
    )
    return serper


@pytest.fixture
def mock_firecrawl() -> AsyncMock:
    fc = AsyncMock()
    fc.scrape_content = AsyncMock(
        return_value=_MockScrapeResult(
            url="https://competitor1.com/seo",
            markdown="# SEO Guide\n\nContent...",
            summary="An SEO guide",
            word_count=2000,
            headings=[{"level": 2, "text": "Introduction"}],
            meta_title="SEO Guide",
            meta_description="SEO guide description",
        )
    )
    fc.map_site = AsyncMock(return_value=_MockMapResult(urls=[{"url": "https://example.com/page1"}]))
    return fc


@pytest.fixture
def mock_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def preview_service(
    mock_orchestrator: AsyncMock,
    mock_db: MagicMock,
    mock_image_storage: AsyncMock,
    mock_http_client: MagicMock,
    mock_serper: AsyncMock,
    mock_firecrawl: AsyncMock,
    mock_redis: AsyncMock,
) -> PreviewService:
    return PreviewService(
        ai_orchestrator=mock_orchestrator,
        db=mock_db,
        image_storage=mock_image_storage,
        http_client=mock_http_client,
        serper_client=mock_serper,
        firecrawl_client=mock_firecrawl,
        redis=mock_redis,
    )


# ---------------------------------------------------------------------------
# _gather_websearch_data
# ---------------------------------------------------------------------------


class TestGatherWebsearchData:
    async def test_gathers_serper_and_research_in_parallel(
        self, mock_orchestrator: AsyncMock, mock_serper: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        result = await gather_websearch_data(
            keyword="seo optimization",
            project_url="https://example.com",
            serper=mock_serper,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
            specialization="SEO",
            company_name="TestCo",
        )

        assert result["serper_data"] is not None
        assert result["serper_data"]["organic"] == _SERPER_ORGANIC
        assert result["research_data"] is not None
        mock_serper.search.assert_awaited_once()

    async def test_gathers_firecrawl_map(
        self,
        mock_orchestrator: AsyncMock,
        mock_serper: AsyncMock,
        mock_firecrawl: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        result = await gather_websearch_data(
            keyword="test",
            project_url="https://example.com",
            serper=mock_serper,
            firecrawl=mock_firecrawl,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
        )

        assert "internal_links" in result
        mock_firecrawl.map_site.assert_awaited_once()

    async def test_no_firecrawl_without_project_url(
        self,
        mock_orchestrator: AsyncMock,
        mock_serper: AsyncMock,
        mock_firecrawl: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        result = await gather_websearch_data(
            keyword="test",
            project_url=None,
            serper=mock_serper,
            firecrawl=mock_firecrawl,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
        )

        mock_firecrawl.map_site.assert_not_awaited()
        assert result.get("internal_links") is None

    async def test_serper_failure_degrades_gracefully(
        self, mock_orchestrator: AsyncMock, mock_serper: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """E04: Serper unavailable -> empty serper_data, no competitor pages."""
        mock_serper.search.side_effect = Exception("Serper quota exceeded")

        result = await gather_websearch_data(
            keyword="test",
            project_url=None,
            serper=mock_serper,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
        )

        assert result["serper_data"] is None
        assert result["competitor_pages"] == []

    async def test_research_failure_degrades_gracefully_e53(
        self, mock_orchestrator: AsyncMock, mock_redis: AsyncMock
    ) -> None:
        """E53: Sonar Pro unavailable -> research_data=None, pipeline continues."""
        mock_orchestrator.generate_without_rate_limit.side_effect = Exception("Sonar down")

        result = await gather_websearch_data(
            keyword="test",
            project_url=None,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
            specialization="SEO",
            company_name="Co",
        )

        assert result["research_data"] is None

    async def test_scrapes_competitor_pages(
        self,
        mock_orchestrator: AsyncMock,
        mock_serper: AsyncMock,
        mock_firecrawl: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        result = await gather_websearch_data(
            keyword="test",
            project_url="https://mysite.com",
            serper=mock_serper,
            firecrawl=mock_firecrawl,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
        )

        assert len(result["competitor_pages"]) >= 1
        mock_firecrawl.scrape_content.assert_awaited()

    async def test_filters_own_site_from_competitors(
        self,
        mock_orchestrator: AsyncMock,
        mock_serper: AsyncMock,
        mock_firecrawl: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """Own site URLs are excluded from competitor scraping."""
        mock_serper.search.return_value = _MockSerperResult(
            organic=[
                {"title": "Own site", "link": "https://example.com/page", "snippet": "..."},
                {"title": "Competitor", "link": "https://competitor.com/page", "snippet": "..."},
            ],
            people_also_ask=[],
            related_searches=[],
        )

        await gather_websearch_data(
            keyword="test",
            project_url="https://example.com",
            serper=mock_serper,
            firecrawl=mock_firecrawl,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
        )

        # scrape_content should only be called for competitor.com, not example.com
        scrape_calls = mock_firecrawl.scrape_content.call_args_list
        scraped_urls = [c.args[0] for c in scrape_calls]
        assert all("example.com" not in url for url in scraped_urls)

    async def test_no_clients_returns_defaults(
        self,
        mock_redis: AsyncMock,
    ) -> None:
        result = await gather_websearch_data(
            "test",
            None,
            serper=None,
            firecrawl=None,
            orchestrator=None,
            redis=mock_redis,
        )

        assert result["serper_data"] is None
        assert result["competitor_pages"] == []

    async def test_firecrawl_scrape_failure_graceful(
        self,
        mock_orchestrator: AsyncMock,
        mock_serper: AsyncMock,
        mock_firecrawl: AsyncMock,
        mock_redis: AsyncMock,
    ) -> None:
        """E31: Firecrawl /scrape timeout -> no competitor data."""
        mock_firecrawl.scrape_content.side_effect = Exception("Timeout")

        result = await gather_websearch_data(
            keyword="test",
            project_url="https://mysite.com",
            serper=mock_serper,
            firecrawl=mock_firecrawl,
            orchestrator=mock_orchestrator,
            redis=mock_redis,
        )

        # No competitor pages, but overall call succeeds
        assert result["competitor_pages"] == []
        assert result["serper_data"] is not None


# ---------------------------------------------------------------------------
# generate_article_content
# ---------------------------------------------------------------------------


class TestGenerateArticleContent:
    @patch("services.ai.articles.sanitize_html", side_effect=lambda x: x)
    @patch("services.ai.markdown_renderer.render_markdown", return_value="<h2>Intro</h2><p>Text</p>")
    @patch("services.ai.reconciliation.reconcile_images")
    @patch("services.ai.reconciliation.extract_block_contexts", return_value=["Intro context", "Body context"])
    @patch("services.ai.reconciliation.distribute_images", return_value=[0, 1])
    @patch("services.ai.reconciliation.split_into_blocks", return_value=[MagicMock(), MagicMock()])
    @patch("services.ai.images.ImageService")
    @patch("services.ai.articles.ArticleService")
    @patch("services.preview.AuditsRepository")
    @patch("services.preview.ProjectsRepository")
    @patch("services.preview.CategoriesRepository")
    async def test_full_pipeline_returns_article_content(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_audit_cls: MagicMock,
        mock_article_svc: MagicMock,
        mock_image_svc: MagicMock,
        mock_split: MagicMock,
        mock_distribute: MagicMock,
        mock_extract_ctx: MagicMock,
        mock_reconcile: MagicMock,
        mock_render: MagicMock,
        mock_sanitize: MagicMock,
        preview_service: PreviewService,
        mock_image_storage: AsyncMock,
    ) -> None:
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=MagicMock(image_settings={"count": 2}))
        mock_proj_cls.return_value.get_by_id = AsyncMock(
            return_value=MagicMock(
                website_url="https://example.com",
                specialization="SEO",
                company_name="TestCo",
                company_city="Moscow",
                description="A company",
                id=1,
            )
        )
        mock_audit_cls.return_value.get_branding_by_project = AsyncMock(return_value=None)

        # Article service returns text first (sequential, not parallel)
        mock_article_svc.return_value.generate = AsyncMock(return_value=_gen_result(_ARTICLE_CONTENT))
        # Image service generates AFTER text with block_contexts
        mock_image_svc.return_value.generate = AsyncMock(return_value=[_MockImageResult(data=b"fake_img")])

        mock_reconcile.return_value = (
            "## Introduction\n\nText with ![img]({{RECONCILED_IMAGE_1}})",
            [MagicMock(data=b"fake_img", alt_text="SEO diagram", filename="seo-diagram", caption="Figure 1")],
        )

        result = await preview_service.generate_article_content(
            user_id=1, project_id=1, category_id=10, keyword="seo optimization"
        )

        assert isinstance(result, ArticleContent)
        assert result.title == "SEO Guide 2026"
        assert result.images_count >= 0
        # Verify block-aware pipeline was called
        mock_split.assert_called_once()
        mock_distribute.assert_called_once()
        mock_extract_ctx.assert_called_once()
        # Verify images were generated with block_contexts
        img_call = mock_image_svc.return_value.generate.call_args
        assert img_call.kwargs.get("block_contexts") == ["Intro context", "Body context"]

    @patch("services.ai.articles.ArticleService")
    @patch("services.ai.images.ImageService")
    @patch("services.preview.AuditsRepository")
    @patch("services.preview.ProjectsRepository")
    @patch("services.preview.CategoriesRepository")
    async def test_text_failure_raises(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_audit_cls: MagicMock,
        mock_image_svc: MagicMock,
        mock_article_svc: MagicMock,
        preview_service: PreviewService,
    ) -> None:
        """E35: Text generation failure -> raise (caller should refund)."""
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=MagicMock(image_settings={}))
        mock_proj_cls.return_value.get_by_id = AsyncMock(
            return_value=MagicMock(
                website_url=None,
                specialization="",
                company_name="",
                company_city="",
                description="",
                id=1,
            )
        )
        mock_audit_cls.return_value.get_branding_by_project = AsyncMock(return_value=None)

        mock_article_svc.return_value.generate = AsyncMock(side_effect=ValueError("Text gen failed"))
        mock_image_svc.return_value.generate = AsyncMock(return_value=[])

        with pytest.raises(ValueError, match="Text gen failed"):
            await preview_service.generate_article_content(user_id=1, project_id=1, category_id=10, keyword="test")

    @patch("services.ai.articles.sanitize_html", side_effect=lambda x: x)
    @patch("services.ai.markdown_renderer.render_markdown", return_value="<p>Text</p>")
    @patch("services.ai.reconciliation.reconcile_images", return_value=("## Text", []))
    @patch("services.ai.images.ImageService")
    @patch("services.ai.articles.ArticleService")
    @patch("services.preview.AuditsRepository")
    @patch("services.preview.ProjectsRepository")
    @patch("services.preview.CategoriesRepository")
    async def test_e34_image_failure_still_returns_content(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_audit_cls: MagicMock,
        mock_article_svc: MagicMock,
        mock_image_svc: MagicMock,
        mock_reconcile: MagicMock,
        mock_render: MagicMock,
        mock_sanitize: MagicMock,
        preview_service: PreviewService,
    ) -> None:
        """E34: Image generation fails -> article published without images."""
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=MagicMock(image_settings={}))
        mock_proj_cls.return_value.get_by_id = AsyncMock(
            return_value=MagicMock(
                website_url=None,
                specialization="",
                company_name="",
                company_city="",
                description="",
                id=1,
            )
        )
        mock_audit_cls.return_value.get_branding_by_project = AsyncMock(return_value=None)
        mock_article_svc.return_value.generate = AsyncMock(return_value=_gen_result(_ARTICLE_CONTENT))
        mock_image_svc.return_value.generate = AsyncMock(side_effect=AIGenerationError(message="Image gen failed"))

        result = await preview_service.generate_article_content(user_id=1, project_id=1, category_id=10, keyword="test")

        assert isinstance(result, ArticleContent)
        assert result.images_count == 0

    @patch("services.ai.articles.sanitize_html", side_effect=lambda x: x)
    @patch("services.ai.markdown_renderer.render_markdown", return_value="<p>Text</p>")
    @patch("services.ai.reconciliation.reconcile_images")
    @patch("services.ai.images.ImageService")
    @patch("services.ai.articles.ArticleService")
    @patch("services.preview.AuditsRepository")
    @patch("services.preview.ProjectsRepository")
    @patch("services.preview.CategoriesRepository")
    async def test_image_upload_failure_graceful(
        self,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_audit_cls: MagicMock,
        mock_article_svc: MagicMock,
        mock_image_svc: MagicMock,
        mock_reconcile: MagicMock,
        mock_render: MagicMock,
        mock_sanitize: MagicMock,
        preview_service: PreviewService,
        mock_image_storage: AsyncMock,
    ) -> None:
        """Image upload to storage fails -> skip image, remove placeholder."""
        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=MagicMock(image_settings={}))
        mock_proj_cls.return_value.get_by_id = AsyncMock(
            return_value=MagicMock(
                website_url=None,
                specialization="",
                company_name="",
                company_city="",
                description="",
                id=1,
            )
        )
        mock_audit_cls.return_value.get_branding_by_project = AsyncMock(return_value=None)
        mock_article_svc.return_value.generate = AsyncMock(return_value=_gen_result(_ARTICLE_CONTENT))
        mock_image_svc.return_value.generate = AsyncMock(return_value=[_MockImageResult(data=b"img")])
        mock_reconcile.return_value = (
            "## Text\n\n![alt]({{RECONCILED_IMAGE_1}})",
            [MagicMock(data=b"img", alt_text="alt", filename="f", caption="c")],
        )
        mock_image_storage.upload.side_effect = Exception("Storage down")

        result = await preview_service.generate_article_content(user_id=1, project_id=1, category_id=10, keyword="test")

        # Article still returned, but without stored images
        assert isinstance(result, ArticleContent)
        assert result.images_count == 0


# ---------------------------------------------------------------------------
# publish_to_wordpress
# ---------------------------------------------------------------------------


class TestPublishToWordpress:
    @patch("services.publishers.wordpress.WordPressPublisher")
    async def test_downloads_images_and_publishes(
        self,
        mock_wp_cls: MagicMock,
        preview_service: PreviewService,
        mock_image_storage: AsyncMock,
    ) -> None:
        preview = MagicMock()
        preview.images = [
            {
                "storage_path": "123/1/img.webp",
                "alt_text": "alt",
                "filename": "img",
                "caption": "cap",
                "url": "http://x",
            },
        ]
        preview.content_html = "<p>Article</p>"
        preview.title = "Test Article"
        preview.keyword = "seo"
        preview.meta_description = "desc"

        connection = MagicMock()
        mock_wp = AsyncMock()
        mock_wp.publish = AsyncMock(return_value=MagicMock(success=True, url="https://wp.com/post/1"))
        mock_wp_cls.return_value = mock_wp

        await preview_service.publish_to_wordpress(preview, connection)

        mock_image_storage.download.assert_awaited_once_with("123/1/img.webp")
        mock_wp.publish.assert_awaited_once()

    @patch("services.publishers.wordpress.WordPressPublisher")
    async def test_image_download_failure_skips_image(
        self,
        mock_wp_cls: MagicMock,
        preview_service: PreviewService,
        mock_image_storage: AsyncMock,
    ) -> None:
        """If image download from storage fails, publish proceeds without that image."""
        preview = MagicMock()
        preview.images = [
            {"storage_path": "bad/path.webp", "alt_text": "alt", "filename": "img", "caption": "", "url": ""},
        ]
        preview.content_html = "<p>Article</p>"
        preview.title = "Test"
        preview.keyword = "test"
        preview.meta_description = ""

        connection = MagicMock()
        mock_image_storage.download.side_effect = Exception("Storage error")
        mock_wp = AsyncMock()
        mock_wp.publish = AsyncMock(return_value=MagicMock(success=True))
        mock_wp_cls.return_value = mock_wp

        await preview_service.publish_to_wordpress(preview, connection)

        mock_wp.publish.assert_awaited_once()

    @patch("services.publishers.wordpress.WordPressPublisher")
    async def test_no_images_in_preview(
        self,
        mock_wp_cls: MagicMock,
        preview_service: PreviewService,
    ) -> None:
        preview = MagicMock()
        preview.images = None
        preview.content_html = "<p>Article</p>"
        preview.title = "Test"
        preview.keyword = "test"
        preview.meta_description = ""

        connection = MagicMock()
        mock_wp = AsyncMock()
        mock_wp.publish = AsyncMock(return_value=MagicMock(success=True))
        mock_wp_cls.return_value = mock_wp

        await preview_service.publish_to_wordpress(preview, connection)

        mock_wp.publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# Image Director integration (§7.4.2)
# ---------------------------------------------------------------------------


class TestImageDirectorIntegration:
    @patch("services.preview.gather_websearch_data")
    @patch("services.ai.articles.sanitize_html", side_effect=lambda x: x)
    @patch("services.ai.markdown_renderer.render_markdown", return_value="<h2>Intro</h2><p>Text</p>")
    @patch("services.ai.reconciliation.reconcile_images", return_value=("## Text", []))
    @patch("services.ai.reconciliation.extract_block_contexts", return_value=["Intro ctx"])
    @patch("services.ai.reconciliation.distribute_images", return_value=[0])
    @patch("services.ai.reconciliation.split_into_blocks")
    @patch("services.ai.images.ImageService")
    @patch("services.ai.articles.ArticleService")
    @patch("services.preview.AuditsRepository")
    @patch("services.preview.ProjectsRepository")
    @patch("services.preview.CategoriesRepository")
    @patch("services.ai.image_director.ImageDirectorService")
    async def test_generate_article_calls_image_director(
        self,
        mock_director_cls: MagicMock,
        mock_cat_cls: MagicMock,
        mock_proj_cls: MagicMock,
        mock_audit_cls: MagicMock,
        mock_article_svc: MagicMock,
        mock_image_svc: MagicMock,
        mock_split: MagicMock,
        mock_distribute: MagicMock,
        mock_extract_ctx: MagicMock,
        mock_reconcile: MagicMock,
        mock_render: MagicMock,
        mock_sanitize: MagicMock,
        mock_gather: MagicMock,
        preview_service: PreviewService,
    ) -> None:
        """Director is called and plans are passed to ImageService."""
        from services.ai.image_director import DirectorResult, ImagePlan

        mock_cat_cls.return_value.get_by_id = AsyncMock(return_value=MagicMock(image_settings={"count": 1}))
        mock_proj_cls.return_value.get_by_id = AsyncMock(
            return_value=MagicMock(
                website_url=None,
                specialization="SEO",
                company_name="TestCo",
                company_city="",
                description="",
                id=1,
            )
        )
        mock_audit_cls.return_value.get_branding_by_project = AsyncMock(return_value=None)
        mock_article_svc.return_value.generate = AsyncMock(return_value=_gen_result(_ARTICLE_CONTENT))
        mock_image_svc.return_value.generate = AsyncMock(return_value=[])

        mock_block = MagicMock()
        mock_block.heading = "Introduction"
        mock_block.content = "Some text about SEO"
        mock_split.return_value = [mock_block]

        mock_gather.return_value = {
            "serper_data": None,
            "competitor_pages": [],
            "competitor_analysis": "",
            "competitor_gaps": "",
            "internal_links": "",
            "research_data": None,
        }

        director_plans = [
            ImagePlan(
                section_index=0,
                concept="Hero",
                prompt="A pro shot",
                negative_prompt="blurry",
                aspect_ratio="16:9",
            ),
        ]
        mock_director_cls.return_value.plan_images = AsyncMock(
            return_value=DirectorResult(images=director_plans, visual_narrative="A story")
        )

        await preview_service.generate_article_content(user_id=1, project_id=1, category_id=10, keyword="seo")

        # Director was called
        mock_director_cls.return_value.plan_images.assert_awaited_once()
        # Plans were passed to ImageService
        img_call = mock_image_svc.return_value.generate.call_args
        assert img_call.kwargs.get("director_plans") == director_plans
