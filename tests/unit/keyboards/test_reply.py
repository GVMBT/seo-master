"""Tests for keyboards/reply.py — main_menu_kb."""

from aiogram.types import ReplyKeyboardMarkup, ReplyKeyboardRemove

from keyboards.reply import BTN_ADMIN, main_menu_kb


class TestMainMenuKb:
    def test_non_admin_returns_remove(self) -> None:
        """Non-admin user: keyboard is removed (no persistent buttons)."""
        result = main_menu_kb(is_admin=False)
        assert isinstance(result, ReplyKeyboardRemove)

    def test_admin_has_admin_button(self) -> None:
        """Admin user: only 'Админка' button."""
        kb = main_menu_kb(is_admin=True)
        assert isinstance(kb, ReplyKeyboardMarkup)
        assert len(kb.keyboard) == 1
        assert kb.keyboard[0][0].text == BTN_ADMIN

    def test_default_is_non_admin(self) -> None:
        """Default is_admin=False → ReplyKeyboardRemove."""
        result = main_menu_kb()
        assert isinstance(result, ReplyKeyboardRemove)

    def test_admin_resize_keyboard_enabled(self) -> None:
        """resize_keyboard should be True for admin keyboard."""
        kb = main_menu_kb(is_admin=True)
        assert isinstance(kb, ReplyKeyboardMarkup)
        assert kb.resize_keyboard is True
