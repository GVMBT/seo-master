"""E2E tests: pipeline entry flow (replaced quick publish).

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.

Design: ONE sequential flow. Tests are ordered steps that share state.
Total messages sent: 3 (/cancel from clean_state + "Написать статью" + /cancel).
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


async def test_step1_write_article_response(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: Send 'Написать статью' -> bot responds with dashboard or pipeline entry."""
    response = await send_and_wait(
        telethon_client,
        bot_username,
        "Написать статью",
        timeout=15.0,
    )
    assert response is not None, "Bot did not respond to 'Написать статью'"

    text = (response.text or "").lower()
    assert any(
        fragment in text
        for fragment in [
            "статью",
            "проект",
            "баланс",
            "токен",
            "написать",
            "опубликовать",
        ]
    ), f"Unexpected write article response: {response.text!r}"

    _state["write_article_msg"] = response
    await asyncio.sleep(1)


async def test_step2_write_article_content_valid(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: Verify write article response has valid content.

    No new messages sent -- inspects state from step 1.
    """
    msg = _state.get("write_article_msg")
    if msg is None:
        pytest.skip("No write article response from step 1")

    text = (msg.text or "").lower()
    assert any(
        fragment in text
        for fragment in [
            "проект",
            "баланс",
            "токен",
            "статью",
            "написать",
        ]
    ), f"Unexpected write article content: {msg.text!r}"


async def test_step3_cancel_after_write_article(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: /cancel after write article -> confirms cancellation."""
    response = await send_and_wait(telethon_client, bot_username, "/cancel", timeout=15.0)
    assert response is not None, "Bot did not respond to /cancel after write article"

    text = (response.text or "").lower()
    assert any(fragment in text for fragment in ["отменено", "нет активного"]), (
        f"Unexpected cancel response: {response.text!r}"
    )

    await asyncio.sleep(1)
