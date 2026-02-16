"""Reply keyboards (persistent bottom buttons)."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Compact reply keyboard: quick access to Menu and Pipeline entry.

    Navigation to Projects, Profile, Tariffs, Settings, Help is via
    inline buttons in the dashboard message (dashboard_kb in inline.py).
    """
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Меню"), KeyboardButton(text="Написать статью")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="АДМИНКА")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def cancel_kb() -> ReplyKeyboardMarkup:
    """Single [Отмена] button for FSM flows."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def skip_cancel_kb() -> ReplyKeyboardMarkup:
    """[Пропустить] + [Отмена] for optional FSM steps."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Пропустить"), KeyboardButton(text="Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
