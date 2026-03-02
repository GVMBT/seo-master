"""Tests for admin keyboard builders."""

from keyboards.inline import admin_panel_kb, user_actions_kb


class TestAdminPanelKb:
    def test_contains_api_status_button(self) -> None:
        kb = admin_panel_kb()
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in flat]
        assert "Статус API" in texts

    def test_no_old_monitoring_button(self) -> None:
        kb = admin_panel_kb()
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in flat]
        assert "Мониторинг" not in texts

    def test_api_status_callback_data(self) -> None:
        kb = admin_panel_kb()
        flat = [btn for row in kb.inline_keyboard for btn in row]
        cbs = [btn.callback_data for btn in flat]
        assert "admin:api_status" in cbs


class TestUserActionsKb:
    def test_contains_credit_debit_buttons(self) -> None:
        kb = user_actions_kb(123, is_blocked=False)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in flat]
        assert "Начислить" in texts
        assert "Списать" in texts

    def test_shows_block_for_active_user(self) -> None:
        kb = user_actions_kb(123, is_blocked=False)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in flat]
        assert "Заблокировать" in texts
        assert "Разблокировать" not in texts

    def test_shows_unblock_for_blocked_user(self) -> None:
        kb = user_actions_kb(123, is_blocked=True)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        texts = [btn.text for btn in flat]
        cbs = [btn.callback_data for btn in flat]
        assert "Разблокировать" in texts
        assert "Заблокировать" not in texts
        assert "admin:user:123:unblock" in cbs

    def test_callback_data_contains_user_id(self) -> None:
        kb = user_actions_kb(456, is_blocked=False)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        cbs = [btn.callback_data for btn in flat]
        assert "admin:user:456:credit" in cbs
        assert "admin:user:456:debit" in cbs
        assert "admin:user:456:block" in cbs
        assert "admin:user:456:activity" in cbs

    def test_has_back_to_panel_button(self) -> None:
        kb = user_actions_kb(123, is_blocked=False)
        flat = [btn for row in kb.inline_keyboard for btn in row]
        cbs = [btn.callback_data for btn in flat]
        assert "admin:panel" in cbs
