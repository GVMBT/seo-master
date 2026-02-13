"""Tests for platform_rules/base.py — PlatformRule base class.

Covers: _check_placeholders, validate() combines common + platform checks.
"""

from __future__ import annotations

from platform_rules.base import PlatformRule
from services.ai.content_validator import PLACEHOLDER_PATTERNS, ValidationResult

# ---------------------------------------------------------------------------
# Concrete subclass for testing the base class behavior
# ---------------------------------------------------------------------------


class _TestRule(PlatformRule):
    """Minimal concrete rule for testing base class logic."""

    def __init__(self, platform_errors: list[str] | None = None, platform_warnings: list[str] | None = None) -> None:
        self._errors = platform_errors or []
        self._warnings = platform_warnings or []

    def _validate_platform(
        self,
        content: str,
        content_type: str,
        *,
        title: str = "",
        has_image: bool = False,
    ) -> ValidationResult:
        return ValidationResult(
            is_valid=len(self._errors) == 0,
            errors=list(self._errors),
            warnings=list(self._warnings),
        )


# ---------------------------------------------------------------------------
# _check_placeholders
# ---------------------------------------------------------------------------


class TestCheckPlaceholders:
    def test_clean_content_no_errors(self) -> None:
        result = PlatformRule._check_placeholders("Normal article text about SEO.")
        assert result.is_valid is True
        assert result.errors == []

    def test_insert_placeholder_detected(self) -> None:
        result = PlatformRule._check_placeholders("Text with [INSERT KEYWORD] here")
        assert result.is_valid is False
        assert any("INSERT" in e for e in result.errors)

    def test_lorem_ipsum_detected(self) -> None:
        result = PlatformRule._check_placeholders("Lorem ipsum dolor sit amet")
        assert result.is_valid is False
        assert any("Lorem ipsum" in e for e in result.errors)

    def test_todo_detected(self) -> None:
        result = PlatformRule._check_placeholders("Fix TODO in this section")
        assert result.is_valid is False
        assert any("TODO" in e for e in result.errors)

    def test_your_placeholder_detected(self) -> None:
        result = PlatformRule._check_placeholders("Welcome to [YOUR COMPANY]")
        assert result.is_valid is False
        assert any("YOUR" in e for e in result.errors)

    def test_html_placeholder_detected(self) -> None:
        result = PlatformRule._check_placeholders("Some <placeholder> text here")
        assert result.is_valid is False

    def test_russian_placeholder_detected(self) -> None:
        result = PlatformRule._check_placeholders("Текст {заполнить} позже")
        assert result.is_valid is False

    def test_example_text_placeholder_detected(self) -> None:
        result = PlatformRule._check_placeholders(
            "\u041f\u0420\u0418\u041c\u0415\u0420 \u0422\u0415\u041a\u0421\u0422\u0410"
            " \u0434\u043b\u044f \u0437\u0430\u043f\u043e\u043b\u043d\u0435\u043d\u0438\u044f"
        )
        assert result.is_valid is False

    def test_case_insensitive_detection(self) -> None:
        result = PlatformRule._check_placeholders("lorem IPSUM dolor sit amet")
        assert result.is_valid is False

    def test_multiple_placeholders_all_detected(self) -> None:
        content = "[INSERT] and Lorem ipsum and TODO and [YOUR NAME]"
        result = PlatformRule._check_placeholders(content)
        assert result.is_valid is False
        assert len(result.errors) >= 4

    def test_all_patterns_covered(self) -> None:
        """Verify we have the right number of placeholder patterns."""
        assert len(PLACEHOLDER_PATTERNS) >= 7


# ---------------------------------------------------------------------------
# validate() — combines common + platform checks
# ---------------------------------------------------------------------------


class TestValidateCombined:
    def test_clean_content_no_platform_errors(self) -> None:
        rule = _TestRule()
        result = rule.validate("Clean article content.", "article")
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_placeholder_error_from_common_check(self) -> None:
        """Common check (placeholder) should be included in final result."""
        rule = _TestRule()
        result = rule.validate("[INSERT TEXT HERE]", "article")
        assert result.is_valid is False
        assert any("INSERT" in e for e in result.errors)

    def test_platform_errors_included(self) -> None:
        """Platform-specific errors should be included in final result."""
        rule = _TestRule(platform_errors=["Platform error"])
        result = rule.validate("Clean content.", "article")
        assert result.is_valid is False
        assert "Platform error" in result.errors

    def test_both_common_and_platform_errors_combined(self) -> None:
        """Both common placeholder errors and platform errors should appear."""
        rule = _TestRule(platform_errors=["Length too short"])
        result = rule.validate("Fix TODO and short", "article")
        assert result.is_valid is False
        assert any("TODO" in e for e in result.errors)
        assert "Length too short" in result.errors

    def test_warnings_combined(self) -> None:
        """Platform warnings should be included."""
        rule = _TestRule(platform_warnings=["Consider adding FAQ"])
        result = rule.validate("Clean text.", "article")
        assert result.is_valid is True
        assert "Consider adding FAQ" in result.warnings

    def test_is_valid_false_when_any_error(self) -> None:
        """is_valid should be False if total errors > 0."""
        rule = _TestRule(platform_errors=["err"])
        result = rule.validate("Clean text.", "article")
        assert result.is_valid is False

    def test_validate_passes_kwargs_to_platform(self) -> None:
        """title and has_image should be forwarded to _validate_platform."""

        class _RecordingRule(PlatformRule):
            captured_title: str = ""
            captured_has_image: bool = False

            def _validate_platform(
                self,
                content: str,
                content_type: str,
                *,
                title: str = "",
                has_image: bool = False,
            ) -> ValidationResult:
                self.captured_title = title
                self.captured_has_image = has_image
                return ValidationResult(is_valid=True)

        rule = _RecordingRule()
        rule.validate("content", "article", title="My Title", has_image=True)
        assert rule.captured_title == "My Title"
        assert rule.captured_has_image is True
