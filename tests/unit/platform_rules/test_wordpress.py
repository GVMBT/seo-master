"""Tests for platform_rules/wordpress.py — WordPress content validation.

Covers: min 500 chars, H2 check (H1 = post title), paragraph check, FAQ warning.
"""

from __future__ import annotations

from platform_rules.wordpress import WordPressRule


def _rule() -> WordPressRule:
    return WordPressRule()


# Valid WordPress article content (H1 is post title, content starts with H2)
_VALID = (
    "<h2>Complete SEO Guide</h2>"
    "<p>" + "A" * 60 + "</p>"
    "<p>" + "B" * 400 + "</p>"
    "<h2>FAQ</h2>"
    "<p>Frequently asked questions here.</p>"
)


class TestWordPressArticleValidation:
    def test_valid_article_no_errors(self) -> None:
        result = _rule().validate(_VALID, "article")
        assert result.is_valid is True
        assert result.errors == []

    def test_short_article_below_500(self) -> None:
        short = "<h2>Title</h2><p>Short text.</p>"
        result = _rule().validate(short, "article")
        assert result.is_valid is False
        assert any("500" in e for e in result.errors)

    def test_exactly_500_chars_no_length_error(self) -> None:
        # Build content exactly 500 chars
        prefix = "<h2>T</h2><p>"
        suffix = "</p>faq"
        fill = "X" * (500 - len(prefix) - len(suffix))
        content = prefix + fill + suffix
        assert len(content) == 500
        result = _rule().validate(content, "article")
        # No length error (may have paragraph error since fill < 50 visible)
        assert not any("слишком короткий" in e for e in result.errors)

    def test_missing_h2_error(self) -> None:
        content = "<p>" + "A" * 500 + "</p>"
        result = _rule().validate(content, "article")
        assert result.is_valid is False
        assert any("H2" in e for e in result.errors)

    def test_missing_long_paragraph_error(self) -> None:
        content = "<h2>Title</h2>" + "x" * 480 + "<p>Hi</p>faq"
        result = _rule().validate(content, "article")
        assert result.is_valid is False
        assert any("50 символов" in e for e in result.errors)

    def test_paragraph_with_50_chars_passes(self) -> None:
        content = "<h2>Title</h2><p>" + "Z" * 50 + "</p>" + "Q" * 400 + "faq"
        result = _rule().validate(content, "article")
        assert not any("50 символов" in e for e in result.errors)

    def test_faq_missing_warning(self) -> None:
        content = "<h2>Title</h2><p>" + "A" * 500 + "</p>"
        result = _rule().validate(content, "article")
        assert any("FAQ" in w for w in result.warnings)

    def test_faq_present_no_warning(self) -> None:
        result = _rule().validate(_VALID, "article")
        assert not any("FAQ" in w for w in result.warnings)

    def test_non_article_content_type_skips_checks(self) -> None:
        """social_post content type should not trigger WP article rules."""
        result = _rule().validate("Short text", "social_post")
        assert result.is_valid is True
        assert result.errors == []

    def test_multiple_errors_collected(self) -> None:
        """Short + no H2 + no paragraph should produce multiple errors."""
        content = "<p>Hi</p>"
        result = _rule().validate(content, "article")
        assert result.is_valid is False
        assert len(result.errors) >= 3

    def test_h2_with_attributes_detected(self) -> None:
        """<h2 class='title'> should be detected as H2."""
        content = '<h2 class="main-title">Title</h2><p>' + "A" * 500 + "</p>faq"
        result = _rule().validate(content, "article")
        assert not any("H2" in e for e in result.errors)
