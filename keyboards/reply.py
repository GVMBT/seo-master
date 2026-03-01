"""Reply keyboards (persistent bottom keyboard)."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Reply keyboard button labels -- exported for F.text filter reuse
BTN_MENU = "\U0001f4cb Меню"
BTN_ADMIN = "\U0001f6e1 Админка"


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Main menu keyboard -- always visible at bottom.

    Buttons: [Menu] + [Admin] for admins.
    """
    rows: list[list[KeyboardButton]] = [
        [KeyboardButton(text=BTN_MENU)],
    ]
    if is_admin:
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)
