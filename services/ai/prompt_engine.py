"""Jinja2 prompt renderer with YAML loader and DB reader.

Source of truth: API_CONTRACTS.md section 5.0.
YAML files = seed data, DB prompt_versions = runtime source.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml
from jinja2 import Environment

from cache.client import RedisClient
from cache.keys import PROMPT_CACHE_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import PromptVersion
from db.repositories.prompts import PromptsRepository

log = structlog.get_logger()


@dataclass
class RenderedPrompt:
    """Result of prompt rendering."""

    system: str
    user: str
    meta: dict[str, Any] = field(default_factory=dict)
    version: str = ""


def _sanitize_variables(context: dict[str, Any]) -> dict[str, Any]:
    """Strip Jinja2 delimiters from user input to prevent prompt injection."""
    sanitized: dict[str, Any] = {}
    for key, value in context.items():
        if isinstance(value, str):
            value = value.replace("<<", "").replace(">>", "")
            value = value.replace("<%", "").replace("%>", "")
            value = value.replace("<#", "").replace("#>", "")
        sanitized[key] = value
    return sanitized


class PromptEngine:
    """Renders prompts from DB prompt_versions with Jinja2 <<>> delimiters."""

    def __init__(self, db: SupabaseClient, redis: RedisClient | None = None) -> None:
        self._prompts_repo = PromptsRepository(db)
        self._redis = redis
        self._env = Environment(
            variable_start_string="<<",
            variable_end_string=">>",
            block_start_string="<%",
            block_end_string="%>",
            comment_start_string="<#",
            comment_end_string="#>",
            autoescape=False,  # noqa: S701  # nosec B701 — prompts are AI text, not HTML; sanitized via _sanitize_variables
        )

    async def _load_prompt(self, task_type: str) -> PromptVersion | None:
        """Load active prompt version, with optional Redis cache.

        Redis errors are non-fatal: cache is an optimization, not critical path.
        """
        if self._redis:
            try:
                cache_key = CacheKeys.prompt_cache(task_type)
                cached = await self._redis.get(cache_key)
                if cached:
                    return PromptVersion.model_validate_json(cached)
            except Exception:
                log.warning("prompt_cache_read_failed", task_type=task_type, exc_info=True)

        prompt = await self._prompts_repo.get_active(task_type)

        if prompt and self._redis:
            try:
                cache_key = CacheKeys.prompt_cache(task_type)
                await self._redis.set(cache_key, prompt.model_dump_json(), ex=PROMPT_CACHE_TTL)
            except Exception:
                log.warning("prompt_cache_write_failed", task_type=task_type, exc_info=True)

        return prompt

    async def render(self, task_type: str, context: dict[str, Any]) -> RenderedPrompt:
        """Load active prompt from DB and render with context.

        Raises AIGenerationError if no active prompt found.
        """
        from bot.exceptions import AIGenerationError

        prompt_version = await self._load_prompt(task_type)
        if prompt_version is None:
            raise AIGenerationError(
                message=f"No active prompt for task_type={task_type}",
                user_message="Промпт не настроен. Обратитесь к администратору",
            )

        parsed = yaml.safe_load(prompt_version.prompt_yaml)
        meta = parsed.get("meta", {})
        system_template = parsed.get("system", "")
        user_template = parsed.get("user", "")

        safe_context = _sanitize_variables(context)

        # Apply defaults from variables spec
        variables = parsed.get("variables", [])
        for var in variables:
            name = var.get("name", "")
            if name and name not in safe_context:
                if var.get("required", False) and "default" not in var:
                    raise AIGenerationError(
                        message=f"Missing required variable: {name}",
                        user_message="Недостаточно данных для генерации",
                    )
                if "default" in var:
                    safe_context[name] = var["default"]

        system_rendered = self._env.from_string(system_template).render(**safe_context)
        user_rendered = self._env.from_string(user_template).render(**safe_context)

        return RenderedPrompt(
            system=system_rendered.strip(),
            user=user_rendered.strip(),
            meta=meta,
            version=prompt_version.version,
        )

    @staticmethod
    def load_yaml_seed(path: str | Path) -> dict[str, Any]:
        """Load a YAML prompt file from disk (for sync_prompts CLI)."""
        with open(path, encoding="utf-8") as f:
            result: dict[str, Any] = yaml.safe_load(f)
            return result
