"""Tests for keyboards/admin.py — admin panel keyboard builders."""

from keyboards.admin import (
    admin_broadcast_audience_kb,
    admin_broadcast_confirm_kb,
    admin_dashboard_kb,
)


def _get_buttons(builder):  # type: ignore[no-untyped-def]
    """Extract flat list of (text, callback_data) from builder."""
    markup = builder.as_markup()
    return [(btn.text, btn.callback_data) for row in markup.inline_keyboard for btn in row]


class TestAdminDashboardKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(admin_dashboard_kb())
        assert len(btns) == 4
        callbacks = [b[1] for b in btns]
        assert "admin:monitoring" in callbacks
        assert "admin:broadcast" in callbacks
        assert "admin:costs" in callbacks
        assert "menu:main" in callbacks


class TestAdminBroadcastAudienceKb:
    def test_buttons(self) -> None:
        btns = _get_buttons(admin_broadcast_audience_kb())
        assert len(btns) == 5
        callbacks = [b[1] for b in btns]
        assert "admin:bc:all" in callbacks
        assert "admin:bc:active_7d" in callbacks


class TestAdminBroadcastConfirmKb:
    def test_count_in_label(self) -> None:
        btns = _get_buttons(admin_broadcast_confirm_kb(42))
        assert "42 чел." in btns[0][0]
