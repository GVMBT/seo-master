"""Tests for services/ai/orchestrator.py — AIOrchestrator.

Covers: generate() happy path, rate limit, API error, fallback model,
heal_response() pipeline, _regex_fix_json(), _try_parse_json().
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from bot.exceptions import AIGenerationError, RateLimitError
from services.ai.orchestrator import (
    MODEL_CHAINS,
    AIOrchestrator,
    ClusterContext,
    GenerationContext,
    GenerationRequest,
    GenerationResult,
)
from services.ai.prompt_engine import RenderedPrompt

# ---------------------------------------------------------------------------
# Helpers — mock OpenAI response objects
# ---------------------------------------------------------------------------


def _make_usage(prompt_tokens: int = 500, completion_tokens: int = 200) -> MagicMock:
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    return usage


def _make_openai_response(
    content: str = '{"title": "Test"}',
    model: str = "deepseek/deepseek-v3.2",
    prompt_tokens: int = 500,
    completion_tokens: int = 200,
) -> MagicMock:
    """Build a mock ChatCompletion response matching OpenAI SDK shape."""
    message = MagicMock()
    message.content = content

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    response.model = model
    response.usage = _make_usage(prompt_tokens, completion_tokens)

    # By default no x_openrouter attribute
    del response.x_openrouter

    return response


def _make_rendered_prompt(
    system: str = "sys",
    user: str = "usr",
    max_tokens: int = 4000,
    temperature: float = 0.7,
    version: str = "v5",
) -> RenderedPrompt:
    return RenderedPrompt(
        system=system,
        user=user,
        meta={"max_tokens": max_tokens, "temperature": temperature},
        version=version,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_prompt_engine() -> AsyncMock:
    engine = AsyncMock()
    engine.render.return_value = _make_rendered_prompt()
    return engine


@pytest.fixture
def mock_rate_limiter() -> AsyncMock:
    limiter = AsyncMock()
    limiter.check.return_value = None
    return limiter


@pytest.fixture
def mock_http_client() -> MagicMock:
    return MagicMock(spec=httpx.AsyncClient)


@pytest.fixture
def mock_openai_client() -> AsyncMock:
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(
        return_value=_make_openai_response(),
    )
    return client


@pytest.fixture
def orchestrator(
    mock_http_client: MagicMock,
    mock_prompt_engine: AsyncMock,
    mock_rate_limiter: AsyncMock,
    mock_openai_client: AsyncMock,
) -> AIOrchestrator:
    """Create AIOrchestrator with mocked AsyncOpenAI client."""
    with patch("services.ai.orchestrator.AsyncOpenAI", return_value=mock_openai_client):
        orch = AIOrchestrator(
            http_client=mock_http_client,
            api_key="test-key",
            prompt_engine=mock_prompt_engine,
            rate_limiter=mock_rate_limiter,
            site_url="https://example.com",
        )
    return orch


# ---------------------------------------------------------------------------
# generate() — success
# ---------------------------------------------------------------------------


class TestGenerateSuccess:
    async def test_generate_article_returns_parsed_dict(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
        mock_rate_limiter: AsyncMock,
    ) -> None:
        """generate() with a structured task returns GenerationResult with parsed content."""
        article_json = json.dumps({"title": "SEO Guide", "body": "Content here"})
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content=article_json,
            model="anthropic/claude-sonnet-4.5",
        )

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )
        result = await orchestrator.generate(request)

        assert isinstance(result, GenerationResult)
        assert result.content == {"title": "SEO Guide", "body": "Content here"}
        assert result.model_used == "anthropic/claude-sonnet-4.5"
        assert result.prompt_version == "v5"
        assert result.fallback_used is False
        assert result.input_tokens == 500
        assert result.output_tokens == 200
        assert result.generation_time_ms >= 0
        mock_rate_limiter.check.assert_awaited_once_with(123, "text_generation")

    async def test_generate_description_returns_raw_string(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """Description task is NOT in STRUCTURED_TASKS, content stays as string."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content="A compelling meta description.",
            model="deepseek/deepseek-v3.2",
        )

        request = GenerationRequest(
            task="description",
            context={"topic": "SEO"},
            user_id=123,
        )
        result = await orchestrator.generate(request)

        assert isinstance(result.content, str)
        assert result.content == "A compelling meta description."

    async def test_generate_keywords_list_wrapped_in_items(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """When AI returns a JSON list for keywords, it is wrapped as {items: [...]}."""
        kw_list = json.dumps(["seo", "marketing", "content"])
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content=kw_list,
            model="deepseek/deepseek-v3.2",
        )

        request = GenerationRequest(
            task="keywords",
            context={"topic": "SEO"},
            user_id=123,
        )
        result = await orchestrator.generate(request)

        assert result.content == {"items": ["seo", "marketing", "content"]}

    async def test_generate_passes_response_schema_for_structured_task(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """response_schema is forwarded as response_format for structured tasks."""
        schema = {"name": "article", "schema": {"type": "object"}}
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"title": "T"}',
            model="anthropic/claude-sonnet-4.5",
        )

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
            response_schema=schema,
        )
        await orchestrator.generate(request)

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        assert call_kwargs.kwargs["response_format"] == {
            "type": "json_schema",
            "json_schema": schema,
        }


