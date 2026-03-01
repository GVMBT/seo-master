"""Bot UI image assets: file_id caching, photo helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from aiogram.types import FSInputFile, InputMediaPhoto

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"

# In-memory file_id cache — survives until process restart.
# First send uses FSInputFile (disk read), subsequent uses cached file_id (instant).
_FILE_ID_CACHE: dict[str, str] = {}


def asset_photo(name: str) -> str | FSInputFile:
    """Get cached file_id or FSInputFile for bot UI image."""
    if name in _FILE_ID_CACHE:
        return _FILE_ID_CACHE[name]
    path = ASSETS_DIR / name
    if not path.is_file():
        msg = f"Asset not found: {path}"
        raise FileNotFoundError(msg)
    return FSInputFile(path)


def cache_file_id(name: str, file_id: str) -> None:
    """Cache file_id after first Telegram upload."""
    _FILE_ID_CACHE[name] = file_id


async def edit_screen(
    msg: Message,
    image: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Message:
    """Edit message to show photo screen (menu navigation).

    Uses edit_media to swap both image and caption in one call.
    Caches file_id from response for subsequent requests.
    """
    media = InputMediaPhoto(media=asset_photo(image), caption=text, parse_mode="HTML")
    result = cast("Message", await msg.edit_media(media=media, reply_markup=reply_markup))
    # Cache file_id from response for performance
    if result.photo:
        cache_file_id(image, result.photo[-1].file_id)
    return result
