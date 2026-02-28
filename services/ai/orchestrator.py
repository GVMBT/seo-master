"""AI Orchestrator — OpenRouter client with MODEL_CHAINS, fallbacks, healing.

Source of truth: API_CONTRACTS.md section 3.1.
Uses AsyncOpenAI with base_url="https://openrouter.ai/api/v1".
"""

import asyncio
import contextlib
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import structlog
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from bot.exceptions import AIGenerationError
from services.ai.prompt_engine import PromptEngine
from services.ai.rate_limiter import RateLimiter

log = structlog.get_logger()

# Task type literal
TaskType = Literal[
    "article",
    "article_outline",
    "article_critique",
    "article_research",
    "social_post",
    "keywords",
    "seed_normalize",
    "review",
    "image",
    "description",
    "cross_post",
]

# Model chains (API_CONTRACTS.md §3.1)
MODEL_CHAINS: dict[str, list[str]] = {
    "article": [
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-5.2",
        "deepseek/deepseek-v3.2",
    ],
    "article_outline": [
        "deepseek/deepseek-v3.2",
        "openai/gpt-5.2",
    ],
    "article_critique": [
        "deepseek/deepseek-v3.2",
        "openai/gpt-5.2",
    ],
    "article_research": [
        "perplexity/sonar-pro",
    ],
    "social_post": [
        "deepseek/deepseek-v3.2",
        "anthropic/claude-sonnet-4.5",
    ],
    "keywords": [
        "deepseek/deepseek-v3.2",
        "openai/gpt-5.2",
    ],
    "seed_normalize": [
        "deepseek/deepseek-v3.2",
        "openai/gpt-5.2",
    ],
    "review": [
        "deepseek/deepseek-v3.2",
        "anthropic/claude-sonnet-4.5",
    ],
    "description": [
        "deepseek/deepseek-v3.2",
        "anthropic/claude-sonnet-4.5",
    ],
    "cross_post": [
        "deepseek/deepseek-v3.2",
        "openai/gpt-5.2",
    ],
    "image": [
        "google/gemini-3-pro-image-preview",
        "google/gemini-3.1-flash-image-preview",
    ],
}

# Tasks that use budget provider routing (sort: price)
BUDGET_TASKS: set[str] = {
    "social_post",
    "keywords",
    "seed_normalize",
    "review",
    "description",
    "cross_post",
    "article_outline",
    "article_critique",
    "article_research",
}

# JSON schema responses (API_CONTRACTS.md structured outputs table)
STRUCTURED_TASKS: set[str] = {
    "article",
    "article_outline",
    "article_critique",
    "article_research",
    "social_post",
    "cross_post",
    "keywords",
    "seed_normalize",
    "review",
}

# Tasks that use response-healing plugin
HEALING_TASKS: set[str] = {
    "article",
    "article_outline",
    "article_critique",
    "article_research",
    "social_post",
    "keywords",
    "review",
}

# Budget model for heal_response fallback
HEAL_MODEL = "deepseek/deepseek-v3.2"


@dataclass
class ClusterContext:
    """Cluster-aware fields for article_v7 / keywords_cluster_v3."""

    main_phrase: str
    secondary_phrases: str = ""
    cluster_volume: int = 0
    main_volume: int = 0
    main_difficulty: int = 0
    cluster_type: str = "article"


@dataclass
class CompetitorContext:
    """Competitor analysis fields from Firecrawl /scrape (Phase 10)."""

    competitor_analysis: str = ""
    competitor_gaps: str = ""


