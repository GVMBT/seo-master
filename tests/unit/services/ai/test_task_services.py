"""Tests for all 6 task-specific AI services.

Covers: ArticleService, SocialPostService, KeywordService,
ImageService, ReviewService, DescriptionService.

Each service is tested for:
- generate() success with valid data
- generate() with missing project/category raises AIGenerationError
- Service-specific edge cases (HTML sanitization, multi-image, etc.)
"""

from __future__ import annotations

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.exceptions import AIGenerationError, ContentValidationError
from db.models import Category, Project
from services.ai.images import GeneratedImage
from services.ai.orchestrator import GenerationResult

# ---------------------------------------------------------------------------
# Shared test data factories
# ---------------------------------------------------------------------------


def _make_project(**overrides: Any) -> Project:
    defaults: dict[str, Any] = {
        "id": 1,
        "user_id": 123,
        "name": "Test Project",
        "company_name": "TestCo",
        "specialization": "SEO",
        "company_city": "Moscow",
        "advantages": "Best quality",
    }
    defaults.update(overrides)
    return Project(**defaults)


def _make_category(**overrides: Any) -> Category:
    defaults: dict[str, Any] = {
        "id": 1,
        "project_id": 1,
        "name": "Test Cat",
        "keywords": [
            {"phrase": "test keyword", "volume": 100, "difficulty": 30},
        ],
        "prices": "Price list here",
        "reviews": [
            {"text": "Great product, highly recommend!", "author": "Ivan", "rating": 5},
        ],
    }
    defaults.update(overrides)
    return Category(**defaults)


def _make_generation_result(**overrides: Any) -> GenerationResult:
    defaults: dict[str, Any] = {
        "content": {"title": "Test Title"},
        "model_used": "test-model",
        "input_tokens": 100,
        "output_tokens": 200,
        "cost_usd": 0.01,
        "generation_time_ms": 500,
        "prompt_version": "v5",
        "fallback_used": False,
    }
    defaults.update(overrides)
    return GenerationResult(**defaults)


