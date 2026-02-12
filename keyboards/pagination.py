"""Generic pagination utility for inline keyboards."""

from collections.abc import Callable, Sequence
from typing import Any

from aiogram.utils.keyboard import InlineKeyboardBuilder

PAGE_SIZE = 8


def paginate(
    items: Sequence[Any],
    page: int,
    item_text_fn: Callable[[Any], str],
    item_callback_fn: Callable[[Any], str],
    page_callback_fn: Callable[[int], str],
    page_size: int = PAGE_SIZE,
) -> tuple[InlineKeyboardBuilder, bool, int]:
    """Build a paginated inline keyboard.

    Args:
        items: Full list of items to paginate.
        page: 0-indexed page number.
        item_text_fn: Extract button text from an item.
        item_callback_fn: Extract callback_data from an item.
        page_callback_fn: Build callback_data for the "next page" button.
        page_size: Items per page (default 8).

    Returns:
        (builder, has_more, nav_count) — caller MUST call builder.adjust()
        with proper sizes after appending extra buttons.
        nav_count is 0, 1, or 2 (number of navigation buttons added).
    """
    start = page * page_size
    end = start + page_size
    page_items = items[start:end]
    has_more = end < len(items)

    builder = InlineKeyboardBuilder()
    for item in page_items:
        builder.button(text=item_text_fn(item), callback_data=item_callback_fn(item))

    # Navigation row: [◀ Назад] [Ещё ▼]
    nav_count = 0
    if page > 0:
        builder.button(text="◀ Назад", callback_data=page_callback_fn(page - 1))
        nav_count += 1
    if has_more:
        builder.button(text="Ещё ▼", callback_data=page_callback_fn(page + 1))
        nav_count += 1

    # Build row sizes: items 1-wide + nav side-by-side
    sizes = [1] * len(page_items)
    if nav_count:
        sizes.append(nav_count)
    builder.adjust(*sizes)

    return builder, has_more, nav_count