# ---------------------------------------------------------------------------
# generate() — rate limit exceeded
# ---------------------------------------------------------------------------


class TestGenerateRateLimit:
    async def test_generate_rate_limit_exceeded_raises_error(
        self,
        orchestrator: AIOrchestrator,
        mock_rate_limiter: AsyncMock,
    ) -> None:
        """Rate limiter raises RateLimitError before API call."""
        mock_rate_limiter.check.side_effect = RateLimitError(
            message="Rate limit exceeded for text_generation: 11/10",
        )

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )

        with pytest.raises(RateLimitError, match="Rate limit exceeded"):
            await orchestrator.generate(request)


# ---------------------------------------------------------------------------
# generate() — API error
# ---------------------------------------------------------------------------


class TestGenerateAPIError:
    async def test_generate_api_error_raises_ai_generation_error(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """OpenRouter API exception is wrapped in AIGenerationError."""
        mock_openai_client.chat.completions.create.side_effect = Exception("Connection timeout")

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )

        with pytest.raises(AIGenerationError, match="OpenRouter API error"):
            await orchestrator.generate(request)


# ---------------------------------------------------------------------------
# generate() — fallback model used
# ---------------------------------------------------------------------------


class TestGenerateFallback:
    async def test_generate_fallback_model_sets_flag(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """When OpenRouter uses a fallback model, fallback_used=True."""
        # Article chain: claude-sonnet-4.5 is primary, gpt-5.2 is fallback
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"title": "Fallback"}',
            model="openai/gpt-5.2",  # Not the first in chain
        )

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )
        result = await orchestrator.generate(request)

        assert result.fallback_used is True
        assert result.model_used == "openai/gpt-5.2"

    async def test_generate_primary_model_no_fallback(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """When primary model responds, fallback_used=False."""
        primary_model = MODEL_CHAINS["article"][0]
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"title": "Primary"}',
            model=primary_model,
        )

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )
        result = await orchestrator.generate(request)

        assert result.fallback_used is False
        assert result.model_used == primary_model


# ---------------------------------------------------------------------------
# generate() — structured parse failure triggers healing
# ---------------------------------------------------------------------------


