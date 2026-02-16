"""E2E tests: onboarding flow (/start, /help, /cancel, menu, inline navigation).

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.

Design: ONE sequential flow. Tests are ordered steps that share state.
Total messages sent: 5 (/cancel from clean_state + /start + /help + /cancel + "Проекты" click).
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


async def test_step1_start_shows_welcome(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start -> bot replies with welcome or dashboard text."""
    response = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert response is not None, "Bot did not respond to /start within timeout"

    text = (response.text or "").lower()
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

    # Save dashboard message for later steps
    _state["dashboard"] = response
    await asyncio.sleep(1)


async def test_step2_help_shows_commands(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: /help -> bot replies with help text listing commands."""
    response = await send_and_wait(telethon_client, bot_username, "/help", timeout=15.0)
    assert response is not None, "Bot did not respond to /help within timeout"

    text = (response.text or "").lower()
    assert "/start" in text, f"Help text missing /start: {response.text!r}"
    assert "/cancel" in text, f"Help text missing /cancel: {response.text!r}"
    assert "/help" in text, f"Help text missing /help: {response.text!r}"

    await asyncio.sleep(1)


async def test_step3_cancel_no_active_action(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: /cancel when no FSM is active -> confirms cancellation or no action."""
    response = await send_and_wait(telethon_client, bot_username, "/cancel", timeout=15.0)
    assert response is not None, "Bot did not respond to /cancel within timeout"

    text = (response.text or "").lower()
    assert any(fragment in text for fragment in ["отменено", "нет активного"]), (
        f"Unexpected /cancel response: {response.text!r}"
    )

    await asyncio.sleep(1)


async def test_step4_menu_shows_dashboard(telethon_client, bot_username: str, clean_state) -> None:
    """Step 4: Send 'Меню' text -> bot replies with dashboard.

    Reuses the reply keyboard from step 3 (/cancel response shows keyboard).
    """
    response = await send_and_wait(telethon_client, bot_username, "Меню", timeout=15.0)
    assert response is not None, "Bot did not respond to 'Меню' within timeout"

    text = (response.text or "").lower()
    assert any(fragment in text for fragment in ["баланс", "токенов", "проектов", "нет проектов"]), (
        f"Unexpected 'Меню' response: {response.text!r}"
    )

    # Save for next step (inline button click)
    _state["menu_dashboard"] = response
    await asyncio.sleep(1)


async def test_step5_inline_projects_navigation(telethon_client, bot_username: str, clean_state) -> None:
    """Step 5: Click 'Проекты' inline button -> shows project list or empty state."""
    dashboard = _state.get("menu_dashboard")
    if dashboard is None:
        pytest.skip("No dashboard message from previous step")

    result = await click_inline_button(telethon_client, dashboard, "Проекты")
    if result is not None:
        text = (result.text or "").lower()
        assert any(fragment in text for fragment in ["проект", "создать", "нет проектов", "список"]), (
            f"Unexpected 'Проекты' navigation response: {result.text!r}"
        )

    await asyncio.sleep(1)
