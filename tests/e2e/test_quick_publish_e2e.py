"""E2E tests: quick publish flow.

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.
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


async def test_quick_publish_button_works(telethon_client, bot_username: str) -> None:
    """Send 'Быстрая публикация' text -> bot responds with quick publish menu or empty state."""
    await _reset_state(telethon_client, bot_username)

    # Ensure reply keyboard is active
    await send_and_wait(telethon_client, bot_username, "/start", timeout=15.0)

    response = await send_and_wait(
        telethon_client, bot_username, "Быстрая публикация", timeout=15.0,
    )
    assert response is not None, "Bot did not respond to 'Быстрая публикация'"

    text = (response.text or "").lower()
    # Should show either quick publish options or a message about no projects/platforms
    assert any(
        fragment in text
        for fragment in [
            "публикация",
            "платформ",
            "проект",
            "нет подключ",
            "выберите",
            "категори",
        ]
    ), f"Unexpected quick publish response: {response.text!r}"


async def test_quick_publish_no_projects(telethon_client, bot_username: str) -> None:
    """Quick publish with no projects -> appropriate message.

    Note: if the test user has projects, the test still validates the response.
    """
    await _reset_state(telethon_client, bot_username)

    await send_and_wait(telethon_client, bot_username, "/start", timeout=15.0)

    response = await send_and_wait(
        telethon_client, bot_username, "Быстрая публикация", timeout=15.0,
    )
    assert response is not None, "Bot did not respond to quick publish"

    text = (response.text or "").lower()
    # Valid responses: either no projects/platforms or quick publish menu
    assert any(
        fragment in text
        for fragment in [
            "нет проектов",
            "нет подключ",
            "проект",
            "платформ",
            "категори",
            "публикация",
            "выберите",
        ]
    ), f"Unexpected response: {response.text!r}"


async def test_quick_publish_navigation(telethon_client, bot_username: str) -> None:
    """Navigate through quick publish menu and verify responses are valid.

    Sends quick publish, then /cancel to return. Validates both responses.
    """
    await _reset_state(telethon_client, bot_username)

    await send_and_wait(telethon_client, bot_username, "/start", timeout=15.0)

    response = await send_and_wait(
        telethon_client, bot_username, "Быстрая публикация", timeout=15.0,
    )
    assert response is not None, "Bot did not respond to quick publish"

    # Return to main menu via /cancel
    cancel_response = await send_and_wait(
        telethon_client, bot_username, "/cancel", timeout=15.0,
    )
    assert cancel_response is not None, "Bot did not respond to /cancel after quick publish"

    text = (cancel_response.text or "").lower()
    assert any(
        fragment in text
        for fragment in ["отменено", "нет активного"]
    ), f"Unexpected cancel response: {cancel_response.text!r}"