class TestGenerateStructuredHealing:
    async def test_generate_structured_invalid_json_healed(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """If initial JSON parse fails, heal_response repairs it."""
        # First call: article generation with broken JSON
        broken_json = '{"title": "Test", "body": "content"'  # missing closing brace
        # Second call: heal model returns valid JSON
        healed_json = '{"title": "Test", "body": "content"}'

        mock_openai_client.chat.completions.create.side_effect = [
            _make_openai_response(content=broken_json, model="anthropic/claude-sonnet-4.5"),
            _make_openai_response(content=healed_json, model="deepseek/deepseek-v3.2"),
        ]

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )
        result = await orchestrator.generate(request)

        # Regex fix closes the brace, so content should be parsed
        assert isinstance(result.content, dict)
        assert result.content["title"] == "Test"

    async def test_generate_structured_all_healing_fails_raises_error(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """If all healing attempts fail, AIGenerationError is raised."""
        not_json = "This is not JSON at all, just plain text without any braces"
        # Heal model also returns non-JSON
        still_not_json = "Sorry, I cannot fix this"

        mock_openai_client.chat.completions.create.side_effect = [
            _make_openai_response(content=not_json, model="anthropic/claude-sonnet-4.5"),
            _make_openai_response(content=still_not_json, model="deepseek/deepseek-v3.2"),
        ]

        request = GenerationRequest(
            task="article",
            context={"topic": "SEO"},
            user_id=123,
        )

        with pytest.raises(AIGenerationError, match="Failed to parse"):
            await orchestrator.generate(request)


# ---------------------------------------------------------------------------
# heal_response() — valid JSON
# ---------------------------------------------------------------------------


class TestHealResponseValidJSON:
    async def test_heal_response_valid_json_returns_dict(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Direct JSON parse succeeds, no fixing needed."""
        raw = '{"title": "Article", "body": "Text"}'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"title": "Article", "body": "Text"}

    async def test_heal_response_valid_json_list_wrapped(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """JSON list is wrapped in {items: [...]}."""
        raw = '["keyword1", "keyword2"]'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"items": ["keyword1", "keyword2"]}


# ---------------------------------------------------------------------------
# heal_response() — markdown-wrapped JSON
# ---------------------------------------------------------------------------


class TestHealResponseMarkdownWrapped:
    async def test_heal_response_markdown_code_fence_stripped(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Markdown ```json ... ``` wrapping is stripped by regex fix."""
        raw = '```json\n{"title": "Test"}\n```'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"title": "Test"}

    async def test_heal_response_plain_code_fence_stripped(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Plain ``` ... ``` wrapping (without json label) is stripped."""
        raw = '```\n{"key": "value"}\n```'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"key": "value"}


# ---------------------------------------------------------------------------
# heal_response() — trailing commas
# ---------------------------------------------------------------------------


class TestHealResponseTrailingCommas:
    async def test_heal_response_trailing_comma_before_brace(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Trailing comma before } is removed."""
        raw = '{"a": 1, "b": 2,}'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"a": 1, "b": 2}

    async def test_heal_response_trailing_comma_before_bracket(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Trailing comma before ] is removed."""
        raw = '["a", "b",]'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"items": ["a", "b"]}


# ---------------------------------------------------------------------------
# heal_response() — unclosed brackets
# ---------------------------------------------------------------------------


class TestHealResponseUnclosedBrackets:
    async def test_heal_response_unclosed_brace_closed(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Missing closing brace is appended."""
        raw = '{"title": "Test", "body": "Content"'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"title": "Test", "body": "Content"}

    async def test_heal_response_unclosed_bracket_closed(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Missing closing bracket is appended."""
        raw = '["a", "b"'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"items": ["a", "b"]}

    async def test_heal_response_multiple_unclosed(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Multiple missing closing braces are appended."""
        raw = '{"data": {"nested": "value"'
        result = await orchestrator.heal_response(raw, "json")

        assert result == {"data": {"nested": "value"}}


# ---------------------------------------------------------------------------
# heal_response() — non-json format
# ---------------------------------------------------------------------------


class TestHealResponseNonJsonFormat:
    async def test_heal_response_non_json_format_returns_raw(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """When expected_format is not 'json', raw string is returned as-is."""
        raw = "This is plain text"
        result = await orchestrator.heal_response(raw, "text")

        assert result == "This is plain text"

    async def test_heal_response_html_format_returns_raw(
        self,
        orchestrator: AIOrchestrator,
    ) -> None:
        """Non-json format (e.g. html) returns raw."""
        raw = "<h1>Title</h1>"
        result = await orchestrator.heal_response(raw, "html")

        assert result == "<h1>Title</h1>"


# ---------------------------------------------------------------------------
# heal_response() — all fixes fail
# ---------------------------------------------------------------------------


class TestHealResponseAllFail:
    async def test_heal_response_all_fixes_fail_returns_none(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """When raw is not JSON and budget model also fails, returns None."""
        raw = "completely invalid non-json non-bracket text"
        # Budget model also returns garbage
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content="still not json either no braces",
        )

        result = await orchestrator.heal_response(raw, "json")

        assert result is None

    async def test_heal_response_budget_model_exception_returns_none(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """When budget model raises an exception, returns None."""
        raw = "not json at all with no fixable structure"
        mock_openai_client.chat.completions.create.side_effect = Exception("Model unavailable")

        result = await orchestrator.heal_response(raw, "json")

        assert result is None


# ---------------------------------------------------------------------------
# _regex_fix_json() — strips code fences
# ---------------------------------------------------------------------------


class TestRegexFixJson:
    def test_strips_json_code_fence(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = AIOrchestrator._regex_fix_json(text)

        assert "```" not in result
        assert result.strip() == '{"key": "value"}'

    def test_strips_plain_code_fence(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = AIOrchestrator._regex_fix_json(text)

        assert "```" not in result

    def test_removes_trailing_comma(self) -> None:
        text = '{"a": 1, "b": 2,}'
        result = AIOrchestrator._regex_fix_json(text)

        assert result == '{"a": 1, "b": 2}'

    def test_closes_unclosed_brace(self) -> None:
        text = '{"key": "value"'
        result = AIOrchestrator._regex_fix_json(text)

        assert result == '{"key": "value"}'

    def test_closes_unclosed_bracket(self) -> None:
        text = '["a", "b"'
        result = AIOrchestrator._regex_fix_json(text)

        assert result == '["a", "b"]'

    def test_combined_fixes(self) -> None:
        """Multiple issues in one string: code fence + trailing comma + unclosed brace."""
        text = '```json\n{"items": [1, 2,]\n```'
        result = AIOrchestrator._regex_fix_json(text)
        # Should strip fence, remove trailing comma, close unclosed brace
        parsed = json.loads(result)

        assert parsed == {"items": [1, 2]}

    def test_already_valid_json_unchanged(self) -> None:
        text = '{"key": "value"}'
        result = AIOrchestrator._regex_fix_json(text)

        assert result == '{"key": "value"}'


# ---------------------------------------------------------------------------
# _try_parse_json() — invalid text
# ---------------------------------------------------------------------------


class TestTryParseJson:
    def test_valid_dict(self) -> None:
        result = AIOrchestrator._try_parse_json('{"a": 1}')

        assert result == {"a": 1}

    def test_valid_list(self) -> None:
        result = AIOrchestrator._try_parse_json("[1, 2, 3]")

        assert result == [1, 2, 3]

    def test_invalid_json_returns_none(self) -> None:
        result = AIOrchestrator._try_parse_json("not json at all")

        assert result is None

    def test_empty_string_returns_none(self) -> None:
        result = AIOrchestrator._try_parse_json("")

        assert result is None

    def test_json_string_value_returns_none(self) -> None:
        """A bare JSON string (not dict/list) should return None."""
        result = AIOrchestrator._try_parse_json('"just a string"')

        assert result is None

    def test_json_number_returns_none(self) -> None:
        """A bare JSON number (not dict/list) should return None."""
        result = AIOrchestrator._try_parse_json("42")

        assert result is None

    def test_json_null_returns_none(self) -> None:
        result = AIOrchestrator._try_parse_json("null")

        assert result is None


# ---------------------------------------------------------------------------
# MODEL_CHAINS verification
# ---------------------------------------------------------------------------


class TestModelChains:
    def test_all_tasks_present(self) -> None:
        expected_tasks = {
            "article",
            "social_post",
            "keywords",
            "keywords_fallback",
            "review",
            "description",
            "competitor_analysis",
            "image",
            "article_outline",
            "article_critique",
        }
        assert set(MODEL_CHAINS.keys()) == expected_tasks

    def test_each_chain_has_at_least_two_models(self) -> None:
        for task, chain in MODEL_CHAINS.items():
            assert len(chain) >= 2, f"Task {task} has fewer than 2 models"

    def test_article_primary_is_claude(self) -> None:
        assert MODEL_CHAINS["article"][0] == "anthropic/claude-sonnet-4.5"

    def test_social_post_primary_is_deepseek(self) -> None:
        assert MODEL_CHAINS["social_post"][0] == "deepseek/deepseek-v3.2"

    def test_image_uses_gemini(self) -> None:
        for model in MODEL_CHAINS["image"]:
            assert "gemini" in model or "google" in model


# ---------------------------------------------------------------------------
# generate() — extra_body construction
# ---------------------------------------------------------------------------


class TestGenerateExtraBody:
    async def test_generate_budget_task_has_price_sorting(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """Budget tasks (social_post, keywords, etc.) include sort: price."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"text": "Post content"}',
        )

        request = GenerationRequest(task="social_post", context={}, user_id=123)
        await orchestrator.generate(request)

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs["extra_body"]
        assert extra_body["provider"]["sort"] == "price"

    async def test_generate_non_budget_task_no_price_sorting(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """Non-budget tasks (article) do not include sort: price."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"title": "Test"}',
            model="anthropic/claude-sonnet-4.5",
        )

        request = GenerationRequest(task="article", context={}, user_id=123)
        await orchestrator.generate(request)

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs["extra_body"]
        assert "sort" not in extra_body["provider"]

    async def test_generate_healing_task_has_plugins(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """Healing tasks include the response-healing plugin."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"title": "Test"}',
            model="anthropic/claude-sonnet-4.5",
        )

        request = GenerationRequest(task="article", context={}, user_id=123)
        await orchestrator.generate(request)

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs["extra_body"]
        assert extra_body["plugins"] == [{"id": "response-healing"}]

    async def test_generate_image_task_has_modalities(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
        mock_prompt_engine: AsyncMock,
    ) -> None:
        """Image task sets modalities and image_config in extra_body."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content="base64_image_data",
            model="google/gemini-3-pro-image-preview",
        )

        request = GenerationRequest(
            task="image",
            context={
                "topic": "SEO",
                "image_settings": {"formats": ["16:9"], "quality": "Ultra HD"},
            },
            user_id=123,
        )
        await orchestrator.generate(request)

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        extra_body = call_kwargs.kwargs["extra_body"]
        assert extra_body["modalities"] == ["image", "text"]
        assert extra_body["image_config"]["aspect_ratio"] == "16:9"
        assert extra_body["image_config"]["image_size"] == "2K"

    async def test_models_array_excludes_primary(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
    ) -> None:
        """models in extra_body should be fallbacks only, NOT include primary."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='{"title": "Test"}',
            model="anthropic/claude-sonnet-4.5",
        )

        request = GenerationRequest(task="article", context={}, user_id=123)
        await orchestrator.generate(request)

        call_kwargs = mock_openai_client.chat.completions.create.call_args
        primary_model = call_kwargs.kwargs["model"]
        extra_body = call_kwargs.kwargs["extra_body"]
        fallback_models = extra_body["models"]

        # Primary should be the first in chain
        assert primary_model == "anthropic/claude-sonnet-4.5"
        # Fallbacks should NOT include primary
        assert primary_model not in fallback_models
        # Fallbacks should be the rest of the chain
        assert fallback_models == ["openai/gpt-5.2", "deepseek/deepseek-v3.2"]


# ---------------------------------------------------------------------------
# generate() — rate action mapping
# ---------------------------------------------------------------------------


class TestRateActionMapping:
    async def test_generate_image_uses_image_generation_action(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
        mock_rate_limiter: AsyncMock,
    ) -> None:
        """Image task maps to 'image_generation' rate limit action."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content="image_data",
            model="google/gemini-3-pro-image-preview",
        )

        request = GenerationRequest(task="image", context={}, user_id=123)
        await orchestrator.generate(request)

        mock_rate_limiter.check.assert_awaited_once_with(123, "image_generation")

    async def test_generate_keywords_uses_keyword_generation_action(
        self,
        orchestrator: AIOrchestrator,
        mock_openai_client: AsyncMock,
        mock_rate_limiter: AsyncMock,
    ) -> None:
        """Keywords task maps to 'keyword_generation' rate limit action."""
        mock_openai_client.chat.completions.create.return_value = _make_openai_response(
            content='["kw1", "kw2"]',
        )

        request = GenerationRequest(task="keywords", context={}, user_id=123)
        await orchestrator.generate(request)

        mock_rate_limiter.check.assert_awaited_once_with(123, "keyword_generation")


# ---------------------------------------------------------------------------
# GenerationContext — to_dict() (skips None, flattens nested)
# ---------------------------------------------------------------------------


class TestGenerationContext:
    def test_to_dict_basic_fields_always_present(self) -> None:
        """Required scalar fields are always in the output dict."""
        ctx = GenerationContext(
            company_name="TestCo",
            specialization="SEO",
            keyword="seo services",
        )
        d = ctx.to_dict()
        assert d["company_name"] == "TestCo"
        assert d["specialization"] == "SEO"
        assert d["keyword"] == "seo services"
        assert d["language"] == "ru"
        # Optional fields not set -> not in dict
        assert "city" not in d
        assert "main_phrase" not in d
        assert "competitor_analysis" not in d

    def test_to_dict_cluster_fields_flattened(self) -> None:
        """ClusterContext fields are flattened into the output dict."""
        ctx = GenerationContext(
            company_name="TestCo",
            specialization="SEO",
            keyword="seo services",
            cluster=ClusterContext(
                main_phrase="seo services moscow",
                secondary_phrases="seo agency (1000/мес), seo firm (500/мес)",
                cluster_volume=26500,
                main_volume=12400,
                main_difficulty=52,
                cluster_type="article",
            ),
        )
        d = ctx.to_dict()
        assert d["main_phrase"] == "seo services moscow"
        assert d["secondary_phrases"] == "seo agency (1000/мес), seo firm (500/мес)"
        assert d["cluster_volume"] == "26500"
        assert d["main_volume"] == "12400"
        assert d["main_difficulty"] == "52"
        assert d["cluster_type"] == "article"

    def test_to_dict_skips_none_optional_fields(self) -> None:
        """None optional fields are omitted to avoid Jinja2 rendering 'None' string."""
        ctx = GenerationContext(
            company_name="TestCo",
            specialization="SEO",
            keyword="seo",
            city=None,
            advantages="Fast",
            words_min=None,
            images_count=4,
        )
        d = ctx.to_dict()
        assert "city" not in d
        assert d["advantages"] == "Fast"
        assert "words_min" not in d
        assert d["images_count"] == "4"