@dataclass
class GenerationContext:
    """Typed context for AI generation (API_CONTRACTS.md §3.1).

    to_dict() skips None values entirely — PromptEngine uses Jinja2 <<var>>
    which renders None as the string "None" in the prompt. YAML variables
    have default: values that PromptEngine uses when a key is missing.
    """

    company_name: str
    specialization: str
    keyword: str
    language: str = "ru"
    category_name: str = ""
    cluster: ClusterContext | None = None
    competitor: CompetitorContext | None = None
    words_min: int | None = None
    words_max: int | None = None
    images_count: int | None = None
    city: str | None = None
    advantages: str | None = None
    prices_excerpt: str | None = None
    serper_questions: str | None = None
    lsi_keywords: str | None = None
    internal_links: str | None = None
    text_color: str | None = None
    accent_color: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Flatten to dict for PromptEngine, skipping None values."""
        result: dict[str, Any] = {}

        # Always-present scalar fields
        result["company_name"] = self.company_name
        result["specialization"] = self.specialization
        result["keyword"] = self.keyword
        result["language"] = self.language
        if self.category_name:
            result["category_name"] = self.category_name

        # Cluster fields — flatten when present
        if self.cluster is not None:
            result["main_phrase"] = self.cluster.main_phrase
            result["secondary_phrases"] = self.cluster.secondary_phrases
            result["cluster_volume"] = str(self.cluster.cluster_volume)
            result["main_volume"] = str(self.cluster.main_volume)
            result["main_difficulty"] = str(self.cluster.main_difficulty)
            result["cluster_type"] = self.cluster.cluster_type

        # Competitor fields — flatten when present
        if self.competitor is not None:
            result["competitor_analysis"] = self.competitor.competitor_analysis
            result["competitor_gaps"] = self.competitor.competitor_gaps

        # Optional scalar fields — skip if None
        for field_name in (
            "words_min",
            "words_max",
            "images_count",
            "city",
            "advantages",
            "prices_excerpt",
            "serper_questions",
            "lsi_keywords",
            "internal_links",
            "text_color",
            "accent_color",
        ):
            value = getattr(self, field_name)
            if value is not None:
                result[field_name] = str(value) if isinstance(value, int) else value

        return result


@dataclass
class GenerationRequest:
    """Request to generate AI content."""

    task: TaskType
    context: dict[str, Any]
    user_id: int
    max_retries: int = 2
    stream: bool = False
    response_schema: dict[str, Any] | None = None


@dataclass
class GenerationResult:
    """Result from AI generation."""

    content: str | dict[str, Any]
    model_used: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    generation_time_ms: int
    prompt_version: str
    fallback_used: bool


# Rate limit action mapping
_RATE_ACTION: dict[str, str] = {
    "article": "text_generation",
    "social_post": "text_generation",
    "keywords": "keyword_generation",
    "seed_normalize": "keyword_generation",
    "review": "text_generation",
    "description": "text_generation",
    "image": "image_generation",
}


class AIOrchestrator:
    """Central AI generation client using OpenRouter via AsyncOpenAI."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str,
        prompt_engine: PromptEngine,
        rate_limiter: RateLimiter,
        site_url: str = "",
    ) -> None:
        self._client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key,
            http_client=http_client,
            default_headers={"HTTP-Referer": site_url} if site_url else {},
        )
        self._prompt_engine = prompt_engine
        self._rate_limiter = rate_limiter
        self._semaphore = asyncio.Semaphore(10)  # Backpressure (ARCHITECTURE.md §5.6)
        self._site_url = site_url

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate content via OpenRouter with rate limiting and fallbacks."""
        # 1. Rate limit check
        action = _RATE_ACTION.get(request.task, "text_generation")
        await self._rate_limiter.check(request.user_id, action)

        # 2. Acquire semaphore (backpressure for autopublish storm)
        async with self._semaphore:
            return await self._do_generate(request)

    async def generate_without_rate_limit(self, request: GenerationRequest) -> GenerationResult:
        """Generate content bypassing per-request rate limiting.

        Used by ImageService which does batch rate limit checks before
        launching parallel generation tasks. The semaphore (backpressure)
        is still applied.
        """
        async with self._semaphore:
            return await self._do_generate(request)

    async def generate_stream(self, request: GenerationRequest) -> None:
        """Stream generation — deferred to Phase 7+."""
        raise NotImplementedError("Streaming deferred to Phase 7+")

    async def _do_generate(self, request: GenerationRequest) -> GenerationResult:
        """Internal generation with prompt rendering, API call, and retry (C12)."""
        # Render prompt
        rendered = await self._prompt_engine.render(request.task, request.context)

        # Build messages
        messages = self._build_messages(rendered.system, rendered.user, request.task)

        # Build extra_body for OpenRouter
        chain = MODEL_CHAINS.get(request.task, [])
        extra_body: dict[str, Any] = {
            # Fallback models only — primary is in `model` param.
            # OpenRouter docs: "model" = primary, "models" = fallbacks tried in order.
            "models": chain[1:],
            "provider": {
                "data_collection": "deny",
                "allow_fallbacks": True,
            },
        }

        # Budget tasks use price sorting (no max_price — it blocks endpoints
        # when combined with require_parameters + json_schema)
        if request.task in BUDGET_TASKS:
            extra_body["provider"]["sort"] = "price"
        else:
            # Non-budget tasks (article, image) need
            # strict parameter matching for quality
            extra_body["provider"]["require_parameters"] = True

        # Response healing plugin for structured tasks
        if request.task in HEALING_TASKS:
            extra_body["plugins"] = [{"id": "response-healing"}]

        self._apply_task_specific_params(request.task, extra_body, request.context)

        # Response format for structured tasks
        kwargs: dict[str, Any] = {}
        if request.response_schema and request.task in STRUCTURED_TASKS:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": request.response_schema,
            }

        # Call OpenRouter with retry (C12: use request.max_retries)
        start_time = time.monotonic()
        response = await self._call_with_retry(
            request=request,
            chain=chain,
            messages=messages,
            rendered=rendered,
            extra_body=extra_body,
            kwargs=kwargs,
        )

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        # Extract response
        if not response.choices:
            raise AIGenerationError(
                message="OpenRouter returned empty choices (content may have been filtered)",
            )
        choice = response.choices[0]
        self._check_finish_reason(choice, request.task, rendered.meta)
        raw_content = choice.message.content or ""

        # For image tasks, extract data URI from message.images
        if request.task == "image":
            raw_content = self._extract_image_content(choice.message, raw_content)

        model_used = response.model or chain[0]
        usage = response.usage

        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        cost_usd = 0.0

        # Parse cost from OpenRouter response ID (async lookup if needed).
        # AsyncOpenAI SDK doesn't expose X-OpenRouter-Cost header directly.
        # Cost tracked via token_expenses table (operation_type=api_openrouter)
        # with actual cost looked up via /api/v1/generation?id= in Phase 9.
        generation_id = getattr(response, "id", "")
        if generation_id:
            log.debug("generation_id_for_cost_lookup", generation_id=generation_id)

        # Parse structured content
        content: str | dict[str, Any] = raw_content
        if request.task in STRUCTURED_TASKS and request.task != "image":
            parsed = self._try_parse_json(raw_content)
            if isinstance(parsed, dict):
                content = parsed
            elif isinstance(parsed, list):
                content = {"items": parsed}
            else:
                # Try healing
                healed = await self.heal_response(raw_content, "json")
                if isinstance(healed, dict):
                    content = healed
                elif healed is not None:
                    content = str(healed)
                else:
                    raise AIGenerationError(
                        message="Failed to parse AI response as JSON after healing",
                    )

        # OpenRouter may return model with variant suffix (e.g. ":beta")
        fallback_used = not model_used.startswith(chain[0]) if chain else False

        log.info(
            "generation_complete",
            task=request.task,
            model=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            elapsed_ms=elapsed_ms,
            fallback_used=fallback_used,
        )

        return GenerationResult(
            content=content,
            model_used=model_used,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            generation_time_ms=elapsed_ms,
            prompt_version=rendered.version,
            fallback_used=fallback_used,
        )

    async def _call_with_retry(
        self,
        *,
        request: GenerationRequest,
        chain: list[str],
        messages: list[dict[str, Any]],
        rendered: Any,
        extra_body: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> Any:
        """Call OpenRouter API with retry on transient errors (C12).

        Retries on: network errors, 429, 5xx.
        No retry on: 401, 403, other 4xx.
        Respects Retry-After header (cap 60s).
        """
        max_retries = request.max_retries
        base_delay = 1.0
        max_retry_after = 60.0
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return await self._client.chat.completions.create(
                    model=chain[0] if chain else "deepseek/deepseek-v3.2",
                    messages=messages,  # type: ignore[arg-type]
                    max_tokens=rendered.meta.get("max_tokens", 4000),
                    temperature=rendered.meta.get(
                        "temperature",
                        0.6 if rendered.meta.get("task") == "article" else 0.7,
                    ),
                    extra_body=extra_body,
                    timeout=rendered.meta.get("timeout", 120),
                    **kwargs,
                )
            except (APITimeoutError, APIConnectionError) as exc:
                # Network errors — always retryable
                last_exc = exc
                if attempt >= max_retries:
                    log.error("openrouter_api_error", task=request.task, error=str(exc))
                    raise AIGenerationError(
                        message=f"OpenRouter API error: {exc}",
                    ) from exc
                delay = min(base_delay * (2**attempt), max_retry_after)
                log.warning(
                    "http_retry",
                    operation="openrouter_generate",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    status=None,
                    delay_s=round(delay, 2),
                    error=str(exc)[:200],
                )
                await asyncio.sleep(delay)
            except APIStatusError as exc:
                last_exc = exc
                status = exc.status_code

                # Auth errors — never retry
                if status in (401, 403):
                    log.error("openrouter_api_error", task=request.task, error=str(exc))
                    raise AIGenerationError(
                        message=f"OpenRouter API error: {exc}",
                    ) from exc

                # Retryable status codes: 429, 5xx
                if status not in (429, 500, 502, 503, 504):
                    log.error("openrouter_api_error", task=request.task, error=str(exc))
                    raise AIGenerationError(
                        message=f"OpenRouter API error: {exc}",
                    ) from exc

                if attempt >= max_retries:
                    log.error("openrouter_api_error", task=request.task, error=str(exc))
                    raise AIGenerationError(
                        message=f"OpenRouter API error: {exc}",
                    ) from exc

                # Calculate delay: Retry-After for 429, backoff for 5xx
                delay = base_delay * (2**attempt)
                if status == 429:
                    retry_after_raw = exc.response.headers.get("Retry-After")
                    if retry_after_raw:
                        with contextlib.suppress(ValueError, TypeError):
                            delay = max(float(retry_after_raw), 0.0)
                delay = min(delay, max_retry_after)

                log.warning(
                    "http_retry",
                    operation="openrouter_generate",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    status=status,
                    delay_s=round(delay, 2),
                    error=str(exc)[:200],
                )
                await asyncio.sleep(delay)
            except Exception as exc:
                # Non-HTTP exceptions (e.g. parsing) — do not retry
                log.error("openrouter_api_error", task=request.task, error=str(exc))
                raise AIGenerationError(
                    message=f"OpenRouter API error: {exc}",
                ) from exc

        # Should not reach here but satisfy type checker
        if last_exc is not None:
            raise AIGenerationError(
                message=f"OpenRouter API error: {last_exc}",
            ) from last_exc
        raise AIGenerationError(message="Unexpected retry state")  # pragma: no cover

    @staticmethod
    def _apply_task_specific_params(
        task: str,
        extra_body: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """Apply task-specific parameters to extra_body."""
        if task == "image":
            extra_body["modalities"] = ["image", "text"]
            image_settings = context.get("image_settings", {})
            aspect_ratio = "1:1"
            formats = image_settings.get("formats", [])
            if formats:
                aspect_ratio = formats[0]
            quality = image_settings.get("quality", "HD")
            size_map = {"HD": "1K", "Ultra HD": "2K", "8K": "4K"}
            extra_body["image_config"] = {
                "aspect_ratio": aspect_ratio,
                "image_size": size_map.get(quality, "1K"),
            }
        elif task == "article_research":
            extra_body["search_context_size"] = "high"

    @staticmethod
    def _check_finish_reason(choice: Any, task: str, meta: dict[str, Any]) -> None:
        """Raise if response was truncated (finish_reason=length)."""
        finish_reason = getattr(choice, "finish_reason", None) or ""
        if finish_reason == "length":
            log.warning(
                "generation_truncated",
                task=task,
                max_tokens=meta.get("max_tokens"),
            )
            raise AIGenerationError(
                message=f"AI response truncated (max_tokens exceeded) for task={task}",
                user_message="Генерация обрезана из-за лимита. Попробуйте ещё раз.",
            )

    @staticmethod
    def _extract_image_content(message: Any, fallback: str) -> str:
        """Extract image data URI from OpenRouter message.images field.

        OpenRouter returns generated images in message.images (not content):
        [{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]
        OpenAI SDK stores this in model_extra since it's not a standard field.
        """
        images_data = getattr(message, "images", None)
        if not images_data or not isinstance(images_data, list):
            return fallback

        for img in images_data:
            if isinstance(img, dict):
                url: str = str(img.get("image_url", {}).get("url", ""))
                if url.startswith("data:image/"):
                    return url

        log.warning(
            "image_response_no_data_uri",
            images_count=len(images_data),
            first_type=type(images_data[0]).__name__ if images_data else "empty",
        )
        return fallback

    def _build_messages(
        self,
        system: str,
        user: str,
        task: str,
    ) -> list[dict[str, Any]]:
        """Build chat messages with Anthropic prompt caching for Claude models."""
        chain = MODEL_CHAINS.get(task, [])
        is_anthropic = "anthropic" in chain[0] if chain else False

        if is_anthropic and system:
            # Use cache_control for Anthropic models (API_CONTRACTS.md §3.1)
            system_msg: dict[str, Any] = {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        elif system:
            system_msg = {"role": "system", "content": system}
        else:
            system_msg = {}

        messages: list[dict[str, Any]] = []
        if system_msg:
            messages.append(system_msg)
        messages.append({"role": "user", "content": user})
        return messages

    async def heal_response(
        self,
        raw: str,
        expected_format: str,
    ) -> dict[str, Any] | str | None:
        """Attempt to fix broken JSON responses (API_CONTRACTS.md §3.1).

        Pipeline:
        1. json.loads(raw) — if OK, return
        2. Regex fixes: strip markdown, trailing commas, close brackets
        3. json.loads() again
        4. Send to budget model for repair
        5. All fail → return None (caller handles refund)
        """
        if expected_format != "json":
            return raw

        # Step 1: direct parse
        parsed = self._try_parse_json(raw)
        if parsed is not None:
            return parsed if isinstance(parsed, dict) else {"items": parsed}

        # Step 2: regex fixes
        fixed = self._regex_fix_json(raw)
        parsed = self._try_parse_json(fixed)
        if parsed is not None:
            return parsed if isinstance(parsed, dict) else {"items": parsed}

        # Step 3: budget model repair
        try:
            repair_response = await self._client.chat.completions.create(
                model=HEAL_MODEL,
                messages=[  # type: ignore[arg-type]
                    {
                        "role": "system",
                        "content": "Fix the following broken JSON. Return ONLY valid JSON, nothing else.",
                    },
                    {"role": "user", "content": raw[:2000]},
                ],
                max_tokens=2000,
                temperature=0.0,
                timeout=30,
            )
            repaired = repair_response.choices[0].message.content or ""
            parsed = self._try_parse_json(repaired)
            if parsed is not None:
                log.info("response_healed_by_model")
                return parsed if isinstance(parsed, dict) else {"items": parsed}
        except Exception:
            log.warning("heal_model_failed", exc_info=True)

        log.error("response_healing_failed", raw_preview=raw[:200])
        return None

    @staticmethod
    def _try_parse_json(text: str) -> dict[str, Any] | list[Any] | None:
        """Try to parse text as JSON. Returns None on failure."""
        try:
            result = json.loads(text)
            if isinstance(result, (dict, list)):
                return result
        except (json.JSONDecodeError, TypeError):  # fmt: skip
            pass
        return None

    @staticmethod
    def _regex_fix_json(text: str) -> str:
        """Apply common regex fixes to broken JSON."""
        # Strip markdown code fences
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
        text = text.strip()

        # Remove trailing commas before } or ]
        text = re.sub(r",\s*([}\]])", r"\1", text)

        # Close unclosed brackets/braces
        opens = text.count("{") - text.count("}")
        if opens > 0:
            text += "}" * opens
        opens = text.count("[") - text.count("]")
        if opens > 0:
            text += "]" * opens

        return text
