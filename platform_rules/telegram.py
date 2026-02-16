"""Telegram content validation rules.

Source of truth: docs/API_CONTRACTS.md section 3.7.
Reuses PLATFORM_LIMITS from services/ai/content_validator.py.
"""

from __future__ import annotations

import re

from platform_rules.base import PlatformRule
from services.ai.content_validator import PLATFORM_LIMITS, ValidationResult

_TG_LIMITS = PLATFORM_LIMITS["telegram"]

# Telegram Bot API supports only these HTML tags
_TG_ALLOWED_TAGS = frozenset(
    {
        "b",
        "strong",
        "i",
        "em",
        "u",
        "ins",
        "s",
        "strike",
        "del",
        "a",
        "code",
        "pre",
        "span",
        "tg-spoiler",
        "tg-emoji",
        "blockquote",
    }
)

# Regex to find HTML tags (opening or self-closing)
_TAG_RE = re.compile(r"</?(\w[\w-]*)[^>]*>")


class TelegramRule(PlatformRule):
    """Validates content destined for Telegram publication."""

    def _validate_platform(
        self,
        content: str,
        content_type: str,
        *,
        title: str = "",
        has_image: bool = False,
    ) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []

        # Length limits depend on whether there is an image (caption vs text)
        if has_image:
            max_len = _TG_LIMITS["max_caption"]
            label = "caption"
        else:
            max_len = _TG_LIMITS["max_text"]
            label = "text"

        if len(content) > max_len:
            errors.append(f"Текст превышает лимит Telegram {label} ({len(content)}/{max_len})")

        # HTML tag whitelist
        unsupported = self._find_unsupported_tags(content)
        if unsupported:
            tags_str = ", ".join(sorted(unsupported))
            errors.append(f"Неподдерживаемые HTML-теги для Telegram: {tags_str}")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    @staticmethod
    def _find_unsupported_tags(content: str) -> set[str]:
        """Return set of HTML tag names not supported by Telegram."""
        found: set[str] = set()
        for match in _TAG_RE.finditer(content):
            tag_name = match.group(1).lower()
            if tag_name not in _TG_ALLOWED_TAGS:
                found.add(tag_name)
        return found
