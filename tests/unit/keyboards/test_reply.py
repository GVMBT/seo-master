"""Tests for keyboards/reply.py."""

from keyboards.reply import cancel_kb, main_menu, skip_cancel_kb


class TestMainMenu:
    def test_has_6_buttons_for_regular_user(self) -> None:
        kb = main_menu(is_admin=False)
        buttons = [btn.text for row in kb.keyboard for btn in row]
        assert len(buttons) == 6
        assert "АДМИНКА" not in buttons

    def test_has_admin_button_for_admin(self) -> None:
        kb = main_menu(is_admin=True)
        buttons = [btn.text for row in kb.keyboard for btn in row]
        assert "АДМИНКА" in buttons
        assert len(buttons) == 7

    def test_contains_all_menu_items(self) -> None:
        kb = main_menu()
        buttons = [btn.text for row in kb.keyboard for btn in row]
        for expected in ["Быстрая публикация", "Проекты", "Профиль", "Тарифы", "Настройки", "Помощь"]:
            assert expected in buttons

    def test_resize_keyboard_enabled(self) -> None:
        kb = main_menu()
        assert kb.resize_keyboard is True


class TestCancelKb:
    def test_has_single_cancel_button(self) -> None:
        kb = cancel_kb()
        buttons = [btn.text for row in kb.keyboard for btn in row]
        assert buttons == ["Отмена"]

    def test_one_time_keyboard(self) -> None:
        kb = cancel_kb()
        assert kb.one_time_keyboard is True


class TestSkipCancelKb:
    def test_has_skip_and_cancel(self) -> None:
        kb = skip_cancel_kb()
        buttons = [btn.text for row in kb.keyboard for btn in row]
        assert "Пропустить" in buttons
        assert "Отмена" in buttons
        assert len(buttons) == 2
