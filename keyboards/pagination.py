"""Pagination utility for inline keyboards."""

import math
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

PAGE_SIZE = 8

# Telegram callback_data max length (bytes).
_MAX_CALLBACK_BYTES = 64


def _safe_cb(data: str) -> str:
    """Ensure callback_data fits Telegram's 64-byte limit."""
    if len(data.encode()) <= _MAX_CALLBACK_BYTES:
        return data
    # Truncate to fit — should never happen with numeric IDs
    return data.encode()[:_MAX_CALLBACK_BYTES].decode(errors="ignore")


def paginate(
    items: list[Any],
    page: int,
    cb_prefix: str,
    item_text: str = "name",
    item_cb: str = "{id}",
) -> tuple[InlineKeyboardMarkup, int]:
    """Build paginated InlineKeyboardMarkup.

    Args:
        items: list of objects with attribute access (Pydantic models).
        page: current page (1-based).
        cb_prefix: callback prefix for page navigation (e.g. "projects").
        item_text: attribute name for button text.
        item_cb: callback template — ``{id}`` replaced with item.id.

    Returns:
        (keyboard, total_pages)
    """
    total = len(items)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    page_items = items[start:end]

    rows: list[list[InlineKeyboardButton]] = []

    for item in page_items:
        text = getattr(item, item_text, str(item))
        cb = _safe_cb(item_cb.replace("{id}", str(item.id)))
        rows.append([InlineKeyboardButton(text=str(text), callback_data=cb)])

    # Pagination row (only if >1 page)
    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="\u25c0", callback_data=_safe_cb(f"page:{cb_prefix}:{page - 1}")))
        else:
            nav_row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="\u25b6", callback_data=_safe_cb(f"page:{cb_prefix}:{page + 1}")))
        else:
            nav_row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        rows.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages
