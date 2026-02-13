"""Article generation service — SEO articles for WordPress.

Source of truth: API_CONTRACTS.md section 5 (article_v5.yaml).
Zero Telegram/Aiogram dependencies.
"""

import re
from typing import Any

import nh3
import structlog

from bot.exceptions import ContentValidationError
from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.content_validator import ContentValidator
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult

log = structlog.get_logger()

# JSON Schema for structured output (API_CONTRACTS.md §3.1)
ARTICLE_SCHEMA: dict[str, Any] = {
    "name": "article_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "meta_description": {"type": "string"},
            "content_html": {"type": "string"},
            "faq_schema": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "answer": {"type": "string"},
                    },
                    "required": ["question", "answer"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "meta_description", "content_html", "faq_schema"],
        "additionalProperties": False,
    },
}

# Allowed HTML tags for nh3 sanitization (ARCHITECTURE.md §5.8)
NH3_TAGS: set[str] = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "a", "b", "strong", "i", "em", "u", "s",
    "ul", "ol", "li", "br", "hr", "span", "div", "blockquote", "img",
    "table", "thead", "tbody", "tr", "th", "td",
    "figure", "figcaption",
    # NOTE: <script> is NOT allowed in NH3_TAGS because nh3 treats it as a
    # "clean_content_tag" (strips tag AND content). Schema.org JSON-LD
    # <script type="application/ld+json"> blocks are preserved separately
    # via _preserve_jsonld / _restore_jsonld before/after nh3.clean().
}
NH3_ATTRS: dict[str, set[str]] = {
    "span": {"style"},
    "a": {"href", "title", "target"},  # rel is managed by link_rel param
    "img": {"src", "alt", "width", "height", "loading"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

# Regex to match Schema.org JSON-LD script blocks
_JSONLD_RE = re.compile(
    r'<script\s+type=["\']application/ld\+json["\']\s*>.*?</script>',
    re.DOTALL | re.IGNORECASE,
)


class ArticleService:
    """Generates SEO articles. No streaming in Phase 6."""

    def __init__(self, orchestrator: AIOrchestrator, db: SupabaseClient) -> None:
        self._orchestrator = orchestrator
        self._db = db
        self._projects = ProjectsRepository(db)
        self._categories = CategoriesRepository(db)
        self._validator = ContentValidator()

    async def generate(
        self,
        user_id: int,
        project_id: int,
        category_id: int,
        keyword: str,
        *,
        branding: dict[str, Any] | None = None,
        overrides: dict[str, Any] | None = None,
        serper_data: dict[str, Any] | None = None,
    ) -> GenerationResult:
        """Generate an SEO article.

        Returns GenerationResult with content as dict:
        {title, meta_description, content_html, faq_schema}
        """
        project = await self._projects.get_by_id(project_id)
        category = await self._categories.get_by_id(category_id)

        if project is None or category is None:
            from bot.exceptions import AIGenerationError
            raise AIGenerationError(message="Project or category not found")

        # Build context from project/category data
        text_settings = overrides or category.text_settings or {}
        context: dict[str, Any] = {
            "keyword": keyword,
            "company_name": project.company_name,
            "specialization": project.specialization,
            "city": project.company_city or "",
            "advantages": project.advantages or "",
            "language": "ru",
            "words_min": text_settings.get("words_min", 1500),
            "words_max": text_settings.get("words_max", 2500),
            "lsi_keywords": "",
            "internal_links": "",
            "prices_excerpt": (category.prices or "")[:500],
            "serper_questions": "",
            "competitor_summary": "",
            "text_color": "#333333",
            "accent_color": "#0066cc",
            "volume": "неизвестно",
            "difficulty": "неизвестно",
        }

        # Enrich with branding colors
        if branding:
            colors = branding.get("colors", {})
            context["text_color"] = colors.get("text", "#333333")
            context["accent_color"] = colors.get("accent", "#0066cc")

        # Enrich with serper data
        if serper_data:
            paa = serper_data.get("people_also_ask", [])
            if paa:
                context["serper_questions"] = "\n".join(f"- {q}" for q in paa[:5])

        # Keyword volume/difficulty from category keywords
        for kw in category.keywords:
            if kw.get("phrase", "").lower() == keyword.lower():
                context["volume"] = str(kw.get("volume", "неизвестно"))
                context["difficulty"] = str(kw.get("difficulty", "неизвестно"))
                break

        request = GenerationRequest(
            task="article",
            context=context,
            user_id=user_id,
            response_schema=ARTICLE_SCHEMA,
        )

        result = await self._orchestrator.generate(request)

        # Sanitize HTML content with nh3
        # Schema.org JSON-LD <script> blocks are preserved through sanitization (H12)
        if isinstance(result.content, dict) and "content_html" in result.content:
            raw_html = result.content["content_html"]
            jsonld_blocks = _JSONLD_RE.findall(raw_html)
            stripped_html = _JSONLD_RE.sub("", raw_html)
            sanitized = nh3.clean(
                stripped_html,
                tags=NH3_TAGS,
                attributes=NH3_ATTRS,
                link_rel="noopener noreferrer",
            )
            if jsonld_blocks:
                sanitized += "\n".join(jsonld_blocks)
            result.content["content_html"] = sanitized

        # Validate — block on invalid content (H10)
        content_text = ""
        if isinstance(result.content, dict):
            content_text = result.content.get("content_html", "")
        validation = self._validator.validate(content_text, "article", "wordpress")
        if not validation.is_valid:
            log.warning(
                "article_validation_failed",
                errors=validation.errors,
                keyword=keyword,
            )
            raise ContentValidationError(
                message=f"Article validation failed: {'; '.join(validation.errors)}",
                user_message="Сгенерированный контент не прошёл валидацию. Попробуйте ещё раз.",
            )

        return result
