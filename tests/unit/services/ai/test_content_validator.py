"""Tests for services/ai/content_validator.py — content validation before publishing.

Covers: placeholder detection, minimum length, WordPress structure checks,
platform-specific length limits, FAQ warnings, multiple error collection.
"""

from __future__ import annotations

from services.ai.content_validator import (
    PLACEHOLDER_PATTERNS,
    PLATFORM_LIMITS,
    ContentValidator,
    ValidationResult,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ARTICLE_CONTENT = (
    "<h2>SEO Guide for Beginners</h2>"
    "<p>" + "A" * 60 + "</p>"
    "<p>" + "B" * 400 + "</p>"
    "<h2>FAQ</h2>"
    "<p>Question and answer section here with enough text.</p>"
)

VALID_SOCIAL_POST = "Check out our new article about SEO best practices! #seo #marketing"


def _validator() -> ContentValidator:
    return ContentValidator()


# ---------------------------------------------------------------------------
# ValidationResult dataclass
# ---------------------------------------------------------------------------


class TestValidationResultDefaults:
    def test_defaults_empty_lists(self) -> None:
        result = ValidationResult(is_valid=True)
        assert result.errors == []
        assert result.warnings == []

    def test_is_valid_flag(self) -> None:
        result = ValidationResult(is_valid=False, errors=["err"])
        assert result.is_valid is False
        assert result.errors == ["err"]


# ---------------------------------------------------------------------------
# Constants verification
# ---------------------------------------------------------------------------


class TestConstants:
    def test_placeholder_patterns_count(self) -> None:
        assert len(PLACEHOLDER_PATTERNS) >= 7

    def test_platform_limits_keys(self) -> None:
        assert "telegram" in PLATFORM_LIMITS
        assert "vk" in PLATFORM_LIMITS
        assert "pinterest" in PLATFORM_LIMITS
        assert "wordpress" in PLATFORM_LIMITS


# ---------------------------------------------------------------------------
# Valid content — no errors
# ---------------------------------------------------------------------------


class TestValidContent:
    def test_valid_article_wordpress_is_valid(self) -> None:
        v = _validator()
        result = v.validate(VALID_ARTICLE_CONTENT, "article", "wordpress")
        assert result.is_valid is True
        assert result.errors == []

    def test_valid_social_post_telegram_no_errors(self) -> None:
        v = _validator()
        result = v.validate(VALID_SOCIAL_POST, "social_post", "telegram")
        assert result.is_valid is True
        assert result.errors == []

    def test_valid_social_post_vk_no_errors(self) -> None:
        v = _validator()
        result = v.validate(VALID_SOCIAL_POST, "social_post", "vk")
        assert result.is_valid is True
        assert result.errors == []

    def test_valid_social_post_pinterest_no_errors(self) -> None:
        v = _validator()
        short_post = "Beautiful pin about SEO trends"
        result = v.validate(short_post, "social_post", "pinterest")
        assert result.is_valid is True
        assert result.errors == []


# ---------------------------------------------------------------------------
# Placeholder detection
# ---------------------------------------------------------------------------


class TestPlaceholderDetection:
    def test_insert_placeholder_detected_error(self) -> None:
        v = _validator()
        content = "<h2>Title</h2><p>" + "A" * 500 + " [INSERT KEYWORD HERE]</p><h2>faq</h2>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        assert any("INSERT" in e for e in result.errors)

    def test_lorem_ipsum_detected_error(self) -> None:
        v = _validator()
        content = "<h2>Title</h2><p>" + "A" * 500 + " Lorem ipsum dolor sit amet</p><h2>faq</h2>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        assert any("Lorem ipsum" in e for e in result.errors)

    def test_todo_placeholder_detected_error(self) -> None:
        v = _validator()
        content = "Great post about TODO items in marketing"
        result = v.validate(content, "social_post", "telegram")
        assert result.is_valid is False
        assert any("TODO" in e for e in result.errors)

    def test_todo_inside_word_not_detected(self) -> None:
        """\\bTODO\\b uses word boundary — 'TODOLIST' should not match."""
        v = _validator()
        # "TODOLIST" does not match \bTODO\b because L follows TODO without boundary
        content = "Check TODOLIST for updates"
        result = v.validate(content, "social_post", "telegram")
        # "TODO" pattern uses \b — "TODOLIST" should not trigger
        # Actually \bTODO\b won't match TODOLIST since L is a word char
        assert result.is_valid is True

    def test_your_placeholder_detected_error(self) -> None:
        v = _validator()
        content = "Welcome to [YOUR COMPANY] website"
        result = v.validate(content, "social_post", "telegram")
        assert result.is_valid is False
        assert any("YOUR" in e for e in result.errors)

    def test_html_placeholder_detected_error(self) -> None:
        v = _validator()
        content = "<h2>Title</h2><p>" + "A" * 500 + " <placeholder> text</p><h2>faq</h2>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        assert any("placeholder" in e for e in result.errors)

    def test_russian_placeholder_detected_error(self) -> None:
        v = _validator()
        content = "Текст для сайта {заполнить} потом"
        result = v.validate(content, "social_post", "vk")
        assert result.is_valid is False

    def test_example_text_placeholder_detected_error(self) -> None:
        v = _validator()
        content = "Вот ПРИМЕР ТЕКСТА для публикации"
        result = v.validate(content, "social_post", "vk")
        assert result.is_valid is False

    def test_placeholder_case_insensitive(self) -> None:
        """Placeholder patterns are checked with re.IGNORECASE."""
        v = _validator()
        content = "lorem Ipsum dolor sit amet in this post"
        result = v.validate(content, "social_post", "telegram")
        assert result.is_valid is False
        assert any("Lorem ipsum" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Article minimum length
# ---------------------------------------------------------------------------


class TestArticleMinimumLength:
    def test_article_below_500_chars_error(self) -> None:
        v = _validator()
        short_content = "<h2>Hi</h2><p>Short</p>"
        result = v.validate(short_content, "article", "wordpress")
        assert result.is_valid is False
        assert any("500" in e for e in result.errors)

    def test_article_exactly_500_chars_no_length_error(self) -> None:
        v = _validator()
        # Build content that is exactly 500 chars with required structure
        filler = "X" * (500 - len("<h2>T</h2><p>") - len("</p>faq"))
        content = "<h2>T</h2><p>" + filler + "</p>faq"
        assert len(content) == 500
        result = v.validate(content, "article", "wordpress")
        # Should not have length error (but may have structure errors)
        assert not any("слишком короткий" in e for e in result.errors)

    def test_social_post_short_no_length_error(self) -> None:
        """Min length check only applies to articles, not social posts."""
        v = _validator()
        result = v.validate("Hi!", "social_post", "telegram")
        assert not any("500" in e for e in result.errors)


# ---------------------------------------------------------------------------
# WordPress article structure
# ---------------------------------------------------------------------------


class TestWordPressStructure:
    def test_wordpress_article_without_h2_error(self) -> None:
        v = _validator()
        content = "<p>" + "A" * 500 + "</p>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        assert any("H2" in e for e in result.errors)

    def test_wordpress_article_without_long_paragraph_error(self) -> None:
        v = _validator()
        # <p> near end with <50 chars after it, so regex <p[^>]*>.{50,} won't match
        content = "<h2>Section</h2>" + "x" * 480 + "<p>Hi</p>faq"
        assert len(content) >= 500
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        assert any("50" in e for e in result.errors)

    def test_wordpress_article_with_h2_and_paragraph_no_structure_errors(self) -> None:
        v = _validator()
        result = v.validate(VALID_ARTICLE_CONTENT, "article", "wordpress")
        assert not any("H2" in e for e in result.errors)
        assert not any("50 символов" in e for e in result.errors)

    def test_non_wordpress_article_no_structure_check(self) -> None:
        """WordPress structure checks should not apply to other platforms."""
        v = _validator()
        content = "A" * 600 + " faq"  # No <h2>, no <p> — but not wordpress
        result = v.validate(content, "article", "telegram")
        assert not any("H2" in e for e in result.errors)
        assert not any("50 символов" in e for e in result.errors)

    def test_non_article_wordpress_no_structure_check(self) -> None:
        """WordPress structure checks apply only to articles."""
        v = _validator()
        result = v.validate("Short post", "social_post", "wordpress")
        assert not any("H2" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Platform-specific length limits
# ---------------------------------------------------------------------------


class TestPlatformLengthLimits:
    def test_telegram_post_over_4096_error(self) -> None:
        v = _validator()
        long_content = "A" * 4097
        result = v.validate(long_content, "social_post", "telegram")
        assert result.is_valid is False
        assert any("Telegram" in e and "4096" in e for e in result.errors)

    def test_telegram_post_exactly_4096_no_error(self) -> None:
        v = _validator()
        content = "A" * 4096
        result = v.validate(content, "social_post", "telegram")
        assert not any("Telegram" in e for e in result.errors)

    def test_vk_post_over_16384_error(self) -> None:
        v = _validator()
        long_content = "A" * 16385
        result = v.validate(long_content, "social_post", "vk")
        assert result.is_valid is False
        assert any("VK" in e and "16384" in e for e in result.errors)

    def test_vk_post_exactly_16384_no_error(self) -> None:
        v = _validator()
        content = "A" * 16384
        result = v.validate(content, "social_post", "vk")
        assert not any("VK" in e for e in result.errors)

    def test_pinterest_post_over_500_error(self) -> None:
        v = _validator()
        long_content = "A" * 501
        result = v.validate(long_content, "social_post", "pinterest")
        assert result.is_valid is False
        assert any("Pinterest" in e and "500" in e for e in result.errors)

    def test_pinterest_post_exactly_500_no_error(self) -> None:
        v = _validator()
        content = "A" * 500
        result = v.validate(content, "social_post", "pinterest")
        assert not any("Pinterest" in e for e in result.errors)

    def test_telegram_article_over_4096_no_platform_error(self) -> None:
        """Platform length check applies only to social_post content_type."""
        v = _validator()
        content = "<h2>T</h2><p>" + "A" * 5000 + "</p>faq"
        result = v.validate(content, "article", "telegram")
        assert not any("Telegram" in e for e in result.errors)


# ---------------------------------------------------------------------------
# FAQ warning
# ---------------------------------------------------------------------------


class TestFAQWarning:
    def test_article_without_faq_warning(self) -> None:
        v = _validator()
        content = "<h2>Title</h2><p>" + "A" * 500 + "</p>"
        result = v.validate(content, "article", "wordpress")
        assert any("FAQ" in w for w in result.warnings)
        # Warning is non-blocking — should not cause is_valid=False by itself
        # (may still be invalid due to structure errors)

    def test_article_with_faq_no_warning(self) -> None:
        v = _validator()
        result = v.validate(VALID_ARTICLE_CONTENT, "article", "wordpress")
        assert not any("FAQ" in w for w in result.warnings)

    def test_article_with_faq_case_insensitive(self) -> None:
        """FAQ check is case-insensitive ('faq' in content.lower())."""
        v = _validator()
        content = "<h2>Title</h2><p>" + "A" * 500 + "</p><h2>FAQ Section</h2>"
        result = v.validate(content, "article", "wordpress")
        assert not any("FAQ" in w for w in result.warnings)

    def test_social_post_no_faq_warning(self) -> None:
        """FAQ warning only applies to articles."""
        v = _validator()
        result = v.validate(VALID_SOCIAL_POST, "social_post", "telegram")
        assert result.warnings == []

    def test_faq_warning_does_not_affect_validity(self) -> None:
        """Warnings are non-blocking: is_valid should still be True."""
        v = _validator()
        # Valid article structure, no placeholders, but no FAQ
        content = "<h2>Title</h2><p>" + "A" * 500 + "</p>"
        result = v.validate(content, "article", "wordpress")
        # Has warning but no errors
        assert result.is_valid is True
        assert len(result.warnings) > 0


# ---------------------------------------------------------------------------
# Multiple errors collected
# ---------------------------------------------------------------------------


class TestMultipleErrors:
    def test_short_article_with_placeholder_collects_both(self) -> None:
        v = _validator()
        # Short (<500) + placeholder ([INSERT) + no H1 + no long paragraph
        content = "<p>[INSERT something] short text</p>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        assert len(result.errors) >= 2
        has_length_error = any("500" in e for e in result.errors)
        has_placeholder_error = any("INSERT" in e for e in result.errors)
        assert has_length_error
        assert has_placeholder_error

    def test_all_wordpress_structure_errors_collected(self) -> None:
        v = _validator()
        # No H2, no long paragraph, short
        content = "<p>Short</p>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False
        # Should have: short + no H2 + no paragraph >= 50
        assert len(result.errors) >= 3

    def test_errors_and_warnings_independent(self) -> None:
        v = _validator()
        # Valid structure but has placeholder + no FAQ
        content = "<h2>Title</h2><p>" + "A" * 500 + " [INSERT KEYWORD]</p>"
        result = v.validate(content, "article", "wordpress")
        assert result.is_valid is False  # has error
        assert len(result.errors) >= 1
        assert any("FAQ" in w for w in result.warnings)  # also has warning


# ---------------------------------------------------------------------------
# validate_images_meta (API_CONTRACTS.md §3.7)
# ---------------------------------------------------------------------------


class TestValidateImagesMeta:
    def test_valid_images_meta_all_correct(self) -> None:
        """All fields valid, main_phrase in alt -> is_valid=True, no errors."""
        v = _validator()
        meta = [
            {"alt": "SEO guide for beginners", "filename": "seo-guide-for-beginners", "figcaption": "Caption"},
            {"alt": "SEO tips and tricks", "filename": "seo-tips-and-tricks", "figcaption": "Caption 2"},
        ]
        result = v.validate_images_meta(meta, expected_count=2, main_phrase="SEO")
        assert result.is_valid is True
        assert result.errors == []

    def test_empty_alt_is_error(self) -> None:
        """Empty alt text produces an error."""
        v = _validator()
        meta = [{"alt": "", "filename": "valid-slug", "figcaption": "Cap"}]
        result = v.validate_images_meta(meta, expected_count=1, main_phrase="keyword")
        assert result.is_valid is False
        assert any("alt is empty" in e for e in result.errors)

    def test_invalid_filename_slug_is_error(self) -> None:
        """Filename with uppercase / spaces / special chars is invalid slug."""
        v = _validator()
        meta = [{"alt": "Good keyword alt", "filename": "Bad Slug!", "figcaption": "Cap"}]
        result = v.validate_images_meta(meta, expected_count=1, main_phrase="keyword")
        assert result.is_valid is False
        assert any("valid slug" in e for e in result.errors)

    def test_count_mismatch_is_warning(self) -> None:
        """images_meta count != expected_count -> warning (not error)."""
        v = _validator()
        meta = [{"alt": "Good keyword alt", "filename": "good-keyword-slug", "figcaption": "Cap"}]
        result = v.validate_images_meta(meta, expected_count=3, main_phrase="keyword")
        assert result.is_valid is True
        assert any("count" in w for w in result.warnings)

    def test_alt_missing_main_phrase_is_warning(self) -> None:
        """Alt text without main_phrase -> warning (not error)."""
        v = _validator()
        meta = [{"alt": "Beautiful image of nature", "filename": "nature-photo", "figcaption": "Cap"}]
        result = v.validate_images_meta(meta, expected_count=1, main_phrase="SEO guide")
        assert result.is_valid is True
        assert any("main_phrase" in w for w in result.warnings)
