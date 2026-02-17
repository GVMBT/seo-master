"""Article generation service — SEO articles for WordPress.

Source of truth: API_CONTRACTS.md section 5 (article_v7.yaml).
v7 changes: multi-step (outline→expand→critique), Markdown output, anti-slop, niche.
Pipeline: outline(DeepSeek) → expand(Claude) → quality_score → conditional critique → MD→HTML → nh3.
Zero Telegram/Aiogram dependencies.
"""

import json as _json
import random
import re
import statistics
from datetime import UTC, datetime
from typing import Any

import nh3
import structlog

from bot.exceptions import AIGenerationError, ContentValidationError
from db.client import SupabaseClient
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from services.ai.content_validator import ContentValidator
from services.ai.orchestrator import AIOrchestrator, GenerationRequest, GenerationResult

log = structlog.get_logger()

# --- JSON Schemas for structured outputs ---

ARTICLE_SCHEMA: dict[str, Any] = {
    "name": "article_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "meta_description": {"type": "string"},
            "content_markdown": {"type": "string"},
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
            "images_meta": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "alt": {"type": "string"},
                        "filename": {"type": "string"},
                        "figcaption": {"type": "string"},
                    },
                    "required": ["alt", "filename", "figcaption"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["title", "meta_description", "content_markdown", "faq_schema", "images_meta"],
        "additionalProperties": False,
    },
}

OUTLINE_SCHEMA: dict[str, Any] = {
    "name": "outline_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "h1": {"type": "string"},
            "sections": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "h2": {"type": "string"},
                        "h3_list": {"type": "array", "items": {"type": "string"}},
                        "key_points": {"type": "array", "items": {"type": "string"}},
                        "target_phrases": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["h2", "h3_list", "key_points", "target_phrases"],
                    "additionalProperties": False,
                },
            },
            "faq_questions": {"type": "array", "items": {"type": "string"}},
            "target_word_count": {"type": "integer"},
            "suggested_images": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["h1", "sections", "faq_questions", "target_word_count", "suggested_images"],
        "additionalProperties": False,
    },
}

CRITIQUE_SCHEMA: dict[str, Any] = {
    "name": "critique_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "meta_description": {"type": "string"},
            "content_markdown": {"type": "string"},
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
            "images_meta": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "alt": {"type": "string"},
                        "filename": {"type": "string"},
                        "figcaption": {"type": "string"},
                    },
                    "required": ["alt", "filename", "figcaption"],
                    "additionalProperties": False,
                },
            },
            "changes_summary": {"type": "string"},
        },
        "required": [
            "title",
            "meta_description",
            "content_markdown",
            "faq_schema",
            "images_meta",
            "changes_summary",
        ],
        "additionalProperties": False,
    },
}

# --- nh3 sanitization config ---

NH3_TAGS: set[str] = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "a",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "br",
    "hr",
    "span",
    "div",
    "blockquote",
    "img",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "figure",
    "figcaption",
    "nav",
}
NH3_ATTRS: dict[str, set[str]] = {
    "span": {"style"},
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "width", "height", "loading"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "h1": {"id"},
    "h2": {"id"},
    "h3": {"id"},
    "h4": {"id"},
    "li": {"class"},
    "nav": {"class"},
}

_JSONLD_RE = re.compile(
    r'<script\s+type=["\']application/ld\+json["\']\s*>.*?</script>',
    re.DOTALL | re.IGNORECASE,
)

# Quality score thresholds (API_CONTRACTS.md §5 step 8)
# >=80: pass, 60-79: critique, 40-59: warn (pass with log), <40: block
CRITIQUE_THRESHOLD = 80
CRITIQUE_MIN = 60
BLOCK_THRESHOLD = 40


def calculate_target_length(
    competitor_word_counts: list[int],
    text_settings: dict[str, Any],
) -> tuple[int, int]:
    """Calculate target article length from competitor analysis."""
    if not competitor_word_counts:
        return text_settings.get("words_min", 1500), text_settings.get("words_max", 2500)
    median_words = int(statistics.median(competitor_word_counts))
    target_min = max(1500, int(median_words * 1.1))
    target_max = min(5000, target_min + 500)
    return target_min, target_max


