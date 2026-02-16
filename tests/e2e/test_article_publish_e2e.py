"""E2E tests: article publish flow (navigate to projects, check state, cancel).

Uses Telethon to send real messages to a staging bot via Telegram.
All tests are skipped if TELETHON_API_ID is not set.

Design: ONE sequential flow. Tests are ordered steps that share state.
Total messages sent: 3 (/cancel from clean_state + /start + /cancel).
The inline "Проекты" click does not count as a user message (callback query).
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


async def test_step1_navigate_to_projects(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start -> click Проекты -> check projects list or empty state."""
    dashboard = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert dashboard is not None, "Bot did not respond to /start"

    _state["dashboard"] = dashboard
    await asyncio.sleep(1)

    # Click "Проекты" inline button
    projects_msg = await click_inline_button(telethon_client, dashboard, "Проекты")
    _state["projects_msg"] = projects_msg

    if projects_msg is not None:
        text = (projects_msg.text or "").lower()
        assert any(
            fragment in text
            for fragment in [
                "проект",
                "создать",
                "нет проектов",
                "выберите",
                "список",
            ]
        ), f"Unexpected projects response: {projects_msg.text!r}"

    await asyncio.sleep(1)


async def test_step2_projects_has_valid_content(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: Verify the projects response from step 1 has meaningful content.

    If user has projects, should list them. If not, shows empty state.
    No new messages sent -- this test inspects the state from step 1.
    """
    projects_msg = _state.get("projects_msg")
    if projects_msg is None:
        pytest.skip("No projects response from step 1 (bot may not have Проекты button)")

    text = (projects_msg.text or "").lower()
    # Either "no projects" message or a list of projects
    assert any(
        fragment in text
        for fragment in [
            "нет проектов",
            "проект",
            "создать",
            "выберите",
        ]
    ), f"Unexpected projects content: {projects_msg.text!r}"


async def test_step3_cancel_returns_cleanly(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: /cancel after navigating to projects -> confirms cancellation."""
    response = await send_and_wait(telethon_client, bot_username, "/cancel", timeout=15.0)
    assert response is not None, "Bot did not respond to /cancel"

    text = (response.text or "").lower()
    assert any(fragment in text for fragment in ["отменено", "нет активного"]), (
        f"Cancel response did not confirm cancellation: {response.text!r}"
    )

    await asyncio.sleep(1)
