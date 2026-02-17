"""Reply keyboards (persistent bottom keyboard)."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Main menu keyboard — always visible at bottom.

    Buttons: [Menu] [Write Article] [Create Post] + [ADMIN] for admins.
    """
    rows: list[list[KeyboardButton]] = [
        [
            KeyboardButton(text="Меню"),
            KeyboardButton(text="Написать статью"),
            KeyboardButton(text="Создать пост"),
        ],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="АДМИНКА")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