def _format_outline(outline: dict[str, Any]) -> str:
    """Format outline dict into readable text for article prompt."""
    lines = [f"# {outline.get('h1', '')}"]
    for section in outline.get("sections", []):
        lines.append(f"\n## {section.get('h2', '')}")
        for h3 in section.get("h3_list", []):
            lines.append(f"### {h3}")
        for point in section.get("key_points", []):
            lines.append(f"- {point}")
    faq = outline.get("faq_questions", [])
    if faq:
        lines.append("\n## FAQ")
        for q in faq:
            lines.append(f"- {q}")
    return "\n".join(lines)


def sanitize_html(raw_html: str) -> str:
    """Sanitize HTML with nh3, preserving JSON-LD blocks."""
    jsonld_blocks = _JSONLD_RE.findall(raw_html)
    stripped_html = _JSONLD_RE.sub("", raw_html)

    sanitized = nh3.clean(
        stripped_html,
        tags=NH3_TAGS,
        attributes=NH3_ATTRS,
        link_rel="noopener noreferrer",
    )

    if jsonld_blocks:
        safe_blocks: list[str] = []
        for block in jsonld_blocks:
            content_match = re.search(r">(.+?)</script>", block, re.DOTALL)
            if content_match:
                try:
                    _json.loads(content_match.group(1))
                    safe_blocks.append(block)
                except ValueError, _json.JSONDecodeError:
                    log.warning("invalid_jsonld_block_stripped")
        if safe_blocks:
            sanitized += "\n".join(safe_blocks)

    return sanitized


def _detect_niche_safe(specialization: str) -> str:
    """Detect niche with graceful fallback."""
    try:
        from services.ai.niche_detector import detect_niche

        return detect_niche(specialization)
    except ImportError:
        return "general"


def _extract_keyword_data(
    keyword: str,
    cluster: dict[str, Any] | None,
    category: Any,
) -> tuple[str, str, str, str, str]:
    """Extract main_phrase, secondary_phrases, volume, difficulty, cluster_volume."""
    main_phrase = keyword
    secondary_phrases = ""
    main_volume = "неизвестно"
    main_difficulty = "неизвестно"
    cluster_volume = "неизвестно"

    if cluster:
        main_phrase = cluster.get("main_phrase", keyword)
        phrases = cluster.get("phrases", [])
        secondary = [
            f"{p['phrase']} ({p.get('volume', '?')}/мес)"
            for p in phrases
            if p.get("phrase", "").lower() != main_phrase.lower()
        ]
        secondary_phrases = ", ".join(secondary)
        cluster_volume = str(cluster.get("total_volume", "неизвестно"))
        for p in phrases:
            if p.get("phrase", "").lower() == main_phrase.lower():
                main_volume = str(p.get("volume", "неизвестно"))
                main_difficulty = str(p.get("difficulty", "неизвестно"))
                break
    else:
        for kw in category.keywords or []:
            if kw.get("phrase", "").lower() == keyword.lower():
                main_volume = str(kw.get("volume", "неизвестно"))
                main_difficulty = str(kw.get("difficulty", "неизвестно"))
                break

    return main_phrase, secondary_phrases, main_volume, main_difficulty, cluster_volume


def _extract_serper_questions(serper_data: dict[str, Any] | None) -> str:
    """Extract random 3 PAA questions for anti-cannibalization."""
    if not serper_data:
        return ""
    paa = serper_data.get("people_also_ask", [])
    if not paa:
        return ""
    sample = random.sample(paa, min(3, len(paa)))
    questions = []
    for item in sample:
        if isinstance(item, dict):
            questions.append(item.get("question", ""))
        else:
            questions.append(str(item))
    return "\n".join(f"- {q}" for q in questions if q)


