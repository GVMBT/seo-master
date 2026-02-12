"""Reply keyboards (persistent bottom buttons)."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Main menu reply keyboard (3x2 grid + optional admin row)."""
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text="Быстрая публикация"), KeyboardButton(text="Проекты")],
        [KeyboardButton(text="Профиль"), KeyboardButton(text="Тарифы")],
        [KeyboardButton(text="Настройки"), KeyboardButton(text="Помощь")],
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
