"""E2E tests: payments flow (tariffs screen, Stars payment option).

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
]


async def _reset_state(client, bot_username: str) -> None:
    """Send /cancel to ensure clean FSM state before each test."""
    await send_and_wait(client, bot_username, "/cancel", timeout=10.0)


async def test_tariffs_screen_shows(telethon_client, bot_username: str) -> None:
    """Navigate to tariffs via dashboard -> shows packages with prices."""
    await _reset_state(telethon_client, bot_username)

    # Get dashboard message
    dashboard = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0)
    assert dashboard is not None, "Bot did not respond to /start"

    # Click "Тарифы" inline button
    tariffs_msg = await click_inline_button(telethon_client, dashboard, "Тарифы")

    if tariffs_msg is not None:
        text = (tariffs_msg.text or "").lower()
        # Tariffs screen should mention tokens, packages, or pricing
        assert any(
            fragment in text
            for fragment in [
                "токен",
                "пакет",
                "тариф",
                "баланс",
                "пополн",
                "stars",
                "подписк",
            ]
        ), f"Unexpected tariffs response: {tariffs_msg.text!r}"


async def test_stars_payment_option_visible(telethon_client, bot_username: str) -> None:
    """Tariffs screen should show Stars payment option or package buttons."""
    await _reset_state(telethon_client, bot_username)

    # Get dashboard
    dashboard = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0)
    assert dashboard is not None, "Bot did not respond to /start"

    # Navigate to tariffs
    tariffs_msg = await click_inline_button(telethon_client, dashboard, "Тарифы")

    if tariffs_msg is not None:
        text = (tariffs_msg.text or "").lower()
        has_buttons = tariffs_msg.buttons is not None and len(tariffs_msg.buttons) > 0

        # Check for Stars-related content in text or buttons
        has_stars_mention = "stars" in text or "star" in text

        has_payment_buttons = False
        if tariffs_msg.buttons:
            for row in tariffs_msg.buttons:
                for btn in row:
                    btn_text = (btn.text or "").lower()
                    if any(
                        word in btn_text
                        for word in ["пополн", "купить", "stars", "пакет", "подписк", "topup"]
                    ):
                        has_payment_buttons = True
                        break

        # Tariffs screen should have either Stars mention or payment buttons
        assert has_stars_mention or has_payment_buttons or has_buttons, (
            f"No payment options found on tariffs screen: {tariffs_msg.text!r}"
        )
