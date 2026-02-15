"""Shared router helpers — DRY extraction for callback guards.

All callback handlers need to verify callback.message is a Message before
calling .edit_text / .edit_reply_markup. This module centralizes that pattern.
"""

from aiogram.types import CallbackQuery, Message

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
