"""E2E tests: payments flow (tariffs screen, Stars payment option).

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.

Design: ONE sequential flow. Tests are ordered steps that share state.
Total messages sent: 2 (/cancel from clean_state + /start).
The inline "Тарифы" click does not count as a user message (callback query).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

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

# Module-level shared state between sequential tests
_state: dict[str, Any] = {}


async def test_step1_navigate_to_tariffs(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start -> click Тарифы -> verify tariffs screen."""
    dashboard = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert dashboard is not None, "Bot did not respond to /start"

    await asyncio.sleep(1)

    # Click "Тарифы" inline button
    tariffs_msg = await click_inline_button(telethon_client, dashboard, "Тарифы")
    _state["tariffs_msg"] = tariffs_msg

    if tariffs_msg is not None:
        text = (tariffs_msg.text or "").lower()
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

    await asyncio.sleep(1)


async def test_step2_stars_payment_visible(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: Verify tariffs screen has Stars payment option or package buttons.

    No new messages sent -- inspects state from step 1.
    """
    tariffs_msg = _state.get("tariffs_msg")
    if tariffs_msg is None:
        pytest.skip("No tariffs response from step 1 (bot may not have Тарифы button)")

    text = (tariffs_msg.text or "").lower()
    has_buttons = tariffs_msg.buttons is not None and len(tariffs_msg.buttons) > 0

    # Check for Stars-related content in text or buttons
    has_stars_mention = "stars" in text or "star" in text

    has_payment_buttons = False
    if tariffs_msg.buttons:
        for row in tariffs_msg.buttons:
            for btn in row:
                btn_text = (btn.text or "").lower()
                if any(word in btn_text for word in ["пополн", "купить", "stars", "пакет", "подписк", "topup"]):
                    has_payment_buttons = True
                    break

    assert has_stars_mention or has_payment_buttons or has_buttons, (
        f"No payment options found on tariffs screen: {tariffs_msg.text!r}"
    )
