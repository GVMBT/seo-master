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

    def __init__(
        self,
        orchestrator: AIOrchestrator,
        db: SupabaseClient,
        *,
        skip_rate_limit: bool = False,
    ) -> None:
        self._orchestrator = orchestrator
        self._db = db
        self._skip_rate_limit = skip_rate_limit
        self._projects = ProjectsRepository(db)
        self._categories = CategoriesRepository(db)

    async def _call_orchestrator(self, request: GenerationRequest) -> GenerationResult:
        """Call orchestrator, bypassing rate limit when skip_rate_limit is set."""
        if self._skip_rate_limit:
            return await self._orchestrator.generate_without_rate_limit(request)
        return await self._orchestrator.generate(request)

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

        result = await self._call_orchestrator(request)

        # Sanitize generated text with nh3 (ARCHITECTURE.md §5.8)
        if isinstance(result.content, dict) and "text" in result.content:
            allowed_tags = _SOCIAL_TAGS.get(platform, set())
            result.content["text"] = nh3.clean(
                result.content["text"],
                tags=allowed_tags,
                attributes=_SOCIAL_ATTRS,
            )

        # Enforce Pinterest hard limits (API: 500 description, 100 title)
        if platform == "pinterest" and isinstance(result.content, dict):
            _enforce_pinterest_limits(result.content)

        return result

    async def adapt_for_platform(
        self,
        original_text: str,
        source_platform: str,
        target_platform: str,
        user_id: int,
        project_id: int,
        keyword: str,
    ) -> GenerationResult:
        """Adapt existing social post for a different platform (cross-posting)."""
        project = await self._projects.get_by_id(project_id)
        if project is None:
            from bot.exceptions import AIGenerationError

            raise AIGenerationError(message="Project not found")

        context: dict[str, Any] = {
            "original_text": original_text,
            "source_platform": source_platform,
            "target_platform": target_platform,
            "keyword": keyword,
            "company_name": project.company_name,
            "specialization": project.specialization,
            "company_description": project.description or "",
            "website_url": project.website_url or "",
            "language": "ru",
        }

        request = GenerationRequest(
            task="cross_post",
            context=context,
            user_id=user_id,
            response_schema=SOCIAL_POST_SCHEMA,
        )

        result = await self._call_orchestrator(request)

        # Sanitize with nh3 for target platform
        if isinstance(result.content, dict) and "text" in result.content:
            allowed_tags = _SOCIAL_TAGS.get(target_platform, set())
            result.content["text"] = nh3.clean(
                result.content["text"],
                tags=allowed_tags,
                attributes=_SOCIAL_ATTRS,
            )

        # Enforce Pinterest hard limits for cross-posting too
        if target_platform == "pinterest" and isinstance(result.content, dict):
            _enforce_pinterest_limits(result.content)

        return result


# ---------------------------------------------------------------------------
# Pinterest hard limits
# ---------------------------------------------------------------------------

_PINTEREST_TEXT_LIMIT = 500
_PINTEREST_TITLE_LIMIT = 100
_PINTEREST_MAX_HASHTAGS = 5


def _enforce_pinterest_limits(content: dict[str, Any]) -> None:
    """Enforce Pinterest API limits on generated content (mutates in-place).

    - text: max 500 chars (truncate at sentence/word boundary)
    - pin_title: max 100 chars, fallback to text[:97]+'...' if empty
    - hashtags: max 5
    """
    # Truncate text
    text = content.get("text", "")
    if len(text) > _PINTEREST_TEXT_LIMIT:
        text = _truncate_at_boundary(text, _PINTEREST_TEXT_LIMIT)
        content["text"] = text

    # pin_title: fallback + truncate
    pin_title = content.get("pin_title", "")
    if not pin_title:
        if len(text) > _PINTEREST_TITLE_LIMIT:
            pin_title = _truncate_at_boundary(text, _PINTEREST_TITLE_LIMIT - 3) + "..."
        else:
            pin_title = text
    elif len(pin_title) > _PINTEREST_TITLE_LIMIT:
        pin_title = _truncate_at_boundary(pin_title, _PINTEREST_TITLE_LIMIT)
    content["pin_title"] = pin_title

    # Limit hashtags
    hashtags = content.get("hashtags", [])
    if len(hashtags) > _PINTEREST_MAX_HASHTAGS:
        content["hashtags"] = hashtags[:_PINTEREST_MAX_HASHTAGS]


def _truncate_at_boundary(text: str, limit: int) -> str:
    """Truncate text at sentence/word boundary. Result guaranteed <= limit chars."""
    if len(text) <= limit:
        return text

    truncated = text[:limit]

    # Try sentence boundary (period) — no ellipsis needed
    dot_pos = truncated.rfind(".")
    if dot_pos > limit // 2:
        return truncated[: dot_pos + 1]

    # Try newline boundary — no ellipsis needed
    nl_pos = truncated.rfind("\n")
    if nl_pos > limit // 2:
        return truncated[:nl_pos]

    # Try word boundary (space) — with ellipsis, must fit in limit
    cut_limit = limit - 3  # Reserve space for "..."
    space_pos = text[:cut_limit].rfind(" ") if cut_limit > 0 else -1
    if space_pos > limit // 2:
        return text[:space_pos] + "..."

    # Hard cut with ellipsis
    return text[: max(cut_limit, 0)] + "..."
