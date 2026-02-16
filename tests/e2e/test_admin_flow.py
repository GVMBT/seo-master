"""E2E tests: admin panel flow.

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.

Design: ONE sequential flow. Tests are ordered steps that share state.
Total messages sent: 2-3 (/cancel from clean_state + /start + optionally "АДМИНКА").
Non-admin users: step 1 checks for admin button; later steps skip gracefully.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from tests.e2e.conftest import send_and_wait

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


async def test_step1_check_admin_button(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start -> check if reply keyboard has АДМИНКА button.

    Saves admin status and dashboard for subsequent steps.
    """
    response = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert response is not None, "Bot did not respond to /start"

    _state["dashboard"] = response

    # Check reply markup for admin button
    has_admin = False
    if response.buttons:
        for row in response.buttons:
            for btn in row:
                if btn.text and "АДМИНКА" in btn.text.upper():
                    has_admin = True
                    break

    _state["has_admin"] = has_admin
    await asyncio.sleep(1)


async def test_step2_admin_panel_content(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: If admin, send АДМИНКА -> verify admin panel content.

    Skips if user is not admin (no АДМИНКА button in step 1).
    """
    if not _state.get("has_admin"):
        pytest.skip("Test user is not an admin (no АДМИНКА button)")

    response = await send_and_wait(telethon_client, bot_username, "АДМИНКА", timeout=15.0)
    assert response is not None, "Admin bot did not respond to АДМИНКА"

    _state["admin_msg"] = response

    text = (response.text or "").lower()
    assert any(fragment in text for fragment in ["админ", "статистика", "пользователей", "панель"]), (
        f"Admin panel response unexpected: {response.text!r}"
    )

    await asyncio.sleep(1)


async def test_step3_admin_has_stats_or_broadcast(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: Verify admin panel has stats and/or broadcast option.

    No new messages sent -- inspects state from step 2.
    Skips if user is not admin.
    """
    if not _state.get("has_admin"):
        pytest.skip("Test user is not an admin (no АДМИНКА button)")

    admin_msg = _state.get("admin_msg")
    if admin_msg is None:
        pytest.skip("No admin panel response from step 2")

    text = (admin_msg.text or "").lower()

    # Check for stats content
    has_stats = any(
        fragment in text for fragment in ["пользователей", "статистика", "проектов", "токенов", "публикаций"]
    )

    # Check for broadcast button
    has_broadcast = False
    if admin_msg.buttons:
        for row in admin_msg.buttons:
            for btn in row:
                btn_text = (btn.text or "").lower()
                if any(word in btn_text for word in ["рассылка", "broadcast"]):
                    has_broadcast = True
                    break

    assert has_stats or has_broadcast or "рассылк" in text, (
        f"Admin panel missing stats or broadcast: {admin_msg.text!r}"
    )
