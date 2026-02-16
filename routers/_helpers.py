"""Shared router helpers — DRY extraction for callback guards and reply keyboard restore.

All callback handlers need to verify callback.message is a Message before
calling .edit_text / .edit_reply_markup. This module centralizes that pattern.
"""

from aiogram.types import CallbackQuery, Message

from keyboards.reply import main_menu

# ---------------------------------------------------------------------------
# Callback message guard
# ---------------------------------------------------------------------------

_MSG_INACCESSIBLE = "Сообщение недоступно."


async def guard_callback_message(callback: CallbackQuery) -> Message | None:
    """Return callback.message if it's a Message, otherwise answer alert and return None.

    Usage in handlers::

        msg = await guard_callback_message(callback)
        if msg is None:
            return
    """
    if isinstance(callback.message, Message):
        return callback.message
    await callback.answer(_MSG_INACCESSIBLE, show_alert=True)
    return None


# ---------------------------------------------------------------------------
# Reply keyboard restore after FSM completion (I3)
# ---------------------------------------------------------------------------

# Braille Pattern Blank (U+2800): a proper-width whitespace character that
# Telegram always accepts, unlike U+200B (zero-width space) which gets
# rejected as "empty" when parse_mode=HTML is enabled.
_KB_RESTORE_CHAR = "\u2800"


async def restore_reply_kb(target: Message, *, is_admin: bool) -> None:
    """Send minimal message to restore the compact reply keyboard after FSM exit.

    Telegram doesn't allow mixing InlineKeyboardMarkup and ReplyKeyboardMarkup
    in one message, so a separate message is required to bring back the
    persistent [Menu] + [Write Article] buttons.

    parse_mode=None overrides the bot-level default (HTML) — without it,
    Telegram strips U+2800 and rejects the message as empty.
    """
    await target.answer(
        _KB_RESTORE_CHAR, reply_markup=main_menu(is_admin=is_admin), parse_mode=None
    )
