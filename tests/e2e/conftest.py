"""E2E test fixtures using Telethon client.

Requires environment variables:
- TELETHON_API_ID
- TELETHON_API_HASH
- TELETHON_SESSION_STRING  (pre-generated StringSession)
- STAGING_BOT_USERNAME     (e.g. @seo_master_staging_bot)

All E2E tests are skipped if these are not set.

Design: one /cancel per module (clean_state fixture), NOT per test.
Tests within a module are sequential steps sharing state via module-level dict.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

# Load .env so E2E tests pick up Telethon credentials.
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env", override=False)

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
        int(_TELETHON_API_ID),  # type: ignore[arg-type]
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


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def clean_state(telethon_client, bot_username):
    """Reset FSM state once per module, not per test.

    Sends /cancel and waits, then yields. Each module gets exactly ONE reset.
    Inter-module delay of 3 seconds prevents rate limiting.
    """
    await send_and_wait(telethon_client, bot_username, "/cancel", timeout=10.0)
    await asyncio.sleep(10)  # 10s gap between modules to avoid 30 msg/min rate limit
    yield


# ---------------------------------------------------------------------------
# Helper functions (importable by test modules)
# ---------------------------------------------------------------------------


async def send_and_wait(
    client,
    bot_username: str,
    text: str,
    timeout: float = 15.0,
    wait_all: bool = False,
):
    """Send a message to the bot and wait for a response.

    Args:
        wait_all: If True, waits extra time and returns the LAST bot message
                  (useful for commands like /start that send multiple messages).
                  If False, returns the first bot message detected.

    Returns the bot's reply Message or None on timeout.
    """
    import time as _time

    entity = await client.get_entity(bot_username)

    # Remember last bot message ID to detect NEW responses only
    prev_messages = await client.get_messages(entity, limit=1)
    last_seen_id = prev_messages[0].id if prev_messages else 0  # noqa: F841

    sent_msg = await client.send_message(entity, text)

    if wait_all:
        # Wait for all responses to arrive, then return the last one
        # (or the one with inline buttons if multiple exist)
        await asyncio.sleep(min(timeout * 0.6, 5.0))
        messages = await client.get_messages(entity, limit=10)
        bot_msgs = [m for m in messages if not m.out and m.id > sent_msg.id]
        if bot_msgs:
            # Prefer message with inline buttons (dashboard/card), else last
            for m in bot_msgs:
                if m.buttons:
                    return m
            return bot_msgs[0]  # newest first (Telethon default order)
        # Fallback: keep polling
        deadline = _time.time() + timeout * 0.4
        while _time.time() < deadline:
            messages = await client.get_messages(entity, limit=10)
            for msg in messages:
                if not msg.out and msg.id > sent_msg.id:
                    return msg
            await asyncio.sleep(0.5)
        return None

    # Default: return first bot response
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        messages = await client.get_messages(entity, limit=5)
        for msg in messages:
            # Bot messages: not outgoing, with ID greater than our sent message
            if not msg.out and msg.id > sent_msg.id:
                return msg
        await asyncio.sleep(0.5)
    return None


async def click_inline_button(
    client,
    message,
    button_text: str,
    timeout: float = 10.0,
):
    """Find and click an inline button by text.

    Returns the bot's response after clicking, or None.
    """
    import time as _time

    if not message or not message.buttons:
        return None

    for row in message.buttons:
        for btn in row:
            if button_text.lower() in (btn.text or "").lower():
                # Remember message ID before clicking
                entity = await message.get_input_chat()
                prev_messages = await client.get_messages(entity, limit=1)
                prev_id = prev_messages[0].id if prev_messages else 0

                await btn.click()

                # Wait for a new or edited message
                deadline = _time.time() + timeout
                while _time.time() < deadline:
                    messages = await client.get_messages(entity, limit=3)
                    for msg in messages:
                        # New message from bot, or the original message was edited
                        if not msg.out and msg.id > prev_id:
                            return msg
                    # Also check if the clicked message itself was edited
                    if messages and messages[0].id == message.id and messages[0].edit_date:
                        return messages[0]
                    await asyncio.sleep(0.5)
                return None
    return None
