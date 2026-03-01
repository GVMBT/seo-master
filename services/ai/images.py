"""Image generation service — Gemini multi-image via OpenRouter.

Source of truth: API_CONTRACTS.md section 7.
Multi-image: N separate requests with variation.
Partial failure OK (K>=1 succeed).
Returns raw bytes — storage upload is caller's responsibility.
"""

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import structlog

from bot.exceptions import AIGenerationError
from services.ai.image_director import ImagePlan
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult
from services.ai.rate_limiter import RateLimiter

log = structlog.get_logger()

# Default variation angles for multi-image (§7.4.1)
DEFAULT_ANGLES: list[str] = [
    "крупный план",
    "общий план",
    "детали",
    "в контексте использования",
]


@dataclass
class GeneratedImage:
    """A single generated image (raw bytes)."""

    data: bytes
    mime: str
    width: int
    height: int


def _flatten_image_settings(context: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested image_settings into top-level prompt variables.

    image_v1.yaml expects flat keys: style, tone, camera_instruction, etc.
    ImageService receives image_settings as a nested dict from preview.py.
    This function extracts the first value from each list-field and maps it
    to the flat key expected by the prompt template.
    """
    flat = dict(context)
    settings = flat.get("image_settings", {})

    # styles[] or style (legacy flat string from UI) → style
    styles = settings.get("styles", [])
    if isinstance(styles, str):
        styles = [styles]
    if not styles:
        legacy_style = settings.get("style")
        if legacy_style:
            styles = [legacy_style]
    if styles:
        flat.setdefault("style", styles[0])

    # tones[] or tone (legacy) → tone
    tones = settings.get("tones", [])
    if isinstance(tones, str):
        tones = [tones]
    if not tones:
        legacy_tone = settings.get("tone")
        if legacy_tone:
            tones = [legacy_tone]
    if tones:
        flat.setdefault("tone", tones[0])

    # cameras[] → camera_instruction (join into one instruction)
    cameras = settings.get("cameras", [])
    if cameras:
        flat.setdefault("camera_instruction", f"Камера: {', '.join(cameras)}.")

    # text_on_image → text_on_image_instruction
    text_on_image = settings.get("text_on_image")
    if text_on_image:
        flat.setdefault("text_on_image_instruction", text_on_image)

    return flat


class ImageService:
    """Generates images via Gemini models through OpenRouter."""

    def __init__(
        self,
        orchestrator: AIOrchestrator,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._rate_limiter = rate_limiter

    async def generate(
        self,
        user_id: int,
        context: dict[str, Any],
        count: int = 1,
        block_contexts: list[str] | None = None,
        director_plans: list[ImagePlan] | None = None,
    ) -> list[GeneratedImage]:
        """Generate N images with variation and optional block context.

        Args:
            block_contexts: Per-image section context from distribute_images() (§7.4.1).
                If provided, each image prompt includes the H2-section text.
                Length should match count (or be shorter — missing entries get "").

        Returns list of GeneratedImage (raw bytes). K >= 1 of N must succeed.
        Raises AIGenerationError if ALL fail.
        Raises RateLimitError if batch rate limit check fails.
        """
        # Reserve N rate limit slots ONCE before parallel generation (H14)
        if self._rate_limiter is not None:
            await self._rate_limiter.check_batch(
                user_id,
                "image_generation",
                count,
            )

        image_settings = context.get("image_settings", {})
        formats = image_settings.get("formats", ["1:1"])
        angles = image_settings.get("angles", [])
        if not angles:
            angles = DEFAULT_ANGLES

        tasks = []
        for i in range(count):
            # Build per-image context with variation
            img_context = dict(context)
            img_context["image_settings"] = dict(image_settings)

            # Round-robin aspect ratio
            img_context["image_settings"]["formats"] = [formats[i % len(formats)]]

            # Director overrides mechanical prompt + aspect ratio (§7.4.2)
            if director_plans and i < len(director_plans):
                plan = director_plans[i]
                img_context["director_prompt"] = plan.prompt
                img_context["director_negative_prompt"] = plan.negative_prompt
                img_context["image_settings"]["formats"] = [plan.aspect_ratio]

            # Block-aware context (§7.4.1): section text for targeted image generation
            if block_contexts and i < len(block_contexts):
                img_context["block_context"] = block_contexts[i]

            if count > 1:
                img_context["image_number"] = str(i + 1)
                img_context["total_images"] = str(count)
                img_context["variation_hint"] = angles[i % len(angles)]

            tasks.append(self._generate_single(user_id, img_context))

        # Run all in parallel, collect results
        results = await asyncio.gather(*tasks, return_exceptions=True)

        images: list[GeneratedImage] = []
        errors: list[str] = []
        for i, result in enumerate(results):
            if isinstance(result, BaseException):
                errors.append(f"Image {i + 1}: {result}")
                log.warning("image_generation_partial_failure", index=i, error=str(result))
            elif isinstance(result, GeneratedImage):
                images.append(result)

        if not images:
            raise AIGenerationError(
                message=f"All {count} image generations failed: {'; '.join(errors)}",
            )

        if errors:
            log.info(
                "image_generation_partial",
                succeeded=len(images),
                failed=len(errors),
                total=count,
            )

        return images

    async def _generate_single(
        self,
        user_id: int,
        context: dict[str, Any],
    ) -> GeneratedImage:
        """Generate a single image.

        Rate limiting is handled at the batch level in generate(),
        so individual calls go directly to the orchestrator without
        per-request rate limit checks (skip_rate_limit=True).
        """
        # Flatten image_settings into top-level keys for prompt template (image_v1.yaml)
        prompt_context = _flatten_image_settings(context)

        request = GenerationRequest(
            task="image",
            context=prompt_context,
            user_id=user_id,
        )

        # Call orchestrator._do_generate directly to skip per-request rate limit
        # check (rate limit was already reserved for the full batch in generate()).
        result: GenerationResult = await self._orchestrator.generate_without_rate_limit(
            request,
        )

        # Parse image from response
        # Gemini returns images in message.content as multimodal content
        raw = result.content
        image_data = self._extract_image(raw)

        if image_data is None:
            raise AIGenerationError(message="No image data in response")

        return image_data

    @staticmethod
    def _extract_image(content: Any) -> GeneratedImage | None:
        """Extract image bytes from OpenRouter/Gemini response content.

        Response may contain:
        - A string with base64 data URI: "data:image/png;base64,..."
        - A string with raw base64
        - A dict/list with image objects
        """
        if isinstance(content, str):
            # Try data URI format
            if content.startswith("data:image/"):
                parts = content.split(",", 1)
                if len(parts) == 2:
                    mime = parts[0].split(":")[1].split(";")[0]
                    data = base64.b64decode(parts[1])
                    return GeneratedImage(data=data, mime=mime, width=0, height=0)

            # Try raw base64
            try:
                data = base64.b64decode(content)
                if len(data) > 100:  # Reasonable image size
                    return GeneratedImage(data=data, mime="image/png", width=0, height=0)
            except Exception:
                log.debug("base64_probe_failed")

        if isinstance(content, dict):
            # Check for inline_data pattern
            if "inline_data" in content:
                inline = content["inline_data"]
                data = base64.b64decode(inline.get("data", ""))
                mime = inline.get("mime_type", "image/png")
                return GeneratedImage(data=data, mime=mime, width=0, height=0)

            # Check for images array
            images = content.get("images", [])
            if images and isinstance(images[0], str):
                return ImageService._extract_image(images[0])

        log.warning(
            "image_extract_failed",
            content_type=type(content).__name__,
            preview=str(content)[:200],
        )
        return None
