"""Shared router helpers — DRY extraction for callback guards and ID parsing.

All callback handlers need to verify callback.message is a Message before
calling .edit_text / .edit_reply_markup. This module centralizes that pattern.
"""

from aiogram.types import CallbackQuery, Message

# ---------------------------------------------------------------------------
# Callback message guard
# ---------------------------------------------------------------------------

_MSG_INACCESSIBLE = "Сообщение недоступно."


def require_callback_message(callback: CallbackQuery) -> Message | None:
    """Return callback.message if it's a Message, otherwise answer and return None.

    Usage in handlers::

        msg = require_callback_message(callback)
        if msg is None:
            return
    """
    if isinstance(callback.message, Message):
        return callback.message
    return None


async def guard_callback_message(callback: CallbackQuery) -> Message | None:
    """Same as require_callback_message but also sends the alert answer.

    Saves an extra `await callback.answer(...)` line in the handler.
    """
    if isinstance(callback.message, Message):
        return callback.message
    await callback.answer(_MSG_INACCESSIBLE, show_alert=True)
    return None


# ---------------------------------------------------------------------------
# callback_data ID parsing
# ---------------------------------------------------------------------------


def parse_callback_id(callback: CallbackQuery, index: int = 1) -> int:
    """Extract integer ID from callback.data at given colon-separated index.

    E.g. ``parse_callback_id(cb, 1)`` for ``"project:42:card"`` → ``42``.
    """
    return int(callback.data.split(":")[index])  # type: ignore[union-attr]
