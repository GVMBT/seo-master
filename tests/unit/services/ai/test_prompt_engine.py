"""Tests for services/ai/prompt_engine.py — Jinja2 prompt renderer.

Covers: render(), _sanitize_variables(), load_yaml_seed(), RenderedPrompt dataclass.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from bot.exceptions import AIGenerationError
from db.models import PromptVersion
from services.ai.prompt_engine import PromptEngine, RenderedPrompt, _sanitize_variables

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ARTICLE_YAML = """\
meta:
  task_type: article
  max_tokens: 8000
  temperature: 0.7
system: |
  You are a writer. Language: <<language>>.
  Company: <<company_name>>.
user: |
  Write about "<<keyword>>".
variables:
  - name: keyword
    required: true
  - name: language
    required: true
    default: "ru"
  - name: company_name
    required: true
"""

_SOCIAL_YAML = """\
meta:
  task_type: social_post
  max_tokens: 1000
system: |
  Social media post for <<platform>>.
user: |
  Topic: <<topic>>.
  Tone: <<tone>>.
variables:
  - name: platform
    required: true
  - name: topic
    required: true
  - name: tone
    required: false
    default: "friendly"
"""

_NO_VARIABLES_YAML = """\
meta:
  task_type: simple
system: |
  Static system prompt.
user: |
  Static user prompt.
"""

_BLOCK_SYNTAX_YAML = """\
meta:
  task_type: conditional
system: |
  <% if include_seo %>SEO mode enabled.<% endif %>
user: |
  Write about <<topic>>.
variables:
  - name: include_seo
    required: false
    default: true
  - name: topic
    required: true
