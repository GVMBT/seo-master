"""Tests for services/ai/social_posts.py — Pinterest limits & truncation.

Covers:
- _enforce_pinterest_limits: text truncation, hashtag limit, title fallback
- _truncate_at_boundary: sentence/word boundary truncation
"""

from __future__ import annotations

from services.ai.social_posts import (
    _enforce_pinterest_limits,
    _truncate_at_boundary,
)

# ---------------------------------------------------------------------------
# _truncate_at_boundary
# ---------------------------------------------------------------------------


class TestTruncateAtBoundary:
    def test_short_text_unchanged(self) -> None:
        """Text within limit is returned as-is."""
        assert _truncate_at_boundary("Hello world", 100) == "Hello world"

    def test_truncate_at_sentence_boundary(self) -> None:
        """Truncates at last period within limit."""
        text = "First sentence. Second sentence. Third sentence that overflows."
        result = _truncate_at_boundary(text, 35)
        # "First sentence. Second sentence." = 32 chars, fits in 35
        assert result == "First sentence. Second sentence."

    def test_truncate_at_word_boundary_no_period(self) -> None:
        """Text without periods truncates at word boundary + ellipsis, within limit."""
        text = "This is a long text without any periods that keeps going on and on"
        result = _truncate_at_boundary(text, 40)
        assert result.endswith("...")
        assert len(result) <= 40  # strict: result fits within limit

    def test_word_boundary_result_within_limit(self) -> None:
        """Ellipsis included, total length must not exceed limit."""
        text = "word " * 100  # 500 chars
        for limit in (10, 50, 100, 200):
            result = _truncate_at_boundary(text, limit)
            assert len(result) <= limit, f"limit={limit}, got len={len(result)}"

    def test_truncate_at_newline_boundary(self) -> None:
        """Truncates at newline when no suitable period exists."""
        text = "First line with enough text to fill\nSecond line continues here on and on"
        result = _truncate_at_boundary(text, 40)
        assert result == "First line with enough text to fill"

    def test_hard_cut_when_no_boundary(self) -> None:
        """Falls back to hard cut with ellipsis when no good boundary."""
        text = "A" * 200
        result = _truncate_at_boundary(text, 50)
        assert len(result) == 50
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# _enforce_pinterest_limits: text truncation
# ---------------------------------------------------------------------------


class TestPinterestTextTruncation:
    def test_text_within_limit_unchanged(self) -> None:
        """Text under 500 chars is not truncated."""
        content = {"text": "Short post", "hashtags": [], "pin_title": "Title"}
        _enforce_pinterest_limits(content)
        assert content["text"] == "Short post"

    def test_text_truncation_at_sentence(self) -> None:
        """Text 600 chars truncates at last period within 500."""
        # Build text: sentences that overflow 500 chars
        sentences = []
        char_count = 0
        i = 0
        while char_count < 600:
            sentence = f"Sentence number {i} with some filler text."
            sentences.append(sentence)
            char_count += len(sentence) + 1  # +1 for space
            i += 1
        text = " ".join(sentences)
        assert len(text) > 500  # Verify setup

        content = {"text": text, "hashtags": [], "pin_title": "Title"}
        _enforce_pinterest_limits(content)

        assert len(content["text"]) <= 500
        assert content["text"].endswith(".")

    def test_text_truncation_no_period(self) -> None:
        """Text without periods truncates at space + ellipsis."""
        text = " ".join(["word"] * 200)  # ~999 chars
        assert len(text) > 500

        content = {"text": text, "hashtags": [], "pin_title": "Title"}
        _enforce_pinterest_limits(content)

        # Should be truncated with "..." at word boundary
        assert len(content["text"]) <= 503  # 500 + "..."
        assert content["text"].endswith("...")


# ---------------------------------------------------------------------------
# _enforce_pinterest_limits: hashtag limit
# ---------------------------------------------------------------------------


class TestPinterestHashtagLimit:
    def test_hashtags_over_limit_truncated(self) -> None:
        """8 hashtags limited to 5."""
        content = {
            "text": "Post text",
            "hashtags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8"],
            "pin_title": "Title",
        }
        _enforce_pinterest_limits(content)
        assert len(content["hashtags"]) == 5
        assert content["hashtags"] == ["tag1", "tag2", "tag3", "tag4", "tag5"]

    def test_hashtags_within_limit_unchanged(self) -> None:
        """3 hashtags stays unchanged."""
        content = {
            "text": "Post text",
            "hashtags": ["tag1", "tag2", "tag3"],
            "pin_title": "Title",
        }
        _enforce_pinterest_limits(content)
        assert len(content["hashtags"]) == 3

    def test_exactly_five_hashtags_unchanged(self) -> None:
        """Exactly 5 hashtags stays unchanged."""
        content = {
            "text": "Post text",
            "hashtags": ["a", "b", "c", "d", "e"],
            "pin_title": "Title",
        }
        _enforce_pinterest_limits(content)
        assert len(content["hashtags"]) == 5


# ---------------------------------------------------------------------------
# _enforce_pinterest_limits: title
# ---------------------------------------------------------------------------


class TestPinterestTitle:
    def test_title_over_limit_truncated(self) -> None:
        """Title 150 chars truncated — shorter than original."""
        title = " ".join(["longword"] * 25)  # ~224 chars
        assert len(title) > 100

        content = {"text": "Post text", "hashtags": [], "pin_title": title}
        _enforce_pinterest_limits(content)

        # _truncate_at_boundary may add "..." at word boundary, result is
        # significantly shorter than original (within ~limit + 3)
        assert len(content["pin_title"]) < len(title)
        assert len(content["pin_title"]) <= 103  # limit(100) + "..."

    def test_title_within_limit_unchanged(self) -> None:
        """Title under 100 chars is not changed."""
        content = {"text": "Post text", "hashtags": [], "pin_title": "Short title"}
        _enforce_pinterest_limits(content)
        assert content["pin_title"] == "Short title"

    def test_empty_title_fallback_short_text(self) -> None:
        """Empty pin_title with short text uses text as title."""
        content = {"text": "Very short text", "hashtags": [], "pin_title": ""}
        _enforce_pinterest_limits(content)
        assert content["pin_title"] == "Very short text"

    def test_empty_title_fallback_long_text(self) -> None:
        """Empty pin_title with long text uses text[:97]+'...' style fallback."""
        text = " ".join(["word"] * 50)  # ~249 chars, well over 100
        assert len(text) > 100

        content = {"text": text, "hashtags": [], "pin_title": ""}
        _enforce_pinterest_limits(content)

        # Should have a title truncated from text + "..."
        assert content["pin_title"].endswith("...")
        assert len(content["pin_title"]) <= 100
