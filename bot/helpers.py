"""Shared helper functions for router handlers.

S1a: safe_message() eliminates ~170 InaccessibleMessage guard blocks.
S1c: get_owned_project/category ownership check helpers.
safe_edit_text: graceful photo→text transition (delete+resend).
"""

from __future__ import annotations

from typing import Any, cast

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message

from db.client import SupabaseClient
from db.models import Category, Project
from services.categories import CategoryService
from services.projects import ProjectService

# ---------------------------------------------------------------------------
# S1a: InaccessibleMessage guard helper
# ---------------------------------------------------------------------------


def safe_message(callback: CallbackQuery) -> Message | None:
    """Return callback.message if accessible, otherwise answer and return None.

    Replaces the 3-line guard pattern used in ~170 handlers:
        if not callback.message or isinstance(callback.message, InaccessibleMessage):
            await callback.answer()
            return

    Usage:
        msg = safe_message(callback)
        if not msg:
            await callback.answer()
            return
    """
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        return None
    return callback.message


# ---------------------------------------------------------------------------
# Photo→text transition helper
# ---------------------------------------------------------------------------


async def safe_edit_text(
    msg: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    **kwargs: Any,
) -> Message:
    """Edit text; if message has media, fallback to delete+resend.

    Photo messages don't support edit_text (Telegram API limitation).
    This helper catches that error and does delete+answer instead.
    """
    try:
        return cast("Message", await msg.edit_text(text, reply_markup=reply_markup, **kwargs))
    except TelegramBadRequest as e:
        if "there is no text in the message" not in str(e):
            raise
        # Photo message — delete and resend as text
        try:
            await msg.delete()
        except TelegramBadRequest:
            pass  # Message too old to delete — send new one anyway
        return await msg.answer(text, reply_markup=reply_markup, **kwargs)


# ---------------------------------------------------------------------------
# S1c: Ownership verification helpers
# ---------------------------------------------------------------------------


async def get_owned_project(
    db: SupabaseClient,
    project_id: int,
    user_id: int,
) -> Project | None:
    """Load project and verify ownership. Returns None if not found or not owned.

    Delegates to ProjectService.get_owned_project().
    """
    proj_svc = ProjectService(db=db)
    return await proj_svc.get_owned_project(project_id, user_id)


async def get_owned_category(
    db: SupabaseClient,
    category_id: int,
    user_id: int,
) -> Category | None:
    """Load category and verify it belongs to a project owned by user.

    Delegates to CategoryService.get_owned_category().
    """
    cat_svc = CategoryService(db=db)
    return await cat_svc.get_owned_category(category_id, user_id)
