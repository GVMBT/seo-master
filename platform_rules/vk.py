"""VK content validation rules.

Source of truth: docs/API_CONTRACTS.md section 3.7.
Reuses PLATFORM_LIMITS from services/ai/content_validator.py.
"""

from __future__ import annotations

import re

from platform_rules.base import PlatformRule
from services.ai.content_validator import PLATFORM_LIMITS, ValidationResult

_VK_LIMITS = PLATFORM_LIMITS["vk"]

# VK wall.post supports only plain text — HTML tags are not rendered
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class VKRule(PlatformRule):
    """Validates content destined for VK publication."""

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

        max_len = _VK_LIMITS["max_text"]
        if len(content) > max_len:
            errors.append(
                f"Текст превышает лимит VK ({len(content)}/{max_len})"
            )

        # Warn if HTML tags are present (VK does not render them)
        if _HTML_TAG_RE.search(content):
            warnings.append("VK не поддерживает HTML-разметку — теги будут удалены")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
