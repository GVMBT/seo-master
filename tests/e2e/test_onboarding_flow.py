"""E2E tests: onboarding flow (/start, /help, /cancel, menu, inline navigation).

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.
"""

from __future__ import annotations

import os

import pytest

from tests.e2e.conftest import click_inline_button, send_and_wait

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("TELETHON_API_ID"),
        reason="E2E: Telethon credentials not configured",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]


async def _reset_state(client, bot_username: str) -> None:
    """Send /cancel to ensure clean FSM state before each test."""
    await send_and_wait(client, bot_username, "/cancel", timeout=10.0)


async def test_start_command_shows_welcome(telethon_client, bot_username: str) -> None:
    """Send /start -> bot replies with welcome or dashboard text."""
    await _reset_state(telethon_client, bot_username)

    response = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0)
    assert response is not None, "Bot did not respond to /start within timeout"

    text = (response.text or "").lower()
    # Bot replies with either welcome (new user) or dashboard (returning user)
    assert any(
        fragment in text
        for fragment in [
            "добро пожаловать",
            "баланс",
            "токенов",
            "проектов",
            "нет проектов",
        ]
    ), f"Unexpected /start response: {response.text!r}"


async def test_help_command_shows_help(telethon_client, bot_username: str) -> None:
    """Send /help -> bot replies with help text containing commands list."""
    await _reset_state(telethon_client, bot_username)

    response = await send_and_wait(telethon_client, bot_username, "/help", timeout=15.0)
    assert response is not None, "Bot did not respond to /help within timeout"

    text = (response.text or "").lower()
    # Help text must mention /start, /cancel, /help commands
    assert "/start" in text, f"Help text missing /start: {response.text!r}"
    assert "/cancel" in text, f"Help text missing /cancel: {response.text!r}"
    assert "/help" in text, f"Help text missing /help: {response.text!r}"


async def test_cancel_no_active_action(telethon_client, bot_username: str) -> None:
    """Send /cancel when no FSM is active -> 'Нет активного действия' or 'отменено'."""
    # First, clear any active FSM
    await send_and_wait(telethon_client, bot_username, "/cancel", timeout=10.0)

    # Send "Отмена" reply button text (equivalent of /cancel via reply keyboard)
    response = await send_and_wait(telethon_client, bot_username, "/cancel", timeout=15.0)
    assert response is not None, "Bot did not respond to /cancel within timeout"

    text = (response.text or "").lower()
    # When no FSM is active, /cancel handler always clears and says "Действие отменено."
    assert any(
        fragment in text
        for fragment in ["отменено", "нет активного"]
    ), f"Unexpected /cancel response: {response.text!r}"


async def test_menu_button_works(telethon_client, bot_username: str) -> None:
    """Send 'Меню' text -> bot replies with dashboard."""
    await _reset_state(telethon_client, bot_username)

    # First send /start to ensure reply keyboard with "Меню" button is visible
    await send_and_wait(telethon_client, bot_username, "/start", timeout=15.0)

    response = await send_and_wait(telethon_client, bot_username, "Меню", timeout=15.0)
    assert response is not None, "Bot did not respond to 'Меню' within timeout"

    text = (response.text or "").lower()
    # Dashboard should show balance or project info
    assert any(
        fragment in text
        for fragment in ["баланс", "токенов", "проектов", "нет проектов"]
    ), f"Unexpected 'Меню' response: {response.text!r}"


async def test_inline_navigation(telethon_client, bot_username: str) -> None:
    """Click 'Проекты' inline button -> shows project list or empty state."""
    await _reset_state(telethon_client, bot_username)

    # Get dashboard message with inline buttons
    dashboard = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0)
    assert dashboard is not None, "Bot did not respond to /start"

    # Click "Проекты" inline button
    result = await click_inline_button(telethon_client, dashboard, "Проекты")
    # The click may edit the dashboard message or send a new one
    # Either way, we should see project-related content
    if result is not None:
        text = (result.text or "").lower()
        assert any(
            fragment in text
            for fragment in ["проект", "создать", "нет проектов", "список"]
        ), f"Unexpected 'Проекты' navigation response: {result.text!r}"
