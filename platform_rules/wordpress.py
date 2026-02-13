"""WordPress content validation rules.

Source of truth: docs/API_CONTRACTS.md section 3.7.
Reuses PLATFORM_LIMITS from services/ai/content_validator.py.
"""

from __future__ import annotations

import re

from platform_rules.base import PlatformRule
from services.ai.content_validator import PLATFORM_LIMITS, ValidationResult

_WP_LIMITS = PLATFORM_LIMITS["wordpress"]


class WordPressRule(PlatformRule):
    """Validates content destined for WordPress publication."""

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

        if content_type == "article":
            min_len = _WP_LIMITS["min_article"]
            if len(content) < min_len:
                errors.append(
                    f"Текст слишком короткий ({len(content)} символов, мин. {min_len})"
                )

            if not re.search(r"<h1[^>]*>", content):
                errors.append("Отсутствует H1-заголовок")

            if not re.search(r"<p[^>]*>.{50,}", content):
                errors.append("Нет абзацев связного текста (мин. 50 символов)")

            if "faq" not in content.lower():
                warnings.append("Нет FAQ-секции")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
