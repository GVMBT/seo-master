"""Reply keyboards (persistent bottom keyboard)."""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

# Reply keyboard button labels -- exported for F.text filter reuse
BTN_ADMIN = "\U0001f6e1 Админка"


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup | ReplyKeyboardRemove:
    """Main menu keyboard -- only for admins.

    Admins get [Админка] button. Non-admins get keyboard removed.
    """
    if is_admin:
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text=BTN_ADMIN)]],
            resize_keyboard=True,
        )
    return ReplyKeyboardRemove()
