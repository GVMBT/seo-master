"""Custom emoji constants for bot UI messages.

Uses static custom emoji (colored circles) for progress indicators.
Requires bot owner to have Telegram Premium subscription.

Fallback: if custom emoji can't be displayed (non-premium forwarding,
system notifications), the Unicode emoji inside the tag is shown instead.
"""

from __future__ import annotations

# Custom emoji IDs (static colored circles from user's sticker pack)
_YELLOW = "5021712394259268143"  # In progress / waiting
_GREEN = "5391076601007972395"  # Done / success
_RED = "4927486932113425461"  # Error / missing

# HTML entities for use in parse_mode="HTML" messages
EMOJI_PROGRESS = f'<tg-emoji emoji-id="{_YELLOW}">\U0001f7e1</tg-emoji>'
EMOJI_DONE = f'<tg-emoji emoji-id="{_GREEN}">\u2705</tg-emoji>'
EMOJI_ERROR = f'<tg-emoji emoji-id="{_RED}">\u274c</tg-emoji>'