class ArticleService:
    """Generates SEO articles via multi-step pipeline (v7).

    Pipeline (API_CONTRACTS.md §5):
    1. Build context from project/category/competitor data
    2. OUTLINE: DeepSeek generates article plan
    3. EXPAND: Claude writes full article from outline (Markdown)
    4. Quality scoring (programmatic, no AI)
    5. CONDITIONAL CRITIQUE: if score < 80, DeepSeek critiques → Claude rewrites
    6. Markdown → HTML (mistune + SEORenderer)
    7. nh3 sanitization
    8. Content validation
    """

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
        cluster: dict[str, Any] | None = None,
        branding: dict[str, Any] | None = None,
        overrides: dict[str, Any] | None = None,
        serper_data: dict[str, Any] | None = None,
        competitor_pages: list[dict[str, Any]] | None = None,
        competitor_analysis: str = "",
        competitor_gaps: str = "",
        internal_links: str = "",
        lsi_keywords: str = "",
    ) -> GenerationResult:
        """Generate an SEO article via multi-step pipeline.

        Returns GenerationResult with content as dict:
        {title, meta_description, content_html, content_markdown, faq_schema, images_meta}
        """
        project = await self._projects.get_by_id(project_id)
        category = await self._categories.get_by_id(category_id)

        if project is None or category is None:
            raise AIGenerationError(message="Project or category not found")

        # Build context
        context, main_phrase, secondary_phrases, branding_dict = self._build_context(
            project,
            category,
            keyword,
            cluster=cluster,
            branding=branding,
            overrides=overrides,
            serper_data=serper_data,
            competitor_pages=competitor_pages,
            competitor_analysis=competitor_analysis,
            competitor_gaps=competitor_gaps,
            internal_links=internal_links,
            lsi_keywords=lsi_keywords,
        )

        # Step 1: OUTLINE → Step 2: EXPAND
        result, content_markdown = await self._generate_steps(user_id, context, keyword)

        # Step 3-5: Render → Score → Critique
        result, content_html = await self._quality_pipeline(
            user_id,
            result,
            content_markdown,
            context,
            main_phrase,
            secondary_phrases,
            branding_dict,
            keyword,
        )

        # Step 6: nh3 sanitization
        content_html = sanitize_html(content_html)

        # Store both markdown and html in result
        if isinstance(result.content, dict):
            result.content["content_html"] = content_html

        # Step 7: Content validation
        validation = self._validator.validate(content_html, "article", "wordpress")
        if not validation.is_valid:
            log.warning("article_validation_failed", errors=validation.errors, keyword=keyword)
            raise ContentValidationError(
                message=f"Article validation failed: {'; '.join(validation.errors)}",
                user_message="Сгенерированный контент не прошёл валидацию. Попробуйте ещё раз.",
            )

        return result

    def _build_context(
        self,
        project: Any,
        category: Any,
        keyword: str,
        *,
        cluster: dict[str, Any] | None,
        branding: dict[str, Any] | None,
        overrides: dict[str, Any] | None,
        serper_data: dict[str, Any] | None,
        competitor_pages: list[dict[str, Any]] | None,
        competitor_analysis: str,
        competitor_gaps: str,
        internal_links: str,
        lsi_keywords: str,
    ) -> tuple[dict[str, Any], str, str, dict[str, str]]:
        """Build prompt context from project/category/competitor data."""
        text_settings = overrides or category.text_settings or {}
        image_settings = category.image_settings or {}

        words_min, words_max = text_settings.get("words_min", 1500), text_settings.get("words_max", 2500)
        if competitor_pages:
            word_counts = [p.get("word_count", 0) for p in competitor_pages if p.get("word_count")]
            if word_counts:
                words_min, words_max = calculate_target_length(word_counts, text_settings)

        niche_type = _detect_niche_safe(project.specialization or "")
        main_phrase, secondary_phrases, main_volume, main_difficulty, cluster_volume = _extract_keyword_data(
            keyword, cluster, category
        )
        serper_questions = _extract_serper_questions(serper_data)

        text_color = "#333333"
        accent_color = "#0066cc"
        if branding:
            colors = branding.get("colors", {})
            text_color = colors.get("text", "#333333")
            accent_color = colors.get("accent", "#0066cc")

        context: dict[str, Any] = {
            "keyword": keyword,
            "main_phrase": main_phrase,
            "secondary_phrases": secondary_phrases,
            "main_volume": main_volume,
            "main_difficulty": main_difficulty,
            "cluster_volume": cluster_volume,
            "company_name": project.company_name,
            "specialization": project.specialization,
            "city": project.company_city or "",
            "advantages": project.advantages or "",
            "language": "ru",
            "words_min": words_min,
            "words_max": words_max,
            "text_style": text_settings.get("style", "Информативный"),
            "niche_type": niche_type,
            "current_date": datetime.now(tz=UTC).strftime("%B %Y"),
            "lsi_keywords": lsi_keywords,
            "internal_links": internal_links,
            "prices_excerpt": (category.prices or "")[:500],
            "serper_questions": serper_questions,
            "competitor_analysis": competitor_analysis,
            "competitor_gaps": competitor_gaps,
            "images_count": image_settings.get("count", 4),
            "text_color": text_color,
            "accent_color": accent_color,
        }
        branding_dict = {"text": text_color, "accent": accent_color}
        return context, main_phrase, secondary_phrases, branding_dict

    async def _generate_steps(
        self,
        user_id: int,
        context: dict[str, Any],
        keyword: str,
    ) -> tuple[GenerationResult, str]:
        """Steps 1-2: Generate outline then expand to full article."""
        outline_text = ""
        try:
            outline_result = await self._generate_outline(user_id, context)
            if isinstance(outline_result.content, dict):
                outline_text = _format_outline(outline_result.content)
                log.info("outline_generated", keyword=keyword)
        except Exception:
            log.warning("outline_skipped", keyword=keyword, exc_info=True)

        context["outline"] = outline_text
        result = await self._generate_article(user_id, context)

        content_markdown = ""
        if isinstance(result.content, dict):
            content_markdown = result.content.get("content_markdown", "")
        return result, content_markdown

    async def _quality_pipeline(
        self,
        user_id: int,
        result: GenerationResult,
        content_markdown: str,
        context: dict[str, Any],
        main_phrase: str,
        secondary_phrases: str,
        branding_dict: dict[str, str],
        keyword: str,
    ) -> tuple[GenerationResult, str]:
        """Steps 3-5: Render → Score → Conditional critique."""
        content_html = self._render_to_html(content_markdown, branding_dict, keyword)

        quality_score = None
        if content_html:
            quality_score = self._score_quality(content_html, main_phrase, secondary_phrases)

            if quality_score is not None and CRITIQUE_MIN <= quality_score.total < CRITIQUE_THRESHOLD:
                log.info("critique_triggered", score=quality_score.total, keyword=keyword)
                result, content_markdown, content_html, quality_score = await self._try_critique(
                    user_id,
                    result,
                    context,
                    content_markdown,
                    content_html,
                    quality_score,
                    branding_dict,
                    main_phrase,
                    secondary_phrases,
                    keyword,
                )

        if quality_score is not None and quality_score.total < BLOCK_THRESHOLD:
            raise ContentValidationError(
                message=f"Article quality too low ({quality_score.total}/100): {'; '.join(quality_score.issues[:3])}",
                user_message="Сгенерированный контент не прошёл проверку качества. Попробуйте ещё раз.",
            )

        # Anti-hallucination check (E48: warnings only, does NOT block publish)
        self._check_hallucinations(content_html, context)

        return result, content_html

    async def _try_critique(
        self,
        user_id: int,
        original_result: GenerationResult,
        context: dict[str, Any],
        content_markdown: str,
        content_html: str,
        quality_score: Any,
        branding_dict: dict[str, str],
        main_phrase: str,
        secondary_phrases: str,
        keyword: str,
    ) -> tuple[GenerationResult, str, str, Any]:
        """Attempt critique rewrite if quality is below threshold."""
        try:
            critique_result = await self._generate_critique(
                user_id,
                context,
                content_markdown,
                quality_score.issues,
            )
            if isinstance(critique_result.content, dict):
                new_md = critique_result.content.get("content_markdown", "")
                if new_md:
                    new_html = self._render_to_html(new_md, branding_dict, keyword)
                    new_score = self._score_quality(new_html, main_phrase, secondary_phrases)
                    if new_score is not None and new_score.total >= quality_score.total:
                        log.info("critique_improved", new_score=new_score.total)
                        return critique_result, new_md, new_html, new_score
                    log.warning("critique_did_not_improve", keyword=keyword)
        except Exception:
            log.warning("critique_failed", keyword=keyword, exc_info=True)
        return original_result, content_markdown, content_html, quality_score

    async def _generate_outline(
        self,
        user_id: int,
        context: dict[str, Any],
    ) -> GenerationResult:
        """Step 1: Generate article outline via DeepSeek (budget)."""
        request = GenerationRequest(
            task="article_outline",
            context=context,
            user_id=user_id,
            response_schema=OUTLINE_SCHEMA,
        )
        return await self._orchestrator.generate(request)

    async def _generate_article(
        self,
        user_id: int,
        context: dict[str, Any],
    ) -> GenerationResult:
        """Step 2: Expand outline into full article via Claude (premium)."""
        request = GenerationRequest(
            task="article",
            context=context,
            user_id=user_id,
            response_schema=ARTICLE_SCHEMA,
        )
        return await self._orchestrator.generate(request)

    async def _generate_critique(
        self,
        user_id: int,
        context: dict[str, Any],
        current_markdown: str,
        quality_issues: list[str],
    ) -> GenerationResult:
        """Step 4: Critique and rewrite via DeepSeek (budget)."""
        critique_context = {
            **context,
            "current_markdown": current_markdown,
            "quality_issues": "\n".join(f"- {issue}" for issue in quality_issues),
        }
        request = GenerationRequest(
            task="article_critique",
            context=critique_context,
            user_id=user_id,
            response_schema=CRITIQUE_SCHEMA,
        )
        return await self._orchestrator.generate(request)

    @staticmethod
    def _render_to_html(markdown_text: str, branding: dict[str, str], keyword: str) -> str:
        """Render markdown to HTML. Fallback to <pre> on error (E47)."""
        if not markdown_text:
            return ""
        try:
            from services.ai.markdown_renderer import render_markdown

            return render_markdown(
                markdown_text,
                branding=branding,
                insert_toc=True,
            )
        except ImportError:
            return f"<pre>{markdown_text}</pre>"
        except Exception:
            log.warning("markdown_parse_failed", keyword=keyword, exc_info=True)
            return f"<pre>{markdown_text}</pre>"

    @staticmethod
    def _check_hallucinations(content_html: str, context: dict[str, Any]) -> None:
        """Run anti-hallucination checks (E48: warnings only, does NOT block)."""
        try:
            from services.ai.anti_hallucination import check_fabricated_data

            issues = check_fabricated_data(
                html=content_html,
                prices_excerpt=context.get("prices_excerpt", ""),
                advantages=context.get("advantages", ""),
            )
            if issues:
                log.warning("hallucination_warnings", issues=issues, keyword=context.get("keyword"))
        except ImportError:
            pass
        except Exception:
            log.warning("hallucination_check_failed", exc_info=True)

    @staticmethod
    def _score_quality(
        content_html: str,
        main_phrase: str,
        secondary_phrases: str,
    ) -> Any:
        """Score article quality programmatically on rendered HTML. Returns QualityScore or None."""
        try:
            from services.ai.quality_scorer import ContentQualityScorer

            scorer = ContentQualityScorer()
            phrases_list = [p.strip().split(" (")[0] for p in secondary_phrases.split(",") if p.strip()]
            return scorer.score(content_html, main_phrase, phrases_list)
        except ImportError:
            log.warning("quality_scorer_not_available")
            return None
        except Exception:
            log.warning("quality_scoring_failed", exc_info=True)
            return None