def _make_image_result(**overrides: Any) -> GenerationResult:
    """GenerationResult for image — content is a base64 data URI string."""
    # Minimal valid PNG (1x1 pixel)
    pixel = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100).decode()
    data_uri = f"data:image/png;base64,{pixel}"
    defaults: dict[str, Any] = {
        "content": data_uri,
        "model_used": "google/gemini-3-pro-image-preview",
        "input_tokens": 50,
        "output_tokens": 0,
        "cost_usd": 0.02,
        "generation_time_ms": 3000,
        "prompt_version": "v1",
        "fallback_used": False,
    }
    defaults.update(overrides)
    return GenerationResult(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_orchestrator() -> AsyncMock:
    orch = AsyncMock()
    orch.generate = AsyncMock(return_value=_make_generation_result())
    orch.generate_without_rate_limit = AsyncMock(return_value=_make_generation_result())
    return orch


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


# ---------------------------------------------------------------------------
# ArticleService
# ---------------------------------------------------------------------------


class TestArticleService:
    """Tests for services.ai.articles.ArticleService."""

    async def test_article_generate_success_returns_result(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Successful article generation returns GenerationResult with content dict."""
        # Content must pass ContentValidator: >=500 chars, has <h1>, has <p> with 50+ chars, no placeholders
        long_paragraph = "A" * 60
        filler = "X" * 500
        article_content = {
            "title": "SEO Guide",
            "meta_description": "Best SEO practices",
            "content_html": f"<h1>Guide</h1><p>{long_paragraph}</p><p>faq section</p>{filler}",
            "faq_schema": [{"question": "What?", "answer": "This."}],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=article_content,
        )

        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            # Inject mocked repos
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            result = await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                keyword="test keyword",
            )

        assert isinstance(result, GenerationResult)
        assert isinstance(result.content, dict)
        assert result.content["title"] == "SEO Guide"
        mock_orchestrator.generate.assert_awaited_once()

    async def test_article_generate_project_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing project raises AIGenerationError."""
        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=None)
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=999,
                    category_id=1,
                    keyword="test keyword",
                )

        mock_orchestrator.generate.assert_not_awaited()

    async def test_article_generate_category_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing category raises AIGenerationError."""
        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(return_value=None)

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=1,
                    category_id=999,
                    keyword="test keyword",
                )

        mock_orchestrator.generate.assert_not_awaited()

    async def test_article_generate_invalid_content_raises_validation_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Invalid content (too short, no H1) should raise ContentValidationError (H10)."""
        article_content = {
            "title": "Short",
            "meta_description": "Desc",
            "content_html": "<p>Too short.</p>",
            "faq_schema": [],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=article_content,
        )

        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(ContentValidationError, match="validation failed"):
                await svc.generate(
                    user_id=123,
                    project_id=1,
                    category_id=1,
                    keyword="test keyword",
                )

    async def test_article_generate_html_sanitized_with_nh3(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """HTML content_html must be sanitized via nh3 (ARCHITECTURE.md 5.8)."""
        # Build content that passes validation: >=500 chars, has <h1>, has <p> with 50+ chars
        filler = "B" * 500
        malicious_html = (
            f'<h1>Title</h1><p>{"Good content paragraph with enough text to pass validation check" }</p>'
            '<script>alert("xss")</script>'
            f'<a href="javascript:void(0)">link</a>{filler}'
        )
        article_content = {
            "title": "Test",
            "meta_description": "Desc",
            "content_html": malicious_html,
            "faq_schema": [],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=article_content,
        )

        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            result = await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                keyword="test keyword",
            )

        html = result.content["content_html"]  # type: ignore[index]
        # nh3 should strip dangerous attributes like javascript: hrefs
        assert "javascript:" not in html

    async def test_article_generate_passes_branding_colors(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Branding colors should be included in the generation context."""
        filler = "C" * 500
        article_content = {
            "title": "Test",
            "meta_description": "Desc",
            "content_html": (
                f"<h1>Title</h1><p>Content paragraph with enough text here for checks.</p>{filler}"
            ),
            "faq_schema": [],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=article_content,
        )

        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                keyword="test keyword",
                branding={"colors": {"text": "#111111", "accent": "#FF0000"}},
            )

        # Verify the context passed to orchestrator contains branding colors
        call_args = mock_orchestrator.generate.call_args
        request = call_args.args[0]
        assert request.context["text_color"] == "#111111"
        assert request.context["accent_color"] == "#FF0000"

    async def test_article_generate_keyword_volume_from_category(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Keyword volume and difficulty should be extracted from category keywords."""
        filler = "D" * 500
        article_content = {
            "title": "Test",
            "meta_description": "Desc",
            "content_html": (
                f"<h1>Title</h1><p>Content paragraph for test long enough for validation.</p>{filler}"
            ),
            "faq_schema": [],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=article_content,
        )

        with (
            patch("services.ai.articles.ProjectsRepository") as MockProjRepo,
            patch("services.ai.articles.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.articles import ArticleService

            svc = ArticleService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                keyword="test keyword",
            )

        call_args = mock_orchestrator.generate.call_args
        request = call_args.args[0]
        assert request.context["volume"] == "100"
        assert request.context["difficulty"] == "30"


# ---------------------------------------------------------------------------
# SocialPostService
# ---------------------------------------------------------------------------


class TestSocialPostService:
    """Tests for services.ai.social_posts.SocialPostService."""

    async def test_social_post_generate_success_returns_result(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Successful social post generation returns GenerationResult."""
        post_content = {
            "text": "Check out our product!",
            "hashtags": ["#seo", "#marketing"],
            "pin_title": "SEO Guide",
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=post_content,
        )

        with (
            patch("services.ai.social_posts.ProjectsRepository") as MockProjRepo,
            patch("services.ai.social_posts.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.social_posts import SocialPostService

            svc = SocialPostService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            result = await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                keyword="test keyword",
                platform="telegram",
            )

        assert isinstance(result, GenerationResult)
        assert result.content["text"] == "Check out our product!"  # type: ignore[index]
        mock_orchestrator.generate.assert_awaited_once()

    async def test_social_post_generate_context_includes_platform(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Generation context must include the target platform."""
        mock_orchestrator.generate.return_value = _make_generation_result()

        with (
            patch("services.ai.social_posts.ProjectsRepository") as MockProjRepo,
            patch("services.ai.social_posts.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.social_posts import SocialPostService

            svc = SocialPostService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                keyword="test keyword",
                platform="vk",
            )

        request = mock_orchestrator.generate.call_args.args[0]
        assert request.context["platform"] == "vk"
        assert request.task == "social_post"

    async def test_social_post_generate_project_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing project raises AIGenerationError."""
        with (
            patch("services.ai.social_posts.ProjectsRepository") as MockProjRepo,
            patch("services.ai.social_posts.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=None)
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.social_posts import SocialPostService

            svc = SocialPostService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=999,
                    category_id=1,
                    keyword="test keyword",
                    platform="telegram",
                )

        mock_orchestrator.generate.assert_not_awaited()

    async def test_social_post_generate_category_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing category raises AIGenerationError."""
        with (
            patch("services.ai.social_posts.ProjectsRepository") as MockProjRepo,
            patch("services.ai.social_posts.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(return_value=None)

            from services.ai.social_posts import SocialPostService

            svc = SocialPostService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=1,
                    category_id=999,
                    keyword="test keyword",
                    platform="telegram",
                )


# ---------------------------------------------------------------------------
# KeywordService
# ---------------------------------------------------------------------------


class TestKeywordService:
    """Tests for services.ai.keywords.KeywordService."""

    async def test_keyword_generate_success_returns_result(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Successful keyword generation returns GenerationResult."""
        kw_content = {
            "keywords": [
                {"phrase": "seo optimization", "intent": "commercial"},
                {"phrase": "what is seo", "intent": "informational"},
            ],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=kw_content,
        )

        with patch("services.ai.keywords.ProjectsRepository") as MockProjRepo:
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )

            from services.ai.keywords import KeywordService

            svc = KeywordService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value

            result = await svc.generate(
                user_id=123,
                project_id=1,
                quantity=10,
                products="SEO services",
                geography="Moscow",
            )

        assert isinstance(result, GenerationResult)
        assert len(result.content["keywords"]) == 2  # type: ignore[arg-type,index]
        mock_orchestrator.generate.assert_awaited_once()

    async def test_keyword_generate_context_includes_quantity_and_geography(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Generation context must include quantity, products, geography."""
        mock_orchestrator.generate.return_value = _make_generation_result()

        with patch("services.ai.keywords.ProjectsRepository") as MockProjRepo:
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )

            from services.ai.keywords import KeywordService

            svc = KeywordService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                quantity=20,
                products="web development",
                geography="Saint Petersburg",
            )

        request = mock_orchestrator.generate.call_args.args[0]
        assert request.context["quantity"] == "20"
        assert request.context["products"] == "web development"
        assert request.context["geography"] == "Saint Petersburg"
        assert request.task == "keywords"

    async def test_keyword_generate_project_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing project raises AIGenerationError."""
        with patch("services.ai.keywords.ProjectsRepository") as MockProjRepo:
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=None)

            from services.ai.keywords import KeywordService

            svc = KeywordService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=999,
                    quantity=10,
                    products="SEO",
                    geography="Moscow",
                )

        mock_orchestrator.generate.assert_not_awaited()


# ---------------------------------------------------------------------------
# ImageService
# ---------------------------------------------------------------------------


class TestImageService:
    """Tests for services.ai.images.ImageService.

    ImageService now calls orchestrator.generate_without_rate_limit (H14)
    and does batch rate limiting via its own rate_limiter parameter.
    """

    async def test_image_generate_single_success(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """Single image generation returns list with one GeneratedImage."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_image_result()

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        result = await svc.generate(
            user_id=123,
            context={"keyword": "test", "image_settings": {}},
            count=1,
        )

        assert len(result) == 1
        assert isinstance(result[0], GeneratedImage)
        assert result[0].mime == "image/png"
        mock_orchestrator.generate_without_rate_limit.assert_awaited_once()

    async def test_image_generate_multi_success(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """Multi-image generation (count=3) returns 3 GeneratedImage objects."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_image_result()

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        result = await svc.generate(
            user_id=123,
            context={"keyword": "test", "image_settings": {}},
            count=3,
        )

        assert len(result) == 3
        assert all(isinstance(img, GeneratedImage) for img in result)
        assert mock_orchestrator.generate_without_rate_limit.await_count == 3

    async def test_image_generate_multi_partial_failure(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """Partial failure: 2 succeed, 1 fails. Returns 2 images (K>=1 OK)."""
        success_result = _make_image_result()
        fail_error = AIGenerationError(message="Model overloaded")

        # Side effects: success, fail, success
        mock_orchestrator.generate_without_rate_limit.side_effect = [
            success_result,
            fail_error,
            success_result,
        ]

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        result = await svc.generate(
            user_id=123,
            context={"keyword": "test", "image_settings": {}},
            count=3,
        )

        assert len(result) == 2
        assert all(isinstance(img, GeneratedImage) for img in result)

    async def test_image_generate_all_fail_raises_error(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """All images fail raises AIGenerationError."""
        mock_orchestrator.generate_without_rate_limit.side_effect = AIGenerationError(
            message="Model unavailable",
        )

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        with pytest.raises(AIGenerationError, match=r"All .* image generations failed"):
            await svc.generate(
                user_id=123,
                context={"keyword": "test", "image_settings": {}},
                count=3,
            )

    async def test_image_generate_no_image_data_in_response_raises_error(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """If response content has no extractable image, raise AIGenerationError."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_generation_result(
            content="This is just plain text, no image",
        )

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        with pytest.raises(AIGenerationError, match=r"All .* image generations failed"):
            await svc.generate(
                user_id=123,
                context={"keyword": "test", "image_settings": {}},
                count=1,
            )

    async def test_image_generate_variation_hints_applied(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """Multi-image should inject variation_hint and image_number into context."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_image_result()

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        await svc.generate(
            user_id=123,
            context={"keyword": "test", "image_settings": {}},
            count=2,
        )

        # Inspect the two calls to orchestrator.generate_without_rate_limit
        calls = mock_orchestrator.generate_without_rate_limit.call_args_list
        assert len(calls) == 2

        req_0 = calls[0].args[0]
        assert req_0.context["image_number"] == "1"
        assert req_0.context["total_images"] == "2"
        assert "variation_hint" in req_0.context

        req_1 = calls[1].args[0]
        assert req_1.context["image_number"] == "2"

    async def test_image_generate_single_no_variation_hint(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """Single image (count=1) should NOT have variation_hint / image_number."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_image_result()

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator)

        await svc.generate(
            user_id=123,
            context={"keyword": "test", "image_settings": {}},
            count=1,
        )

        req = mock_orchestrator.generate_without_rate_limit.call_args.args[0]
        assert "image_number" not in req.context
        assert "variation_hint" not in req.context

    async def test_image_generate_calls_batch_rate_limit(
        self, mock_orchestrator: AsyncMock
    ) -> None:
        """ImageService should call check_batch on rate_limiter before generation (H14)."""
        mock_orchestrator.generate_without_rate_limit.return_value = _make_image_result()
        mock_rate_limiter = AsyncMock()
        mock_rate_limiter.check_batch = AsyncMock()

        from services.ai.images import ImageService

        svc = ImageService(orchestrator=mock_orchestrator, rate_limiter=mock_rate_limiter)

        await svc.generate(
            user_id=123,
            context={"keyword": "test", "image_settings": {}},
            count=4,
        )

        mock_rate_limiter.check_batch.assert_awaited_once_with(123, "image_generation", 4)


# ---------------------------------------------------------------------------
# ReviewService
# ---------------------------------------------------------------------------


class TestReviewService:
    """Tests for services.ai.reviews.ReviewService."""

    async def test_review_generate_success_returns_result(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Successful review generation returns GenerationResult."""
        review_content = {
            "reviews": [
                {
                    "author": "Ivan",
                    "date": "2026-01-15",
                    "rating": 5,
                    "text": "Excellent service!",
                    "pros": "Fast delivery",
                    "cons": "None",
                },
            ],
        }
        mock_orchestrator.generate.return_value = _make_generation_result(
            content=review_content,
        )

        with (
            patch("services.ai.reviews.ProjectsRepository") as MockProjRepo,
            patch("services.ai.reviews.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.reviews import ReviewService

            svc = ReviewService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            result = await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                quantity=3,
            )

        assert isinstance(result, GenerationResult)
        assert "reviews" in result.content  # type: ignore[operator]
        mock_orchestrator.generate.assert_awaited_once()

    async def test_review_generate_context_includes_quantity(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Generation context must include quantity as string."""
        mock_orchestrator.generate.return_value = _make_generation_result()

        with (
            patch("services.ai.reviews.ProjectsRepository") as MockProjRepo,
            patch("services.ai.reviews.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.reviews import ReviewService

            svc = ReviewService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
                quantity=5,
            )

        request = mock_orchestrator.generate.call_args.args[0]
        assert request.context["quantity"] == "5"
        assert request.task == "review"

    async def test_review_generate_project_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing project raises AIGenerationError."""
        with (
            patch("services.ai.reviews.ProjectsRepository") as MockProjRepo,
            patch("services.ai.reviews.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=None)
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.reviews import ReviewService

            svc = ReviewService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=999,
                    category_id=1,
                    quantity=3,
                )

        mock_orchestrator.generate.assert_not_awaited()

    async def test_review_generate_category_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing category raises AIGenerationError."""
        with (
            patch("services.ai.reviews.ProjectsRepository") as MockProjRepo,
            patch("services.ai.reviews.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(return_value=None)

            from services.ai.reviews import ReviewService

            svc = ReviewService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=1,
                    category_id=999,
                    quantity=3,
                )


# ---------------------------------------------------------------------------
# DescriptionService
# ---------------------------------------------------------------------------


class TestDescriptionService:
    """Tests for services.ai.description.DescriptionService."""

    async def test_description_generate_success_returns_result(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Successful description generation returns GenerationResult with text content."""
        mock_orchestrator.generate.return_value = _make_generation_result(
            content="Professional SEO services for your business.",
        )

        with (
            patch("services.ai.description.ProjectsRepository") as MockProjRepo,
            patch("services.ai.description.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.description import DescriptionService

            svc = DescriptionService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            result = await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
            )

        assert isinstance(result, GenerationResult)
        assert isinstance(result.content, str)
        assert "SEO" in result.content
        mock_orchestrator.generate.assert_awaited_once()

    async def test_description_generate_context_includes_keywords_sample(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Context should include keywords_sample from category keywords."""
        mock_orchestrator.generate.return_value = _make_generation_result(
            content="Description text",
        )

        with (
            patch("services.ai.description.ProjectsRepository") as MockProjRepo,
            patch("services.ai.description.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.description import DescriptionService

            svc = DescriptionService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
            )

        request = mock_orchestrator.generate.call_args.args[0]
        assert request.context["keywords_sample"] == "test keyword"
        assert request.context["category_name"] == "Test Cat"
        assert request.task == "description"
        # description has no response_schema (returns plain text)
        assert request.response_schema is None

    async def test_description_generate_empty_keywords_shows_fallback(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Category with no keywords should use fallback text."""
        mock_orchestrator.generate.return_value = _make_generation_result(
            content="Description text",
        )

        with (
            patch("services.ai.description.ProjectsRepository") as MockProjRepo,
            patch("services.ai.description.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(keywords=[]),
            )

            from services.ai.description import DescriptionService

            svc = DescriptionService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
            )

        request = mock_orchestrator.generate.call_args.args[0]
        assert request.context["keywords_sample"] == "\u043d\u0435 \u0437\u0430\u0434\u0430\u043d\u044b"

    async def test_description_generate_reviews_excerpt_included(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Reviews excerpt should be included in context when reviews exist."""
        mock_orchestrator.generate.return_value = _make_generation_result(
            content="Description text",
        )
        category = _make_category(
            reviews=[
                {"text": "Awesome product, I love it!", "author": "A"},
                {"text": "Good quality", "author": "B"},
            ],
        )

        with (
            patch("services.ai.description.ProjectsRepository") as MockProjRepo,
            patch("services.ai.description.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(return_value=category)

            from services.ai.description import DescriptionService

            svc = DescriptionService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            await svc.generate(
                user_id=123,
                project_id=1,
                category_id=1,
            )

        request = mock_orchestrator.generate.call_args.args[0]
        assert "Awesome product" in request.context["reviews_excerpt"]
        assert "Good quality" in request.context["reviews_excerpt"]

    async def test_description_generate_project_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing project raises AIGenerationError."""
        with (
            patch("services.ai.description.ProjectsRepository") as MockProjRepo,
            patch("services.ai.description.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(return_value=None)
            MockCatRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_category(),
            )

            from services.ai.description import DescriptionService

            svc = DescriptionService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=999,
                    category_id=1,
                )

        mock_orchestrator.generate.assert_not_awaited()

    async def test_description_generate_category_not_found_raises_error(
        self, mock_orchestrator: AsyncMock, mock_db: MagicMock
    ) -> None:
        """Missing category raises AIGenerationError."""
        with (
            patch("services.ai.description.ProjectsRepository") as MockProjRepo,
            patch("services.ai.description.CategoriesRepository") as MockCatRepo,
        ):
            MockProjRepo.return_value.get_by_id = AsyncMock(
                return_value=_make_project(),
            )
            MockCatRepo.return_value.get_by_id = AsyncMock(return_value=None)

            from services.ai.description import DescriptionService

            svc = DescriptionService(orchestrator=mock_orchestrator, db=mock_db)
            svc._projects = MockProjRepo.return_value
            svc._categories = MockCatRepo.return_value

            with pytest.raises(AIGenerationError, match="not found"):
                await svc.generate(
                    user_id=123,
                    project_id=1,
                    category_id=999,
                )


# ---------------------------------------------------------------------------
# ImageService._extract_image — static method unit tests
# ---------------------------------------------------------------------------


class TestImageExtractImage:
    """Tests for ImageService._extract_image static helper."""

    def test_extract_image_from_data_uri(self) -> None:
        """Extracts image from data:image/png;base64,... format."""
        from services.ai.images import ImageService

        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        encoded = base64.b64encode(raw_bytes).decode()
        data_uri = f"data:image/png;base64,{encoded}"

        result = ImageService._extract_image(data_uri)

        assert result is not None
        assert result.mime == "image/png"
        assert result.data == raw_bytes

    def test_extract_image_from_raw_base64(self) -> None:
        """Extracts image from raw base64 string (no data URI prefix)."""
        from services.ai.images import ImageService

        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        encoded = base64.b64encode(raw_bytes).decode()

        result = ImageService._extract_image(encoded)

        assert result is not None
        assert result.mime == "image/png"
        assert result.data == raw_bytes

    def test_extract_image_from_dict_inline_data(self) -> None:
        """Extracts image from dict with inline_data key."""
        from services.ai.images import ImageService

        raw_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        encoded = base64.b64encode(raw_bytes).decode()
        content = {
            "inline_data": {
                "data": encoded,
                "mime_type": "image/jpeg",
            },
        }

        result = ImageService._extract_image(content)

        assert result is not None
        assert result.mime == "image/jpeg"

    def test_extract_image_returns_none_for_plain_text(self) -> None:
        """Non-image text content returns None."""
        from services.ai.images import ImageService

        result = ImageService._extract_image("just some text")
        assert result is None

    def test_extract_image_returns_none_for_empty_dict(self) -> None:
        """Empty dict returns None."""
        from services.ai.images import ImageService

        result = ImageService._extract_image({})
        assert result is None
