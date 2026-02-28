"""Tests for services.ai.images — _flatten_image_settings + ImageService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.ai.images import ImageService, _flatten_image_settings
from services.ai.orchestrator import GenerationResult


class TestFlattenImageSettings:
    """Unit tests for _flatten_image_settings helper."""

    def test_empty_settings(self) -> None:
        ctx = {"keyword": "test", "image_settings": {}}
        result = _flatten_image_settings(ctx)
        # No flat keys added — PromptEngine will use YAML defaults
        assert "style" not in result
        assert "tone" not in result

    def test_styles_first_element(self) -> None:
        ctx = {"image_settings": {"styles": ["Минимализм", "Реализм"]}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Минимализм"

    def test_tones_first_element(self) -> None:
        ctx = {"image_settings": {"tones": ["Тёплый", "Холодный"]}}
        result = _flatten_image_settings(ctx)
        assert result["tone"] == "Тёплый"

    def test_cameras_joined(self) -> None:
        ctx = {"image_settings": {"cameras": ["макро", "широкий угол"]}}
        result = _flatten_image_settings(ctx)
        assert result["camera_instruction"] == "Камера: макро, широкий угол."

    def test_text_on_image(self) -> None:
        ctx = {"image_settings": {"text_on_image": "Добавь логотип в угол"}}
        result = _flatten_image_settings(ctx)
        assert result["text_on_image_instruction"] == "Добавь логотип в угол"

    def test_no_image_settings_key(self) -> None:
        ctx = {"keyword": "test"}
        result = _flatten_image_settings(ctx)
        assert result["keyword"] == "test"
        assert "style" not in result

    def test_does_not_overwrite_explicit_style(self) -> None:
        """If caller already set 'style' in context, don't overwrite."""
        ctx = {"style": "Акварель", "image_settings": {"styles": ["Минимализм"]}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Акварель"

    def test_preserves_other_context_keys(self) -> None:
        ctx = {
            "keyword": "SEO",
            "company_name": "Acme",
            "image_settings": {"styles": ["Flat"]},
        }
        result = _flatten_image_settings(ctx)
        assert result["keyword"] == "SEO"
        assert result["company_name"] == "Acme"
        assert result["style"] == "Flat"

    def test_full_settings(self) -> None:
        ctx = {
            "keyword": "ремонт",
            "image_settings": {
                "styles": ["Фотореализм"],
                "tones": ["Профессиональный"],
                "cameras": ["портрет"],
                "text_on_image": "Без текста",
                "formats": ["16:9"],
                "count": 2,
            },
        }
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Фотореализм"
        assert result["tone"] == "Профессиональный"
        assert result["camera_instruction"] == "Камера: портрет."
        assert result["text_on_image_instruction"] == "Без текста"
        # image_settings still present for ImageService internal use
        assert "image_settings" in result

    def test_empty_lists_ignored(self) -> None:
        ctx = {"image_settings": {"styles": [], "tones": [], "cameras": []}}
        result = _flatten_image_settings(ctx)
        assert "style" not in result
        assert "tone" not in result
        assert "camera_instruction" not in result

    def test_legacy_flat_style_from_ui(self) -> None:
        """UI saves image_settings.style as flat string (not styles array)."""
        ctx = {"image_settings": {"style": "Минимализм"}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Минимализм"

    def test_legacy_flat_tone(self) -> None:
        ctx = {"image_settings": {"tone": "Тёплый"}}
        result = _flatten_image_settings(ctx)
        assert result["tone"] == "Тёплый"

    def test_styles_array_takes_priority_over_legacy(self) -> None:
        """If both styles[] and style exist, styles[] wins."""
        ctx = {"image_settings": {"styles": ["Акварель"], "style": "Минимализм"}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Акварель"

    def test_styles_as_string_not_list(self) -> None:
        """Handle edge case where styles is a string instead of list."""
        ctx = {"image_settings": {"styles": "Мультяшный"}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Мультяшный"

    def test_tones_as_string_not_list(self) -> None:
        ctx = {"image_settings": {"tones": "Холодный"}}
        result = _flatten_image_settings(ctx)
        assert result["tone"] == "Холодный"


# ---------------------------------------------------------------------------
# ImageService.generate() — block_contexts parameter
# ---------------------------------------------------------------------------


def _fake_image_result() -> GenerationResult:
    """Return a GenerationResult with a minimal base64 PNG data URI."""
    # 1x1 red pixel PNG as base64 data URI
    return GenerationResult(
        content="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
        model_used="google/gemini-3-pro-image-preview",
        prompt_version="v1",
        fallback_used=False,
        input_tokens=100,
        output_tokens=200,
        cost_usd=0.02,
        generation_time_ms=3000,
    )


class TestImageServiceBlockContexts:
    """Verify block_contexts flow into per-image context."""

    @pytest.fixture
    def orchestrator(self) -> AsyncMock:
        orch = AsyncMock()
        orch.generate_without_rate_limit = AsyncMock(return_value=_fake_image_result())
        return orch

    async def test_block_contexts_passed_to_generate(self, orchestrator: AsyncMock) -> None:
        svc = ImageService(orchestrator)
        contexts = ["Введение. Текст про SEO.", "Материалы и обзоры."]
        await svc.generate(
            user_id=1,
            context={"keyword": "seo", "content_type": "article",
                     "company_name": "Co", "specialization": "SEO",
                     "image_settings": {}},
            count=2,
            block_contexts=contexts,
        )

        # Each call should have block_context in the context dict
        calls = orchestrator.generate_without_rate_limit.call_args_list
        assert len(calls) == 2
        req0 = calls[0].args[0]
        req1 = calls[1].args[0]
        assert req0.context["block_context"] == "Введение. Текст про SEO."
        assert req1.context["block_context"] == "Материалы и обзоры."

    async def test_no_block_contexts_no_key(self, orchestrator: AsyncMock) -> None:
        svc = ImageService(orchestrator)
        await svc.generate(
            user_id=1,
            context={"keyword": "seo", "content_type": "article",
                     "company_name": "Co", "specialization": "SEO",
                     "image_settings": {}},
            count=1,
            block_contexts=None,
        )

        calls = orchestrator.generate_without_rate_limit.call_args_list
        req0 = calls[0].args[0]
        assert "block_context" not in req0.context

    async def test_fewer_contexts_than_images(self, orchestrator: AsyncMock) -> None:
        """If block_contexts shorter than count, extra images get no context."""
        svc = ImageService(orchestrator)
        await svc.generate(
            user_id=1,
            context={"keyword": "seo", "content_type": "article",
                     "company_name": "Co", "specialization": "SEO",
                     "image_settings": {}},
            count=3,
            block_contexts=["Context for first only"],
        )

        calls = orchestrator.generate_without_rate_limit.call_args_list
        assert len(calls) == 3
        assert calls[0].args[0].context["block_context"] == "Context for first only"
        assert "block_context" not in calls[1].args[0].context
        assert "block_context" not in calls[2].args[0].context
