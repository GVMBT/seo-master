"""E2E tests: FSM input validation against live bot.

Tests REAL validation behavior:
1. Start project creation FSM
2. Send too-short name → error, stays in same state
3. Send valid name → proceeds to step 2
4. /cancel → FSM cancelled, back to menu

This validates that FSM handlers correctly reject invalid input
and stay in the same state (not advance or crash).

Design: ONE sequential flow.
Total messages: 6 (/cancel + /start + click + bad input + good input + /cancel).
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

_state: dict[str, Any] = {}


async def test_step01_start_and_create(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start → click Проекты → click Создать."""
    dashboard = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert dashboard is not None, "Bot did not respond to /start"
    await asyncio.sleep(1)

    projects = await click_inline_button(telethon_client, dashboard, "Проекты")
    assert projects is not None, "No projects list"
    _state["projects"] = projects
    await asyncio.sleep(1)

    create = await click_inline_button(telethon_client, projects, "Создать")
    assert create is not None, "No create button response"

    text = (create.text or "").lower()
    assert "шаг 1" in text or "название" in text, f"Not in FSM step 1: {create.text!r}"
    await asyncio.sleep(1)


async def test_step02_invalid_name_rejected(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: Send single char → validation error, stays in step 1."""
    response = await send_and_wait(telethon_client, bot_username, "X", timeout=15.0)
    assert response is not None, "Bot did not respond to invalid name"

    text = (response.text or "").lower()
    # Should get validation error
    assert any(w in text for w in ["символ", "от 2", "введите", "ошибк", "недопуст"]), (
        f"Expected validation error: {response.text!r}"
    )

    await asyncio.sleep(1)


async def test_step03_valid_name_accepted(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: Send valid name → proceeds to step 2 (company name)."""
    response = await send_and_wait(telethon_client, bot_username, "Validation Test Project", timeout=15.0)
    assert response is not None, "Bot did not respond to valid name"

    text = (response.text or "").lower()
    assert any(w in text for w in ["шаг 2", "компани"]), f"Expected step 2: {response.text!r}"

    await asyncio.sleep(1)


async def test_step04_cancel_mid_fsm(telethon_client, bot_username: str, clean_state) -> None:
    """Step 4: /cancel during FSM → FSM cleared, back to menu."""
    response = await send_and_wait(telethon_client, bot_username, "/cancel", timeout=15.0)
    assert response is not None, "Bot did not respond to /cancel"

    text = (response.text or "").lower()
    assert any(w in text for w in ["отменено", "действие отменено"]), f"Expected cancellation: {response.text!r}"

    await asyncio.sleep(1)


async def test_step05_fsm_cleared_after_cancel(telethon_client, bot_username: str, clean_state) -> None:
    """Step 5: Verify FSM is actually cleared — send text, should not be treated as FSM input."""
    response = await send_and_wait(telethon_client, bot_username, "Меню", timeout=15.0)
    assert response is not None, "Bot did not respond to 'Меню'"

    text = (response.text or "").lower()
    # Should show dashboard, not FSM prompt
    assert any(w in text for w in ["баланс", "токенов", "проектов", "нет проектов"]), (
        f"FSM not properly cleared: {response.text!r}"
    )

    await asyncio.sleep(1)
