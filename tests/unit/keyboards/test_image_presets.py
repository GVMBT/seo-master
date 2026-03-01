"""Tests for image presets keyboard and recommend logic."""

from __future__ import annotations

import pytest

from keyboards.inline import image_custom_kb, image_presets_kb
from routers.categories.content_settings import (
    _IMAGE_PRESET_NAMES,
    _IMAGE_PRESETS,
    _recommend_preset,
)


# ---------------------------------------------------------------------------
# 1. image_presets_kb layout
# ---------------------------------------------------------------------------


def test_image_presets_kb_all_options() -> None:
    """Keyboard must have 5 presets + custom + stepper + back."""
    kb = image_presets_kb(
        cat_id=10,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset=None,
        recommended_idx=0,
        count=3,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]
    # 5 preset names (with possible marks)
    for name in _IMAGE_PRESET_NAMES:
        found = any(name in t for t in texts)
        assert found, f"Preset '{name}' not found in keyboard"
    # Custom button
    assert any("Свой вариант" in t for t in texts)
    # Stepper
    assert any("Количество:" in t for t in texts)
    # Back
    assert any("К настройкам" in t for t in texts)


def test_image_presets_kb_marks_current() -> None:
    """Current preset must be marked with checkmark."""
    kb = image_presets_kb(
        cat_id=10,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset="Lifestyle",
        recommended_idx=0,
        count=3,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if "Lifestyle" in btn.text:
            assert btn.text.startswith("\u2713 ")
            break
    else:
        pytest.fail("Lifestyle button not found")


def test_image_presets_kb_marks_recommended() -> None:
    """Recommended preset must be marked with star when no current is set."""
    kb = image_presets_kb(
        cat_id=10,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset=None,
        recommended_idx=2,
        count=3,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if _IMAGE_PRESET_NAMES[2] in btn.text:
            assert btn.text.startswith("\u2605 "), f"Expected star mark, got: {btn.text}"
            break
    else:
        pytest.fail("Recommended button not found")


def test_image_presets_kb_no_star_when_current_set() -> None:
    """Star must NOT appear when a current preset is already selected."""
    kb = image_presets_kb(
        cat_id=10,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset="Фотосток",
        recommended_idx=2,
        count=3,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    star_buttons = [btn for btn in buttons if btn.text.startswith("\u2605 ")]
    assert len(star_buttons) == 0


def test_image_presets_kb_stepper_value() -> None:
    """Stepper must show the provided count value."""
    kb = image_presets_kb(
        cat_id=10,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset=None,
        recommended_idx=0,
        count=7,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    count_btn = [btn for btn in buttons if "Количество:" in btn.text]
    assert len(count_btn) == 1
    assert "7" in count_btn[0].text


def test_image_presets_kb_callback_data_format() -> None:
    """Callback data must follow settings:{cat_id}:ip:{idx} format."""
    kb = image_presets_kb(
        cat_id=99,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset=None,
        recommended_idx=0,
        count=3,
    )
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    preset_buttons = [btn for btn in buttons if btn.callback_data and btn.callback_data.startswith("settings:99:ip:")]
    assert len(preset_buttons) == len(_IMAGE_PRESET_NAMES)
    for i, btn in enumerate(preset_buttons):
        assert btn.callback_data == f"settings:99:ip:{i}"


# ---------------------------------------------------------------------------
# 2. _recommend_preset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("niche", "expected_idx"),
    [
        ("realestate", 0),
        ("auto", 0),
        ("beauty", 2),
        ("food", 2),
        ("finance", 3),
        ("it", 3),
        ("children", 4),
        ("unknown_niche", 0),
        ("general", 0),
    ],
)
def test_recommend_preset_by_niche(niche: str, expected_idx: int) -> None:
    """_recommend_preset must return correct index for known niches."""
    assert _recommend_preset(niche) == expected_idx


# ---------------------------------------------------------------------------
# 3. Backward compatibility
# ---------------------------------------------------------------------------


def test_backward_compat_no_preset() -> None:
    """Keyboard works when no current preset is set (None)."""
    kb = image_presets_kb(
        cat_id=10,
        preset_names=_IMAGE_PRESET_NAMES,
        current_preset=None,
        recommended_idx=0,
        count=4,
    )
    # Should not crash, should have the star on index 0
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    first_preset = buttons[0]
    assert first_preset.text.startswith("\u2605 ")


# ---------------------------------------------------------------------------
# 4. image_custom_kb
# ---------------------------------------------------------------------------


def test_image_custom_kb_buttons() -> None:
    """Custom kb must have style button and back-to-presets."""
    kb = image_custom_kb(cat_id=10)
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]
    assert "Стиль изображений" in texts
    assert "К пресетам" in texts


# ---------------------------------------------------------------------------
# 5. Preset data integrity
# ---------------------------------------------------------------------------


def test_preset_names_list_matches_presets() -> None:
    """_IMAGE_PRESET_NAMES must match _IMAGE_PRESETS names."""
    assert _IMAGE_PRESET_NAMES == [p["name"] for p in _IMAGE_PRESETS]


def test_preset_count() -> None:
    """Must have exactly 5 presets."""
    assert len(_IMAGE_PRESETS) == 5


def test_preset_styles_are_valid() -> None:
    """Each preset style must be in _IMAGE_STYLES list."""
    from routers.categories.content_settings import _VALID_IMAGE_STYLES

    for p in _IMAGE_PRESETS:
        assert p["style"] in _VALID_IMAGE_STYLES, f"Preset '{p['name']}' has unknown style '{p['style']}'"
