"""Keyboard builders for admin panel (F20)."""

from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_dashboard_kb() -> InlineKeyboardBuilder:
    """Admin dashboard: [Мониторинг] [Сообщения всем] [Затраты API] [Назад]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Мониторинг", callback_data="admin:monitoring")
    builder.button(text="Сообщения всем", callback_data="admin:broadcast")
    builder.button(text="Затраты API", callback_data="admin:costs")
    builder.button(text="Назад", callback_data="menu:main")
    builder.adjust(2, 1, 1)
    return builder


def admin_broadcast_audience_kb() -> InlineKeyboardBuilder:
    """Broadcast audience selection."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Всем", callback_data="admin:bc:all")
    builder.button(text="Активные 7д", callback_data="admin:bc:active_7d")
    builder.button(text="Активные 30д", callback_data="admin:bc:active_30d")
    builder.button(text="Платные", callback_data="admin:bc:paid")
    builder.button(text="Отмена", callback_data="admin:main")
    builder.adjust(2, 2, 1)
    return builder


def admin_broadcast_confirm_kb(count: int) -> InlineKeyboardBuilder:
    """Confirm broadcast: [Да, отправить (N чел.)] [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, отправить ({count} чел.)", callback_data="admin:bc:confirm")
    builder.button(text="Отмена", callback_data="admin:main")
    builder.adjust(1)
    return builder
