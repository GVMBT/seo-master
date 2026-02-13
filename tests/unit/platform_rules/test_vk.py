"""Tests for platform_rules/vk.py — VK content validation.

Covers: max 16384, HTML warning.
"""

from __future__ import annotations

from platform_rules.vk import VKRule


def _rule() -> VKRule:
    return VKRule()


class TestVKTextLimits:
    def test_within_limit(self) -> None:
        content = "A" * 16384
        result = _rule().validate(content, "social_post")
        assert result.is_valid is True
        assert result.errors == []

    def test_exceeds_limit(self) -> None:
        content = "A" * 16385
        result = _rule().validate(content, "social_post")
        assert result.is_valid is False
        assert any("16384" in e for e in result.errors)

    def test_short_text_valid(self) -> None:
        result = _rule().validate("Hello VK!", "social_post")
        assert result.is_valid is True

    def test_empty_text_valid(self) -> None:
        result = _rule().validate("", "social_post")
        assert result.is_valid is True

    def test_exactly_at_limit(self) -> None:
        content = "B" * 16384
        result = _rule().validate(content, "social_post")
        assert result.is_valid is True
        assert not any("VK" in e for e in result.errors)


class TestVKHtmlWarning:
    def test_no_html_no_warning(self) -> None:
        result = _rule().validate("Plain text without HTML", "social_post")
        assert result.warnings == []

    def test_html_tags_produce_warning(self) -> None:
        content = "<b>Bold</b> text for VK"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is True  # Warning is non-blocking
        assert any("HTML" in w for w in result.warnings)

    def test_h1_tag_produces_warning(self) -> None:
        content = "<h1>Title</h1>"
        result = _rule().validate(content, "social_post")
        assert any("HTML" in w for w in result.warnings)

    def test_self_closing_tag_produces_warning(self) -> None:
        content = '<img src="x.jpg" />'
        result = _rule().validate(content, "social_post")
        assert any("HTML" in w for w in result.warnings)

    def test_angle_brackets_in_math_no_crash(self) -> None:
        """Regex <[^>]+> may match math expressions -- verify no crash."""
        content = "The result is 5 > 3 and 2 < 4"
        _rule().validate(content, "social_post")
        # Known limitation: "< 4" may match as an HTML "tag"
        # VK warning is advisory only, so we just verify no crash

    def test_warning_does_not_block_validity(self) -> None:
        content = "<b>Bold</b> valid VK post"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is True
        assert len(result.warnings) > 0
