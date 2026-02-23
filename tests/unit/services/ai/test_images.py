"""Tests for services.ai.images — _flatten_image_settings."""

from __future__ import annotations

from services.ai.images import _flatten_image_settings


class TestFlattenImageSettings:
    """Unit tests for _flatten_image_settings helper."""

    def test_empty_settings(self) -> None:
        ctx = {"keyword": "test", "image_settings": {}}
        result = _flatten_image_settings(ctx)
        # No flat keys added — PromptEngine will use YAML defaults
        assert "style" not in result
        assert "tone" not in result

    def test_styles_first_element(self) -> None:
        ctx = {"image_settings": {"styles": ["Минимализм", "Реализм"]}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Минимализм"

    def test_tones_first_element(self) -> None:
        ctx = {"image_settings": {"tones": ["Тёплый", "Холодный"]}}
        result = _flatten_image_settings(ctx)
        assert result["tone"] == "Тёплый"

    def test_cameras_joined(self) -> None:
        ctx = {"image_settings": {"cameras": ["макро", "широкий угол"]}}
        result = _flatten_image_settings(ctx)
        assert result["camera_instruction"] == "Камера: макро, широкий угол."

    def test_text_on_image(self) -> None:
        ctx = {"image_settings": {"text_on_image": "Добавь логотип в угол"}}
        result = _flatten_image_settings(ctx)
        assert result["text_on_image_instruction"] == "Добавь логотип в угол"

    def test_no_image_settings_key(self) -> None:
        ctx = {"keyword": "test"}
        result = _flatten_image_settings(ctx)
        assert result["keyword"] == "test"
        assert "style" not in result

    def test_does_not_overwrite_explicit_style(self) -> None:
        """If caller already set 'style' in context, don't overwrite."""
        ctx = {"style": "Акварель", "image_settings": {"styles": ["Минимализм"]}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Акварель"

    def test_preserves_other_context_keys(self) -> None:
        ctx = {
            "keyword": "SEO",
            "company_name": "Acme",
            "image_settings": {"styles": ["Flat"]},
        }
        result = _flatten_image_settings(ctx)
        assert result["keyword"] == "SEO"
        assert result["company_name"] == "Acme"
        assert result["style"] == "Flat"

    def test_full_settings(self) -> None:
        ctx = {
            "keyword": "ремонт",
            "image_settings": {
                "styles": ["Фотореализм"],
                "tones": ["Профессиональный"],
                "cameras": ["портрет"],
                "text_on_image": "Без текста",
                "formats": ["16:9"],
                "count": 2,
            },
        }
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Фотореализм"
        assert result["tone"] == "Профессиональный"
        assert result["camera_instruction"] == "Камера: портрет."
        assert result["text_on_image_instruction"] == "Без текста"
        # image_settings still present for ImageService internal use
        assert "image_settings" in result

    def test_empty_lists_ignored(self) -> None:
        ctx = {"image_settings": {"styles": [], "tones": [], "cameras": []}}
        result = _flatten_image_settings(ctx)
        assert "style" not in result
        assert "tone" not in result
        assert "camera_instruction" not in result

    def test_legacy_flat_style_from_ui(self) -> None:
        """UI saves image_settings.style as flat string (not styles array)."""
        ctx = {"image_settings": {"style": "Минимализм"}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Минимализм"

    def test_legacy_flat_tone(self) -> None:
        ctx = {"image_settings": {"tone": "Тёплый"}}
        result = _flatten_image_settings(ctx)
        assert result["tone"] == "Тёплый"

    def test_styles_array_takes_priority_over_legacy(self) -> None:
        """If both styles[] and style exist, styles[] wins."""
        ctx = {"image_settings": {"styles": ["Акварель"], "style": "Минимализм"}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Акварель"

    def test_styles_as_string_not_list(self) -> None:
        """Handle edge case where styles is a string instead of list."""
        ctx = {"image_settings": {"styles": "Мультяшный"}}
        result = _flatten_image_settings(ctx)
        assert result["style"] == "Мультяшный"

    def test_tones_as_string_not_list(self) -> None:
        ctx = {"image_settings": {"tones": "Холодный"}}
        result = _flatten_image_settings(ctx)
        assert result["tone"] == "Холодный"
