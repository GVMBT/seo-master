"""E2E test fixtures using Telethon client.

Requires environment variables:
- TELETHON_API_ID
- TELETHON_API_HASH
- TELETHON_SESSION_STRING  (pre-generated StringSession)
- STAGING_BOT_USERNAME     (e.g. @seo_master_staging_bot)

All E2E tests are skipped if these are not set.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

# Skip entire module if Telethon credentials not configured
_TELETHON_API_ID = os.environ.get("TELETHON_API_ID")
_TELETHON_API_HASH = os.environ.get("TELETHON_API_HASH")
_TELETHON_SESSION = os.environ.get("TELETHON_SESSION_STRING")
_BOT_USERNAME = os.environ.get("STAGING_BOT_USERNAME", "seo_master_staging_bot")

pytestmark = pytest.mark.e2e

_skip_reason = "E2E: TELETHON_API_ID / TELETHON_API_HASH / TELETHON_SESSION_STRING not set"


def _telethon_available() -> bool:
    return bool(_TELETHON_API_ID and _TELETHON_API_HASH and _TELETHON_SESSION)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def telethon_client():
    """Create Telethon client with StringSession (no interactive phone prompt)."""
    if not _telethon_available():
        pytest.skip(_skip_reason)

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    client = TelegramClient(
        StringSession(_TELETHON_SESSION),
        int(_TELETHON_API_ID),
        _TELETHON_API_HASH,
    )
    await client.connect()
    if not await client.is_user_authorized():
        pytest.skip("Telethon session invalid or expired")

    yield client
    await client.disconnect()


@pytest.fixture(scope="module")
def bot_username() -> str:
    """Staging bot username (without @)."""
    return _BOT_USERNAME.lstrip("@")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


async def send_and_wait(
    client,
    bot_username: str,
    text: str,
    timeout: float = 15.0,
):
    """Send a message to the bot and wait for a response.

    Returns the bot's reply Message or None on timeout.
    """
    entity = await client.get_entity(bot_username)
    await client.send_message(entity, text)

    # Wait for bot response
    end = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < end:
        messages = await client.get_messages(entity, limit=3)
        for msg in messages:
            # Bot messages have from_id pointing to bot
            if msg.from_id and hasattr(msg.from_id, "user_id"):
                bot_entity = await client.get_entity(bot_username)
                if msg.from_id.user_id == bot_entity.id and msg.date.timestamp() > (
                    asyncio.get_event_loop().time() - timeout
                ):
                    return msg
        await asyncio.sleep(0.5)
    return None


async def click_inline_button(
    client,
    message,
    button_text: str,
):
    """Find and click an inline button by text.

    Returns the bot's response after clicking, or None.
    """
    if not message or not message.buttons:
        return None

    for row in message.buttons:
        for btn in row:
            if button_text.lower() in (btn.text or "").lower():
                await btn.click()
                await asyncio.sleep(1.5)
                # Get latest messages to find the response
                entity = await message.get_input_chat()
                messages = await client.get_messages(entity, limit=3)
                return messages[0] if messages else None
    return None


async def assert_bot_replied(
    client,
    bot_username: str,
    fragment: str,
    timeout: float = 10.0,
) -> bool:
    """Assert the bot replied with a message containing the fragment."""
    msg = await send_and_wait(client, bot_username, "", timeout)
    return bool(msg and fragment.lower() in (msg.text or "").lower())
