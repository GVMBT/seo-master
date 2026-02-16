"""Pinterest content validation rules.

Source of truth: docs/API_CONTRACTS.md section 3.7.
Reuses PLATFORM_LIMITS from services/ai/content_validator.py.
"""

from __future__ import annotations

from platform_rules.base import PlatformRule
from services.ai.content_validator import PLATFORM_LIMITS, ValidationResult

_PIN_LIMITS = PLATFORM_LIMITS["pinterest"]


class PinterestRule(PlatformRule):
    """Validates content destined for Pinterest publication."""

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

        # Description length
        max_desc = _PIN_LIMITS["max_description"]
        if len(content) > max_desc:
            errors.append(f"Описание превышает лимит Pinterest ({len(content)}/{max_desc})")

        # Title length
        max_title = _PIN_LIMITS["max_title"]
        if title and len(title) > max_title:
            errors.append(f"Заголовок превышает лимит Pinterest ({len(title)}/{max_title})")

        # Image is required for Pinterest pins
        if not has_image:
            errors.append("Pinterest требует изображение для публикации")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
