"""Tests for keyboards/inline.py — delete account keyboards."""

from keyboards.inline import delete_account_cancelled_kb, delete_account_confirm_kb


class TestDeleteAccountConfirmKb:
    def test_has_confirm_and_cancel_buttons(self) -> None:
        """Keyboard has confirm (DANGER) and cancel buttons."""
        kb = delete_account_confirm_kb()
        buttons = [btn for row in kb.inline_keyboard for btn in row]

        callbacks = [b.callback_data for b in buttons]
        assert "account:delete:confirm" in callbacks
        assert "account:delete:cancel" in callbacks

    def test_confirm_button_text(self) -> None:
        """Confirm button has Russian text."""
        kb = delete_account_confirm_kb()
        confirm_btn = kb.inline_keyboard[0][0]
        assert "удалить" in confirm_btn.text.lower()

    def test_two_rows(self) -> None:
        """Two rows: confirm and cancel."""
        kb = delete_account_confirm_kb()
        assert len(kb.inline_keyboard) == 2


class TestDeleteAccountCancelledKb:
    def test_has_profile_nav(self) -> None:
        """Cancelled keyboard navigates back to profile."""
        kb = delete_account_cancelled_kb()
        buttons = [btn for row in kb.inline_keyboard for btn in row]

        callbacks = [b.callback_data for b in buttons]
        assert "nav:profile" in callbacks
