"""Tests for keyboards/reply.py — main_menu_kb."""

from keyboards.reply import BTN_ADMIN, BTN_MENU, main_menu_kb


class TestMainMenuKb:
    def test_non_admin_has_one_row(self) -> None:
        """Non-admin user: only 'Меню' button."""
        kb = main_menu_kb(is_admin=False)
        assert len(kb.keyboard) == 1
        assert kb.keyboard[0][0].text == BTN_MENU

    def test_admin_has_two_rows(self) -> None:
        """Admin user: 'Меню' + 'Админка' buttons."""
        kb = main_menu_kb(is_admin=True)
        assert len(kb.keyboard) == 2
        assert kb.keyboard[0][0].text == BTN_MENU
        assert kb.keyboard[1][0].text == BTN_ADMIN

    def test_default_is_non_admin(self) -> None:
        """Default is_admin=False."""
        kb = main_menu_kb()
        assert len(kb.keyboard) == 1

    def test_resize_keyboard_enabled(self) -> None:
        """resize_keyboard should be True."""
        kb = main_menu_kb()
        assert kb.resize_keyboard is True
