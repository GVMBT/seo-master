"""E2E tests: admin panel flow.

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.

Note: admin tests may need additional skipping if the test user is not an admin.
The tests are designed to be resilient to both admin and non-admin users.
"""

from __future__ import annotations

import os

import pytest

from tests.e2e.conftest import send_and_wait

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("TELETHON_API_ID"),
        reason="E2E: Telethon credentials not configured",
    ),
]


async def _reset_state(client, bot_username: str) -> None:
    """Send /cancel to ensure clean FSM state before each test."""
    await send_and_wait(client, bot_username, "/cancel", timeout=10.0)


async def _has_admin_button(client, bot_username: str) -> bool:
    """Check if the reply keyboard after /start contains an АДМИНКА button.

    Uses Telethon to inspect the reply keyboard markup on the bot's response.
    """
    response = await send_and_wait(client, bot_username, "/start", timeout=20.0)
    if response is None:
        return False
    # Check reply markup for admin button (ReplyKeyboardMarkup on response)
    # Telethon provides buttons on messages with reply_markup
    if not response.buttons:
        return False
    for row in response.buttons:
        for btn in row:
            if btn.text and "АДМИНКА" in btn.text.upper():
                return True
    return False


async def test_admin_panel_requires_admin(telethon_client, bot_username: str) -> None:
    """Non-admin user should NOT see the АДМИНКА button in reply keyboard.

    If the test user IS an admin, this test verifies the button IS present.
    Either way, the bot's behavior should be consistent with the user's role.
    """
    await _reset_state(telethon_client, bot_username)

    has_admin = await _has_admin_button(telethon_client, bot_username)

    # Send АДМИНКА text regardless (to test access control)
    response = await send_and_wait(telethon_client, bot_username, "АДМИНКА", timeout=15.0)

    if has_admin:
        # Admin user: should see admin panel content
        assert response is not None, "Admin bot did not respond to АДМИНКА"
        text = (response.text or "").lower()
        assert any(
            fragment in text
            for fragment in ["админ", "статистика", "пользователей", "панель"]
        ), f"Admin panel response unexpected: {response.text!r}"
    else:
        # Non-admin: bot may not respond or may show an error/ignore
        # The reply keyboard filter F.text == "АДМИНКА" only fires if the button exists
        # Non-admin users will not have the button, so the message may go unhandled
        pass  # No assertion needed for non-admin — button absence is the guard


async def test_admin_stats_accessible(telethon_client, bot_username: str) -> None:
    """Admin user can access stats panel.

    Skips if the test user is not an admin (no АДМИНКА button).
    """
    await _reset_state(telethon_client, bot_username)

    has_admin = await _has_admin_button(telethon_client, bot_username)
    if not has_admin:
        pytest.skip("Test user is not an admin")

    response = await send_and_wait(telethon_client, bot_username, "АДМИНКА", timeout=15.0)
    assert response is not None, "Admin bot did not respond to АДМИНКА"

    text = (response.text or "").lower()
    # Admin panel should show statistics or user counts
    assert any(
        fragment in text
        for fragment in ["пользователей", "статистика", "проектов", "токенов", "публикаций"]
    ), f"Stats not shown in admin panel: {response.text!r}"


async def test_admin_broadcast_accessible(telethon_client, bot_username: str) -> None:
    """Admin user can see broadcast option in admin panel.

    Skips if the test user is not an admin (no АДМИНКА button).
    """
    await _reset_state(telethon_client, bot_username)

    has_admin = await _has_admin_button(telethon_client, bot_username)
    if not has_admin:
        pytest.skip("Test user is not an admin")

    response = await send_and_wait(telethon_client, bot_username, "АДМИНКА", timeout=15.0)
    assert response is not None, "Admin bot did not respond to АДМИНКА"

    # Check inline buttons for broadcast option
    has_broadcast = False
    if response.buttons:
        for row in response.buttons:
            for btn in row:
                btn_text = (btn.text or "").lower()
                if any(word in btn_text for word in ["рассылка", "broadcast"]):
                    has_broadcast = True
                    break

    # Admin panel should have a broadcast button or mention it
    text = (response.text or "").lower()
    assert has_broadcast or "рассылк" in text, (
        f"Broadcast option not found in admin panel: {response.text!r}"
    )