"""


def _make_prompt_version(
    task_type: str = "article",
    version: str = "v5",
    prompt_yaml: str = _ARTICLE_YAML,
    is_active: bool = True,
) -> PromptVersion:
    return PromptVersion(
        id=1,
        task_type=task_type,
        version=version,
        prompt_yaml=prompt_yaml,
        is_active=is_active,
    )


@pytest.fixture
def mock_db() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def engine(mock_db: AsyncMock) -> PromptEngine:
    """PromptEngine with mocked DB client."""
    return PromptEngine(mock_db)


# ---------------------------------------------------------------------------
# RenderedPrompt dataclass
# ---------------------------------------------------------------------------


class TestRenderedPrompt:
    def test_create_with_defaults(self) -> None:
        rp = RenderedPrompt(system="sys", user="usr")
        assert rp.system == "sys"
        assert rp.user == "usr"
        assert rp.meta == {}
        assert rp.version == ""

    def test_create_with_all_fields(self) -> None:
        rp = RenderedPrompt(
            system="sys",
            user="usr",
            meta={"task_type": "article", "max_tokens": 8000},
            version="v5",
        )
        assert rp.meta["max_tokens"] == 8000
        assert rp.version == "v5"


# ---------------------------------------------------------------------------
# _sanitize_variables()
# ---------------------------------------------------------------------------


class TestSanitizeVariables:
    def test_strips_variable_delimiters(self) -> None:
        ctx: dict[str, Any] = {"keyword": "<<malicious>> input"}
        result = _sanitize_variables(ctx)
        assert result["keyword"] == "malicious input"

    def test_strips_block_delimiters(self) -> None:
        ctx: dict[str, Any] = {"keyword": "<% evil %> code"}
        result = _sanitize_variables(ctx)
        assert result["keyword"] == " evil  code"

    def test_strips_comment_delimiters(self) -> None:
        ctx: dict[str, Any] = {"keyword": "<# comment #> text"}
        result = _sanitize_variables(ctx)
        assert result["keyword"] == " comment  text"

    def test_strips_mixed_delimiters(self) -> None:
        ctx: dict[str, Any] = {"keyword": "<<a>> <% b %> <# c #>"}
        result = _sanitize_variables(ctx)
        assert result["keyword"] == "a  b   c "

    def test_preserves_non_string_values(self) -> None:
        ctx: dict[str, Any] = {"count": 42, "flag": True, "items": ["a", "b"]}
        result = _sanitize_variables(ctx)
        assert result["count"] == 42
        assert result["flag"] is True
        assert result["items"] == ["a", "b"]

    def test_empty_context(self) -> None:
        assert _sanitize_variables({}) == {}

    def test_clean_string_unchanged(self) -> None:
        ctx: dict[str, Any] = {"keyword": "normal text without delimiters"}
        result = _sanitize_variables(ctx)
        assert result["keyword"] == "normal text without delimiters"


# ---------------------------------------------------------------------------
# PromptEngine.render() — valid prompts
# ---------------------------------------------------------------------------


class TestRenderValid:
    async def test_render_all_variables_provided(self, engine: PromptEngine) -> None:
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "SEO tips", "language": "en", "company_name": "Acme"},
            )
        assert isinstance(result, RenderedPrompt)
        assert "SEO tips" in result.user
        assert "en" in result.system
        assert "Acme" in result.system
        assert result.version == "v5"
        assert result.meta["task_type"] == "article"
        assert result.meta["max_tokens"] == 8000

    async def test_render_fills_default_for_optional_missing(self, engine: PromptEngine) -> None:
        """When 'language' has default 'ru' and is not provided, it should use default."""
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "SEO tips", "company_name": "Acme"},
            )
        assert "ru" in result.system

    async def test_render_default_overridden_by_context(self, engine: PromptEngine) -> None:
        """When variable has default but context provides a value, context wins."""
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "SEO tips", "language": "de", "company_name": "Acme"},
            )
        assert "de" in result.system
        assert "ru" not in result.system

    async def test_render_strips_output(self, engine: PromptEngine) -> None:
        """Rendered system/user should be stripped of leading/trailing whitespace."""
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "test", "language": "ru", "company_name": "X"},
            )
        assert not result.system.startswith("\n")
        assert not result.system.endswith("\n")
        assert not result.user.startswith("\n")
        assert not result.user.endswith("\n")

    async def test_render_no_variables_section(self, engine: PromptEngine) -> None:
        """YAML with no variables section should render static prompts."""
        pv = _make_prompt_version(prompt_yaml=_NO_VARIABLES_YAML, task_type="simple")
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render("simple", {})
        assert result.system == "Static system prompt."
        assert result.user == "Static user prompt."

    async def test_render_social_post_with_defaults(self, engine: PromptEngine) -> None:
        """Social post YAML with tone default='friendly'."""
        pv = _make_prompt_version(
            task_type="social_post",
            prompt_yaml=_SOCIAL_YAML,
            version="v2",
        )
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "social_post",
                {"platform": "VK", "topic": "SEO trends"},
            )
        assert "VK" in result.system
        assert "SEO trends" in result.user
        assert "friendly" in result.user
        assert result.version == "v2"

    async def test_render_meta_preserved(self, engine: PromptEngine) -> None:
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "test", "language": "ru", "company_name": "X"},
            )
        assert result.meta["temperature"] == 0.7

    async def test_render_sanitizes_user_input(self, engine: PromptEngine) -> None:
        """Jinja2 delimiters in user input should be stripped before rendering."""
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {
                    "keyword": "<<injection>> attempt",
                    "language": "ru",
                    "company_name": "<% block %> evil",
                },
            )
        # Delimiters stripped, so raw text appears
        assert "injection attempt" in result.user
        assert "<<" not in result.user
        assert "<%" not in result.system


# ---------------------------------------------------------------------------
# PromptEngine.render() — error cases
# ---------------------------------------------------------------------------


class TestRenderErrors:
    async def test_render_no_active_prompt_raises(self, engine: PromptEngine) -> None:
        with (
            patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=None),
            pytest.raises(AIGenerationError, match="No active prompt"),
        ):
            await engine.render("nonexistent_type", {"keyword": "test"})

    async def test_render_missing_required_variable_no_default_raises(
        self, engine: PromptEngine
    ) -> None:
        """When a required variable without default is missing from context, raise."""
        pv = _make_prompt_version()
        with (
            patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv),
            pytest.raises(AIGenerationError, match="Missing required variable: keyword"),
        ):
            await engine.render("article", {"language": "en", "company_name": "Acme"})

    async def test_render_missing_required_variable_with_default_ok(
        self, engine: PromptEngine
    ) -> None:
        """Required variable WITH default should not raise when missing."""
        pv = _make_prompt_version()
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            # 'language' is required but has default 'ru' — should not raise
            result = await engine.render(
                "article",
                {"keyword": "test", "company_name": "X"},
            )
        assert "ru" in result.system

    async def test_render_multiple_missing_required_raises_on_first(
        self, engine: PromptEngine
    ) -> None:
        """When multiple required variables are missing, raises on the first one found."""
        pv = _make_prompt_version()
        with (
            patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv),
            pytest.raises(AIGenerationError, match="Missing required variable"),
        ):
            await engine.render("article", {})

    async def test_render_error_user_message_russian(self, engine: PromptEngine) -> None:
        """AIGenerationError should contain Russian user_message."""
        with (
            patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=None),
            pytest.raises(AIGenerationError) as exc_info,
        ):
            await engine.render("bad_type", {})
        assert exc_info.value.user_message == "Промпт не настроен. Обратитесь к администратору"

    async def test_render_missing_variable_user_message(self, engine: PromptEngine) -> None:
        pv = _make_prompt_version()
        with (
            patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv),
            pytest.raises(AIGenerationError) as exc_info,
        ):
            await engine.render("article", {"language": "en", "company_name": "X"})
        assert exc_info.value.user_message == "Недостаточно данных для генерации"


# ---------------------------------------------------------------------------
# PromptEngine.render() — block syntax
# ---------------------------------------------------------------------------


class TestRenderBlockSyntax:
    async def test_render_with_block_syntax(self, engine: PromptEngine) -> None:
        """Jinja2 block syntax (<% %>) should work for conditionals."""
        pv = _make_prompt_version(
            task_type="conditional",
            prompt_yaml=_BLOCK_SYNTAX_YAML,
        )
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "conditional",
                {"topic": "Python", "include_seo": True},
            )
        assert "SEO mode enabled." in result.system

    async def test_render_block_false_condition(self, engine: PromptEngine) -> None:
        pv = _make_prompt_version(
            task_type="conditional",
            prompt_yaml=_BLOCK_SYNTAX_YAML,
        )
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "conditional",
                {"topic": "Python", "include_seo": False},
            )
        assert "SEO mode enabled." not in result.system


# ---------------------------------------------------------------------------
# PromptEngine.load_yaml_seed() — static method
# ---------------------------------------------------------------------------


class TestLoadYamlSeed:
    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = _ARTICLE_YAML
        yaml_file = tmp_path / "article.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        result = PromptEngine.load_yaml_seed(yaml_file)

        assert isinstance(result, dict)
        assert result["meta"]["task_type"] == "article"
        assert result["meta"]["max_tokens"] == 8000
        assert result["meta"]["temperature"] == 0.7
        assert "<<keyword>>" in result["user"]
        assert len(result["variables"]) == 3

    def test_load_yaml_with_str_path(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\n", encoding="utf-8")

        result = PromptEngine.load_yaml_seed(str(yaml_file))
        assert result == {"key": "value"}

    def test_load_yaml_preserves_variables_list(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "social.yaml"
        yaml_file.write_text(_SOCIAL_YAML, encoding="utf-8")

        result = PromptEngine.load_yaml_seed(yaml_file)
        variables = result["variables"]
        assert len(variables) == 3
        assert variables[0]["name"] == "platform"
        assert variables[0]["required"] is True
        assert variables[2]["name"] == "tone"
        assert variables[2]["default"] == "friendly"

    def test_load_yaml_file_not_found_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            PromptEngine.load_yaml_seed("/nonexistent/path/prompt.yaml")


# ---------------------------------------------------------------------------
# PromptEngine.__init__ — Jinja2 Environment config
# ---------------------------------------------------------------------------


class TestEngineInit:
    def test_jinja_env_delimiters(self, engine: PromptEngine) -> None:
        env = engine._env
        assert env.variable_start_string == "<<"
        assert env.variable_end_string == ">>"
        assert env.block_start_string == "<%"
        assert env.block_end_string == "%>"
        assert env.comment_start_string == "<#"
        assert env.comment_end_string == "#>"

    def test_prompts_repo_created(self, engine: PromptEngine) -> None:
        assert engine._prompts_repo is not None


# ---------------------------------------------------------------------------
# Integration-like: render with PromptsRepository patched at module level
# ---------------------------------------------------------------------------


class TestRenderModulePatch:
    async def test_render_via_module_patch(self, mock_db: AsyncMock) -> None:
        """Patch PromptsRepository at module import location."""
        pv = _make_prompt_version()
        with patch(
            "services.ai.prompt_engine.PromptsRepository"
        ) as mock_repo_cls:
            mock_repo_instance = AsyncMock()
            mock_repo_instance.get_active.return_value = pv
            mock_repo_cls.return_value = mock_repo_instance

            eng = PromptEngine(mock_db)
            result = await eng.render(
                "article",
                {"keyword": "test", "language": "en", "company_name": "Corp"},
            )

        assert result.system == "You are a writer. Language: en.\nCompany: Corp."
        assert result.user == 'Write about "test".'
        assert result.version == "v5"
        mock_repo_instance.get_active.assert_awaited_once_with("article")


# ---------------------------------------------------------------------------
# PromptEngine._load_prompt() — Redis caching
# ---------------------------------------------------------------------------


class TestLoadPromptCaching:
    async def test_cache_miss_calls_db_and_stores(self) -> None:
        """On cache miss, loads from DB and stores result in Redis."""
        pv = _make_prompt_version()
        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None  # cache miss

        engine = PromptEngine(mock_db, redis=mock_redis)
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "test", "language": "ru", "company_name": "X"},
            )

        assert result.version == "v5"
        mock_redis.get.assert_awaited_once()
        mock_redis.set.assert_awaited_once()

    async def test_cache_hit_skips_db(self) -> None:
        """On cache hit, deserializes from Redis without DB call."""
        pv = _make_prompt_version()
        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = pv.model_dump_json()  # cache hit

        engine = PromptEngine(mock_db, redis=mock_redis)
        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock) as mock_get:
            result = await engine.render(
                "article",
                {"keyword": "test", "language": "ru", "company_name": "X"},
            )

        assert result.version == "v5"
        mock_redis.get.assert_awaited_once()
        mock_get.assert_not_awaited()  # DB NOT called
        mock_redis.set.assert_not_awaited()  # no re-store

    async def test_no_redis_skips_caching(self) -> None:
        """Without Redis, loads directly from DB."""
        pv = _make_prompt_version()
        mock_db = AsyncMock()
        engine = PromptEngine(mock_db)  # no redis

        with patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=pv):
            result = await engine.render(
                "article",
                {"keyword": "test", "language": "ru", "company_name": "X"},
            )

        assert result.version == "v5"

    async def test_cache_miss_no_prompt_returns_none(self) -> None:
        """When DB returns None, nothing is cached."""
        mock_db = AsyncMock()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        engine = PromptEngine(mock_db, redis=mock_redis)
        with (
            patch.object(engine._prompts_repo, "get_active", new_callable=AsyncMock, return_value=None),
            pytest.raises(AIGenerationError),
        ):
            await engine.render("nonexistent", {})

        mock_redis.set.assert_not_awaited()  # don't cache None
