"""Tests for keyboards/help.py — help system keyboard builders."""

from keyboards.help import (
    help_back_kb,
    help_main_kb,
)


def _get_buttons(builder):  # type: ignore[no-untyped-def]
    """Extract flat list of (text, callback_data) from builder."""
    markup = builder.as_markup()
    return [(btn.text, btn.callback_data) for row in markup.inline_keyboard for btn in row]


class TestHelpMainKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(help_main_kb())
        assert len(btns) == 5
        callbacks = [b[1] for b in btns]
        assert "help:connect" in callbacks
        assert "help:project" in callbacks
        assert "help:category" in callbacks
        assert "help:publish" in callbacks
        assert "menu:main" in callbacks


class TestHelpBackKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(help_back_kb())
        assert len(btns) == 2
        assert btns[0][1] == "help:main"
        assert btns[1][1] == "menu:main"
