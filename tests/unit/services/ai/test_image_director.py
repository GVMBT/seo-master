"""Tests for ImageDirectorService (§7.4.2).

Covers:
- Successful plan generation with structured output
- E54: graceful degradation when Director fails
- Parsing edge cases (missing fields, invalid data)
- Template context building
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.ai.image_director import (
    DIRECTOR_SCHEMA,
    DirectorResult,
    ImageDirectorContext,
    ImageDirectorService,
    ImagePlan,
)
from services.ai.orchestrator import GenerationResult


def _make_context(**overrides: object) -> ImageDirectorContext:
    """Create a test ImageDirectorContext with defaults."""
    defaults: dict = {
        "article_title": "Кухни на заказ в Москве",
        "article_summary": "Статья о кухнях на заказ. " * 50,
        "company_name": "МосКухни",
        "niche": "home_renovation",
        "image_count": 3,
        "target_sections": [
            {"index": 1, "heading": "Фасады из массива дуба", "context": "Дуб — популярный материал..."},
            {"index": 3, "heading": "Фурнитура Blum", "context": "Фурнитура определяет удобство..."},
            {"index": 5, "heading": "Готовые проекты", "context": "Портфолио наших работ..."},
        ],
        "brand_colors": "primary: #8B4513, accent: #DAA520",
        "image_style": "photorealism, professional",
    }
    defaults.update(overrides)
    return ImageDirectorContext(**defaults)


def _make_ai_result(content: dict | str | None = None) -> GenerationResult:
    """Create a mock GenerationResult."""
    if content is None:
        content = {
            "images": [
                {
                    "section_index": 1,
                    "concept": "Close-up of oak cabinet door grain",
                    "prompt": "Professional interior photo, close-up oak cabinet door, warm lighting",
                    "negative_prompt": "text, watermark, blurry",
                    "aspect_ratio": "4:3",
                },
                {
                    "section_index": 3,
                    "concept": "Blum hardware mechanism detail",
                    "prompt": "Macro photo of Blum soft-close hinge mechanism, studio lighting",
                    "negative_prompt": "text, watermark, cartoon",
                    "aspect_ratio": "1:1",
                },
                {
                    "section_index": 5,
                    "concept": "Completed modern kitchen panorama",
                    "prompt": "Wide angle modern kitchen interior, bright natural light from window",
                    "negative_prompt": "text, watermark, people, low quality",
                    "aspect_ratio": "16:9",
                },
            ],
            "visual_narrative": "Detail → mechanism → full view progression",
        }
    return GenerationResult(
        content=content,
        model_used="deepseek/deepseek-v3.2",
        input_tokens=800,
        output_tokens=400,
        cost_usd=0.001,
        generation_time_ms=3200,
        prompt_version="image_director_v1",
        fallback_used=False,
    )


class TestImageDirectorSuccess:
    """Happy path: Director returns structured plans."""

    async def test_plan_images_returns_director_result(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        assert isinstance(result, DirectorResult)
        assert len(result.images) == 3
        assert result.visual_narrative == "Detail → mechanism → full view progression"
        assert result.model_used == "deepseek/deepseek-v3.2"
        assert result.cost_usd == pytest.approx(0.001)

    async def test_plan_images_parses_image_plans(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        plan = result.images[0]
        assert isinstance(plan, ImagePlan)
        assert plan.section_index == 1
        assert plan.concept == "Close-up of oak cabinet door grain"
        assert "oak" in plan.prompt.lower()
        assert plan.negative_prompt == "text, watermark, blurry"
        assert plan.aspect_ratio == "4:3"

    async def test_plan_images_sends_correct_request(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        await service.plan_images(_make_context(), user_id=42)

        call = orchestrator.generate.call_args[0][0]
        assert call.task == "image_director"
        assert call.user_id == 42
        assert call.response_schema is DIRECTOR_SCHEMA
        assert call.context["article_title"] == "Кухни на заказ в Москве"
        assert call.context["image_count"] == 3
        assert len(call.context["target_sections"]) == 3

    async def test_article_summary_truncated_to_500_words(self) -> None:
        long_summary = "слово " * 1000  # 1000 words
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        await service.plan_images(_make_context(article_summary=long_summary), user_id=1)

        ctx = orchestrator.generate.call_args[0][0].context
        word_count = len(ctx["article_summary"].split())
        assert word_count <= 500

    async def test_brand_colors_dict_formatted(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        await service.plan_images(
            _make_context(brand_colors={"primary": "#8B4513", "accent": "#DAA520"}),
            user_id=1,
        )

        ctx = orchestrator.generate.call_args[0][0].context
        assert "primary: #8B4513" in ctx["brand_colors"]
        assert "accent: #DAA520" in ctx["brand_colors"]

    async def test_brand_colors_empty_string(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        await service.plan_images(_make_context(brand_colors=""), user_id=1)

        ctx = orchestrator.generate.call_args[0][0].context
        assert ctx["brand_colors"] == ""

    async def test_image_style_includes_tone(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result()

        service = ImageDirectorService(orchestrator)
        await service.plan_images(
            _make_context(image_style="watercolor", image_tone="warm"),
            user_id=1,
        )

        ctx = orchestrator.generate.call_args[0][0].context
        assert "watercolor" in ctx["image_style"]
        assert "warm" in ctx["image_style"]


class TestImageDirectorE54Fallback:
    """E54: Director fails → returns None (caller falls back to mechanical prompts)."""

    async def test_ai_error_returns_none(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.side_effect = RuntimeError("DeepSeek timeout")

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is None

    async def test_string_response_returns_none(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content="unexpected string")

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is None

    async def test_empty_images_returns_none(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content={"images": [], "visual_narrative": ""})

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is None

    async def test_missing_images_key_returns_none(self) -> None:
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content={"visual_narrative": "story"})

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is None


class TestImageDirectorParsing:
    """Edge cases in result parsing."""

    async def test_partial_plans_skips_invalid(self) -> None:
        """If one plan is invalid, others still work."""
        content = {
            "images": [
                {
                    "section_index": 1,
                    "concept": "Good plan",
                    "prompt": "A valid prompt",
                    "negative_prompt": "bad stuff",
                    "aspect_ratio": "4:3",
                },
                {
                    # Missing required "prompt" key
                    "section_index": 3,
                    "concept": "Broken plan",
                },
            ],
            "visual_narrative": "partial",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        assert len(result.images) == 1
        assert result.images[0].section_index == 1

    async def test_all_plans_invalid_returns_none(self) -> None:
        content = {
            "images": [
                {"section_index": "not_int"},  # invalid
            ],
            "visual_narrative": "",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is None

    async def test_default_negative_prompt(self) -> None:
        """Missing negative_prompt uses default."""
        content = {
            "images": [
                {
                    "section_index": 1,
                    "concept": "test",
                    "prompt": "a prompt",
                    "aspect_ratio": "16:9",
                    # negative_prompt omitted
                },
            ],
            "visual_narrative": "",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        assert "watermark" in result.images[0].negative_prompt

    async def test_default_aspect_ratio(self) -> None:
        """Missing aspect_ratio defaults to 4:3."""
        content = {
            "images": [
                {
                    "section_index": 1,
                    "concept": "test",
                    "prompt": "a prompt",
                    "negative_prompt": "bad",
                    # aspect_ratio omitted
                },
            ],
            "visual_narrative": "",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        assert result.images[0].aspect_ratio == "4:3"

    async def test_invalid_aspect_ratio_falls_back_to_default(self) -> None:
        content = {
            "images": [
                {
                    "section_index": 1,
                    "concept": "test",
                    "prompt": "a prompt",
                    "negative_prompt": "bad",
                    "aspect_ratio": "7:3",  # invalid
                },
            ],
            "visual_narrative": "",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        assert result.images[0].aspect_ratio == "4:3"

    async def test_plans_capped_to_image_count(self) -> None:
        """Director returns more plans than requested → capped."""
        content = {
            "images": [
                {
                    "section_index": i,
                    "prompt": f"prompt {i}",
                    "concept": "c",
                    "negative_prompt": "n",
                    "aspect_ratio": "4:3",
                }
                for i in range(5)
            ],
            "visual_narrative": "too many",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(image_count=2), user_id=42)

        assert result is not None
        assert len(result.images) == 2

    async def test_plan_without_prompt_filtered_out(self) -> None:
        """Plans with empty prompt are filtered."""
        content = {
            "images": [
                {"section_index": 1, "prompt": "valid", "concept": "c", "negative_prompt": "n", "aspect_ratio": "4:3"},
                {"section_index": 2, "prompt": "", "concept": "c", "negative_prompt": "n", "aspect_ratio": "4:3"},
            ],
            "visual_narrative": "",
        }
        orchestrator = AsyncMock()
        orchestrator.generate.return_value = _make_ai_result(content=content)

        service = ImageDirectorService(orchestrator)
        result = await service.plan_images(_make_context(), user_id=42)

        assert result is not None
        assert len(result.images) == 1
        assert result.images[0].section_index == 1


class TestDirectorSchema:
    """DIRECTOR_SCHEMA structure validation."""

    def test_schema_has_required_fields(self) -> None:
        schema = DIRECTOR_SCHEMA["schema"]
        assert "images" in schema["properties"]
        assert "visual_narrative" in schema["properties"]
        assert schema["required"] == ["images", "visual_narrative"]

    def test_image_item_schema(self) -> None:
        item = DIRECTOR_SCHEMA["schema"]["properties"]["images"]["items"]
        required = item["required"]
        assert "section_index" in required
        assert "prompt" in required
        assert "negative_prompt" in required
        assert "aspect_ratio" in required

    def test_aspect_ratio_enum(self) -> None:
        item = DIRECTOR_SCHEMA["schema"]["properties"]["images"]["items"]
        ar = item["properties"]["aspect_ratio"]
        assert ar["type"] == "string"
        assert "16:9" in ar["enum"]
        assert "4:3" in ar["enum"]
        assert "1:1" in ar["enum"]
