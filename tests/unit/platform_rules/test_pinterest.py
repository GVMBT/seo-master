"""Tests for platform_rules/pinterest.py — Pinterest content validation.

Covers: max 500 description, max 100 title, image required.
"""

from __future__ import annotations

from platform_rules.pinterest import PinterestRule


def _rule() -> PinterestRule:
    return PinterestRule()


class TestPinterestDescriptionLimit:
    def test_within_limit(self) -> None:
        content = "A" * 500
        result = _rule().validate(content, "social_post", has_image=True)
        assert result.is_valid is True
        assert not any("500" in e for e in result.errors)

    def test_exceeds_limit(self) -> None:
        content = "A" * 501
        result = _rule().validate(content, "social_post", has_image=True)
        assert result.is_valid is False
        assert any("Pinterest" in e and "500" in e for e in result.errors)

    def test_empty_description_valid(self) -> None:
        result = _rule().validate("", "social_post", has_image=True)
        assert result.is_valid is True

    def test_short_description_valid(self) -> None:
        result = _rule().validate("Beautiful pin!", "social_post", has_image=True)
        assert result.is_valid is True


class TestPinterestTitleLimit:
    def test_title_within_limit(self) -> None:
        result = _rule().validate("desc", "social_post", title="A" * 100, has_image=True)
        assert not any("100" in e for e in result.errors)

    def test_title_exceeds_limit(self) -> None:
        result = _rule().validate("desc", "social_post", title="A" * 101, has_image=True)
        assert result.is_valid is False
        assert any("Pinterest" in e and "100" in e for e in result.errors)

    def test_empty_title_no_error(self) -> None:
        """Empty title should not trigger title length error."""
        result = _rule().validate("desc", "social_post", title="", has_image=True)
        assert not any("100" in e for e in result.errors)

    def test_no_title_no_error(self) -> None:
        """Default empty title should not trigger error."""
        result = _rule().validate("desc", "social_post", has_image=True)
        assert not any("Заголовок" in e for e in result.errors)


class TestPinterestImageRequired:
    def test_with_image_no_error(self) -> None:
        result = _rule().validate("desc", "social_post", has_image=True)
        assert result.is_valid is True
        assert not any("изображение" in e for e in result.errors)

    def test_without_image_error(self) -> None:
        result = _rule().validate("desc", "social_post", has_image=False)
        assert result.is_valid is False
        assert any("изображение" in e for e in result.errors)

    def test_default_no_image_error(self) -> None:
        """Default has_image=False should produce error."""
        result = _rule().validate("desc", "social_post")
        assert result.is_valid is False
        assert any("изображение" in e for e in result.errors)


class TestPinterestMultipleErrors:
    def test_long_desc_no_image_both_errors(self) -> None:
        content = "A" * 600
        result = _rule().validate(content, "social_post", has_image=False)
        assert result.is_valid is False
        assert len(result.errors) >= 2

    def test_long_title_long_desc_no_image_three_errors(self) -> None:
        content = "A" * 600
        result = _rule().validate(content, "social_post", title="T" * 200, has_image=False)
        assert result.is_valid is False
        assert len(result.errors) >= 3

    def test_valid_pin_all_constraints_met(self) -> None:
        result = _rule().validate("Beautiful pin", "social_post", title="My Pin", has_image=True)
        assert result.is_valid is True
        assert result.errors == []
