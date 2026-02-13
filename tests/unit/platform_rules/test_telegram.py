"""Tests for platform_rules/telegram.py — Telegram content validation.

Covers: max 4096/1024, HTML tag whitelist, _find_unsupported_tags.
"""

from __future__ import annotations

from platform_rules.telegram import _TG_ALLOWED_TAGS, TelegramRule


def _rule() -> TelegramRule:
    return TelegramRule()


class TestTelegramTextLimits:
    def test_text_within_limit(self) -> None:
        content = "A" * 4096
        result = _rule().validate(content, "social_post", has_image=False)
        assert result.is_valid is True
        assert not any("4096" in e for e in result.errors)

    def test_text_exceeds_limit(self) -> None:
        content = "A" * 4097
        result = _rule().validate(content, "social_post", has_image=False)
        assert result.is_valid is False
        assert any("4096" in e for e in result.errors)

    def test_caption_within_limit(self) -> None:
        content = "A" * 1024
        result = _rule().validate(content, "social_post", has_image=True)
        assert result.is_valid is True

    def test_caption_exceeds_limit(self) -> None:
        content = "A" * 1025
        result = _rule().validate(content, "social_post", has_image=True)
        assert result.is_valid is False
        assert any("1024" in e for e in result.errors)

    def test_caption_limit_stricter_than_text(self) -> None:
        """Text between 1024 and 4096 should pass without image but fail with image."""
        content = "A" * 2000
        result_text = _rule().validate(content, "social_post", has_image=False)
        result_caption = _rule().validate(content, "social_post", has_image=True)
        assert result_text.is_valid is True
        assert result_caption.is_valid is False

    def test_empty_content_valid(self) -> None:
        result = _rule().validate("", "social_post")
        assert result.is_valid is True


class TestTelegramHtmlWhitelist:
    def test_allowed_tags_no_error(self) -> None:
        content = "<b>Bold</b> <i>Italic</i> <a href='#'>Link</a> <code>code</code>"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is True
        assert not any("HTML" in e for e in result.errors)

    def test_strong_em_allowed(self) -> None:
        content = "<strong>Strong</strong> <em>Emphasis</em>"
        result = _rule().validate(content, "social_post")
        assert not any("HTML" in e for e in result.errors)

    def test_unsupported_div_tag(self) -> None:
        content = "<div>Content</div>"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is False
        assert any("div" in e for e in result.errors)

    def test_unsupported_h1_tag(self) -> None:
        content = "<h1>Title</h1>"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is False
        assert any("h1" in e for e in result.errors)

    def test_unsupported_p_tag(self) -> None:
        content = "<p>Paragraph</p>"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is False
        assert any("p" in e.lower() for e in result.errors)

    def test_unsupported_img_tag(self) -> None:
        content = '<img src="photo.jpg">'
        result = _rule().validate(content, "social_post")
        assert result.is_valid is False

    def test_tg_spoiler_allowed(self) -> None:
        content = "<tg-spoiler>Hidden</tg-spoiler>"
        result = _rule().validate(content, "social_post")
        assert not any("tg-spoiler" in e for e in result.errors)

    def test_blockquote_allowed(self) -> None:
        content = "<blockquote>Quote</blockquote>"
        result = _rule().validate(content, "social_post")
        assert not any("blockquote" in e for e in result.errors)

    def test_multiple_unsupported_tags_listed(self) -> None:
        content = "<div>A</div><span>B</span><h2>C</h2>"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is False
        # div and h2 should be listed (span is allowed)
        error_text = " ".join(result.errors)
        assert "div" in error_text
        assert "h2" in error_text

    def test_closing_tags_not_false_positive(self) -> None:
        """Closing tags like </b> should not trigger errors."""
        content = "<b>Bold</b>"
        result = _rule().validate(content, "social_post")
        assert result.is_valid is True

    def test_pre_tag_allowed(self) -> None:
        content = "<pre>Code block</pre>"
        result = _rule().validate(content, "social_post")
        assert not any("pre" in e for e in result.errors)


class TestFindUnsupportedTags:
    def test_empty_returns_empty(self) -> None:
        result = TelegramRule._find_unsupported_tags("")
        assert result == set()

    def test_only_allowed_returns_empty(self) -> None:
        result = TelegramRule._find_unsupported_tags("<b>Bold</b><i>Italic</i>")
        assert result == set()

    def test_finds_unsupported(self) -> None:
        result = TelegramRule._find_unsupported_tags("<div>x</div><table>y</table>")
        assert result == {"div", "table"}

    def test_case_insensitive(self) -> None:
        result = TelegramRule._find_unsupported_tags("<DIV>x</DIV>")
        assert "div" in result


class TestAllowedTagsSet:
    def test_contains_core_formatting(self) -> None:
        for tag in ("b", "strong", "i", "em", "u", "ins", "s", "strike", "del"):
            assert tag in _TG_ALLOWED_TAGS

    def test_contains_link_and_code(self) -> None:
        for tag in ("a", "code", "pre"):
            assert tag in _TG_ALLOWED_TAGS

    def test_contains_tg_specific(self) -> None:
        assert "tg-spoiler" in _TG_ALLOWED_TAGS
        assert "tg-emoji" in _TG_ALLOWED_TAGS
        assert "blockquote" in _TG_ALLOWED_TAGS
