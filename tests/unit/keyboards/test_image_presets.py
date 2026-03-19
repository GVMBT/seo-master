"""Tests for project-level image settings keyboards."""

from __future__ import annotations

from bot.texts.content_options import ASPECT_RATIOS, IMAGE_STYLES
from keyboards.inline import (
    project_article_format_kb,
    project_image_count_kb,
    project_image_menu_kb,
    project_image_style_kb,
    project_preview_format_kb,
)

# ---------------------------------------------------------------------------
# 1. project_image_menu_kb layout (2x5 grid)
# ---------------------------------------------------------------------------


def test_image_menu_has_all_sections() -> None:
    """Image menu must have all 9 sub-sections + back button."""
    kb = project_image_menu_kb(pid=10, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    texts = [btn.text for btn in buttons]
    assert "Стиль" in texts
    assert "Количество" in texts
    assert "Превью" in texts
    assert "Форматы" in texts
    assert "Камера" in texts
    assert "Ракурс" in texts
    assert "Качество" in texts
    assert "Тональность" in texts
    assert any("Текст" in t and "фото" in t for t in texts)
    assert "Назад" in texts


def test_image_menu_grid_layout() -> None:
    """Image menu must be a 2-column grid (5 rows of 2)."""
    kb = project_image_menu_kb(pid=10, target="d")
    for row in kb.inline_keyboard:
        assert len(row) == 2


def test_image_menu_platform_target() -> None:
    """Image menu with platform target must use correct callback prefix."""
    kb = project_image_menu_kb(pid=10, target="wordpress")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if btn.callback_data:
            assert "psettings:10:wordpress:" in btn.callback_data


# ---------------------------------------------------------------------------
# 2. project_preview_format_kb
# ---------------------------------------------------------------------------


def test_preview_format_shows_all_ratios() -> None:
    """Preview format keyboard must show all Gemini-supported aspect ratios."""
    kb = project_preview_format_kb(pid=10, current=None, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    ratio_buttons = [btn for btn in buttons if btn.callback_data and btn.callback_data.startswith("psettings:")]
    ratio_only = [btn for btn in ratio_buttons if ":pf:" in (btn.callback_data or "")]
    assert len(ratio_only) == len(ASPECT_RATIOS)


def test_preview_format_marks_current() -> None:
    """Current format must be marked with checkmark."""
    kb = project_preview_format_kb(pid=10, current="16:9", target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if "16:9" in btn.text:
            assert btn.text.startswith("\u2713 ")
            break
    else:
        raise AssertionError("16:9 button not found")


def test_preview_format_callback_data() -> None:
    """Callback data must follow psettings:{pid}:{target}:pf:{idx} format."""
    kb = project_preview_format_kb(pid=99, current=None, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    pf_buttons = [btn for btn in buttons if btn.callback_data and ":pf:" in btn.callback_data]
    assert len(pf_buttons) == len(ASPECT_RATIOS)
    for i, btn in enumerate(pf_buttons):
        assert btn.callback_data == f"psettings:99:d:pf:{i}"


# ---------------------------------------------------------------------------
# 3. project_article_format_kb (multi-select)
# ---------------------------------------------------------------------------


def test_article_format_marks_selected() -> None:
    """Selected formats must be marked with checkmark."""
    selected = {"1:1", "16:9"}
    kb = project_article_format_kb(pid=10, selected=selected, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if btn.callback_data and ":af:" in btn.callback_data and ("1:1" in btn.text or "16:9" in btn.text):
            assert btn.text.startswith("\u2713 ")


# ---------------------------------------------------------------------------
# 4. project_image_style_kb
# ---------------------------------------------------------------------------


def test_image_style_shows_all_styles() -> None:
    """Image style keyboard must show all 10 styles."""
    kb = project_image_style_kb(pid=10, selected=set(), target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    style_buttons = [btn for btn in buttons if btn.callback_data and ":is:" in (btn.callback_data or "")]
    assert len(style_buttons) == len(IMAGE_STYLES)


def test_image_style_marks_selected() -> None:
    """Selected styles must be marked with checkmark."""
    kb = project_image_style_kb(pid=10, selected={IMAGE_STYLES[0]}, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if btn.callback_data and ":is:0" in btn.callback_data:
            assert btn.text.startswith("\u2713 ")
            break
    else:
        raise AssertionError("First style button not found")


# ---------------------------------------------------------------------------
# 5. project_image_count_kb
# ---------------------------------------------------------------------------


def test_image_count_0_to_10() -> None:
    """Image count keyboard must offer 0-10 options."""
    kb = project_image_count_kb(pid=10, current=3, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    count_buttons = [btn for btn in buttons if btn.callback_data and ":ic:" in (btn.callback_data or "")]
    assert len(count_buttons) == 11


def test_image_count_marks_current() -> None:
    """Current count must be marked with checkmark."""
    kb = project_image_count_kb(pid=10, current=5, target="d")
    buttons = [btn for row in kb.inline_keyboard for btn in row]
    for btn in buttons:
        if btn.callback_data == "psettings:10:d:ic:5":
            assert btn.text.startswith("\u2713 ")
            break
    else:
        raise AssertionError("Count 5 button not found")


# ---------------------------------------------------------------------------
# 6. Content options data integrity
# ---------------------------------------------------------------------------


def test_aspect_ratios_count() -> None:
    """Must have exactly 10 Gemini-supported aspect ratios."""
    assert len(ASPECT_RATIOS) == 10


def test_image_styles_count() -> None:
    """Must have exactly 10 image styles."""
    assert len(IMAGE_STYLES) == 10
