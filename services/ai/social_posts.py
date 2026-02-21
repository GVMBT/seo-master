"""Social post generation service — platform-specific posts.

Source of truth: API_CONTRACTS.md section 5 (social_v3.yaml).
Zero Telegram/Aiogram dependencies.
"""

from typing import Any

import nh3
import structlog

from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult

log = structlog.get_logger()

# Allowed tags for social post sanitization (ARCHITECTURE.md §5.8)
# Telegram HTML supports: b, strong, i, em, u, s, a, code, pre, blockquote
# VK/Pinterest: plain text (strip all tags)
_SOCIAL_TAGS: dict[str, set[str]] = {
    "telegram": {"b", "strong", "i", "em", "u", "s", "a", "code", "pre", "blockquote"},
    "vk": set(),
    "pinterest": set(),
}
_SOCIAL_ATTRS: dict[str, set[str]] = {
    "a": {"href"},
}

# JSON Schema for structured output
SOCIAL_POST_SCHEMA: dict[str, Any] = {
    "name": "social_post_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "hashtags": {
                "type": "array",
                "items": {"type": "string"},
            },
            "pin_title": {"type": "string"},
        },
        "required": ["text", "hashtags", "pin_title"],
        "additionalProperties": False,
    },
}


class SocialPostService:
    """Generates social media posts for TG/VK/Pinterest."""

    def __init__(self, orchestrator: AIOrchestrator, db: SupabaseClient) -> None:
        self._orchestrator = orchestrator
        self._db = db
        self._projects = ProjectsRepository(db)
        self._categories = CategoriesRepository(db)

    async def generate(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        platform: str,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> GenerationResult:
        """Generate a platform-specific social post.

        Returns GenerationResult with content as dict: {text, hashtags, pin_title}
        """
        project = await self._projects.get_by_id(project_id)
        category = await self._categories.get_by_id(category_id)

        if project is None or category is None:
            from bot.exceptions import AIGenerationError

            raise AIGenerationError(message="Project or category not found")

        text_settings = overrides or category.text_settings or {}
        styles = text_settings.get("styles")
        if isinstance(styles, str):
            styles = [styles]
        if not styles:
            legacy = text_settings.get("style")
            styles = [legacy] if legacy else ["Разговорный"]

        context: dict[str, Any] = {
            "keyword": keyword,
            "platform": platform,
            "company_name": project.company_name,
            "specialization": project.specialization,
            "advantages": project.advantages or "",
            "company_description": project.description or "",
            "experience": project.experience or "",
            "website_url": project.website_url or "",
            "language": "ru",
            "text_style": ", ".join(s for s in styles if s) or "Разговорный",
            "words_min": text_settings.get("words_min", 100),
            "words_max": text_settings.get("words_max", 300),
            "prices_excerpt": (category.prices or "")[:300],
        }

        request = GenerationRequest(
            task="social_post",
            context=context,
            user_id=user_id,
            response_schema=SOCIAL_POST_SCHEMA,
        )

        result = await self._orchestrator.generate(request)

        # Sanitize generated text with nh3 (ARCHITECTURE.md §5.8)
        if isinstance(result.content, dict) and "text" in result.content:
            allowed_tags = _SOCIAL_TAGS.get(platform, set())
            result.content["text"] = nh3.clean(
                result.content["text"],
                tags=allowed_tags,
                attributes=_SOCIAL_ATTRS,
            )

        return result
