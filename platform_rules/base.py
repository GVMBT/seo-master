"""Abstract base for platform-specific content validation rules.

Source of truth: docs/API_CONTRACTS.md section 3.7.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod

from services.ai.content_validator import (
    PLACEHOLDER_PATTERNS,
    ValidationResult,
)


class PlatformRule(ABC):
    """Base class for platform-specific content validation.

    Subclasses implement ``_validate_platform`` with checks specific to a
    single platform.  Common checks (placeholder detection) live here so
    they run for every platform without duplication.
    """

    @abstractmethod
    def _validate_platform(
        self,
        content: str,
        content_type: str,
        *,
        title: str = "",
        has_image: bool = False,
    ) -> ValidationResult:
        """Platform-specific validation — implemented by each subclass."""

    def validate(
        self,
        content: str,
        content_type: str,
        *,
        title: str = "",
        has_image: bool = False,
    ) -> ValidationResult:
        """Run common checks then delegate to platform-specific logic."""
        common = self._check_placeholders(content)
        platform = self._validate_platform(
            content,
            content_type,
            title=title,
            has_image=has_image,
        )

        errors = common.errors + platform.errors
        warnings = common.warnings + platform.warnings
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Common checks (shared across all platforms)
    # ------------------------------------------------------------------

    @staticmethod
    def _check_placeholders(content: str) -> ValidationResult:
        """Detect placeholder text that should not appear in published content."""
        errors: list[str] = []
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                errors.append(f"Обнаружен placeholder-текст: {pattern}")
        return ValidationResult(is_valid=len(errors) == 0, errors=errors)
