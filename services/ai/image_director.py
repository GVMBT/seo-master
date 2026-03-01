"""Image Director — AI prompt engineering layer for image generation.

Analyzes article content and target sections, then creates specific,
purposeful image prompts instead of generic mechanical ones.

Source of truth: API_CONTRACTS.md §7.4.2
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from services.ai.orchestrator import AIOrchestrator, GenerationRequest

log = structlog.get_logger()

# JSON Schema for structured output (DeepSeek V3.2 / Gemini Flash)
DIRECTOR_SCHEMA: dict[str, Any] = {
    "name": "image_director_output",
    "strict": True,
    "schema": {
        "type": "object",
        "required": ["images", "visual_narrative"],
        "additionalProperties": False,
        "properties": {
            "images": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": [
                        "section_index",
                        "concept",
                        "prompt",
                        "negative_prompt",
                        "aspect_ratio",
                    ],
                    "additionalProperties": False,
                    "properties": {
                        "section_index": {
                            "type": "integer",
                            "description": "Block index this image is for",
                        },
                        "concept": {
                            "type": "string",
                            "description": "Brief description of the visual concept",
                        },
                        "prompt": {
                            "type": "string",
                            "description": "Detailed image generation prompt in English",
                        },
                        "negative_prompt": {
                            "type": "string",
                            "description": "What to avoid in the image",
                        },
                        "aspect_ratio": {
                            "type": "string",
                            "enum": [
                                "1:1",
                                "3:2",
                                "4:3",
                                "16:9",
                            ],
                            "description": "Best aspect ratio for this content",
                        },
                    },
                },
            },
            "visual_narrative": {
                "type": "string",
                "description": "How images work together as a visual story",
            },
        },
    },
}

# Default negative prompt when Director is unavailable (E54 fallback)
_DEFAULT_NEGATIVE = "text, watermark, blurry, low quality, cartoon, illustration, anime"

_VALID_ASPECT_RATIOS = {"1:1", "3:2", "4:3", "16:9"}
_DEFAULT_ASPECT_RATIO = "4:3"


@dataclass
class ImagePlan:
    """Plan for a single image, created by Image Director."""

    section_index: int
    concept: str
    prompt: str
    negative_prompt: str
    aspect_ratio: str


@dataclass
class DirectorResult:
    """Full result from Image Director."""

    images: list[ImagePlan]
    visual_narrative: str
    model_used: str = ""
    cost_usd: float = 0.0


@dataclass
class ImageDirectorContext:
    """Input context for Image Director."""

    article_title: str
    article_summary: str
    company_name: str
    niche: str
    image_count: int
    target_sections: list[dict[str, Any]]
    brand_colors: dict[str, str] | str = ""
    image_style: str = "photorealism, professional"
    image_tone: str = "professional"


class ImageDirectorService:
    """AI layer that crafts specific image prompts based on article content.

    Instead of mechanical prompts (keyword + style + block_context[:200]),
    Director analyzes the full article and each target section to create
    purposeful, compositionally-specific prompts.

    Graceful degradation (E54): if Director fails, returns None and caller
    falls back to mechanical prompts.
    """

    def __init__(self, orchestrator: AIOrchestrator) -> None:
        self._orchestrator = orchestrator

    async def plan_images(
        self,
        context: ImageDirectorContext,
        user_id: int,
    ) -> DirectorResult | None:
        """Analyze article and plan images with AI reasoning.

        Returns DirectorResult with per-image plans, or None on failure (E54).
        Plans are capped to context.image_count to avoid extra generations.
        """
        template_context = self._build_template_context(context)

        request = GenerationRequest(
            task="image_director",
            context=template_context,
            user_id=user_id,
            response_schema=DIRECTOR_SCHEMA,
        )

        try:
            result = await self._orchestrator.generate(request)
        except Exception:
            log.warning("image_director_skipped", reason="ai_error", exc_info=True)
            return None

        return self._parse_result(result.content, result.model_used, result.cost_usd, context.image_count)

    @staticmethod
    def _format_brand_colors(colors: dict[str, str] | str) -> str:
        """Convert brand_colors dict to string for prompt template."""
        if isinstance(colors, dict):
            return ", ".join(f"{k}: {v}" for k, v in colors.items())
        return colors

    def _build_template_context(self, ctx: ImageDirectorContext) -> dict[str, Any]:
        """Build context dict for Jinja2 prompt template."""
        # Truncate to ~500 words (spec §7.4.2)
        words = ctx.article_summary.split()[:500]
        return {
            "article_title": ctx.article_title,
            "article_summary": " ".join(words),
            "company_name": ctx.company_name,
            "niche": ctx.niche,
            "image_count": ctx.image_count,
            "target_sections": ctx.target_sections,
            "brand_colors": self._format_brand_colors(ctx.brand_colors),
            "image_style": f"{ctx.image_style}, {ctx.image_tone}",
        }

    def _parse_result(
        self,
        content: str | dict[str, Any],
        model_used: str,
        cost_usd: float,
        max_images: int = 10,
    ) -> DirectorResult | None:
        """Parse structured output into DirectorResult."""
        if isinstance(content, str):
            log.warning("image_director_skipped", reason="unexpected_string_response")
            return None

        images_raw = content.get("images")
        if not images_raw or not isinstance(images_raw, list):
            log.warning("image_director_skipped", reason="no_images_in_response")
            return None

        plans: list[ImagePlan] = []
        for img in images_raw:
            try:
                aspect = str(img.get("aspect_ratio", _DEFAULT_ASPECT_RATIO))
                if aspect not in _VALID_ASPECT_RATIOS:
                    aspect = _DEFAULT_ASPECT_RATIO
                plans.append(
                    ImagePlan(
                        section_index=int(img.get("section_index", 0)),
                        concept=str(img.get("concept", "")),
                        prompt=str(img.get("prompt", "")),
                        negative_prompt=str(img.get("negative_prompt", _DEFAULT_NEGATIVE)),
                        aspect_ratio=aspect,
                    )
                )
            except ValueError, TypeError:
                log.warning("image_director_plan_skip", image=img, exc_info=True)
                continue

        # Filter out plans without prompt (required field)
        plans = [p for p in plans if p.prompt]

        if not plans:
            log.warning("image_director_skipped", reason="all_plans_failed_to_parse")
            return None

        # Cap to requested image count (R3: avoid extra generations)
        plans = plans[:max_images]

        return DirectorResult(
            images=plans,
            visual_narrative=str(content.get("visual_narrative", "")),
            model_used=model_used,
            cost_usd=cost_usd,
        )
