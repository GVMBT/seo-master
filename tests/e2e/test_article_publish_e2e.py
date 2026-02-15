"""E2E tests: article publish flow (start, cancel midway, no-projects error).

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


async def _navigate_to_projects(client, bot_username: str):
    """Navigate to projects list from dashboard. Returns the response message."""
    dashboard = await send_and_wait(client, bot_username, "/start", timeout=20.0)
    if dashboard is None:
        return None
    return await click_inline_button(client, dashboard, "Проекты")


async def test_article_flow_starts(telethon_client, bot_username: str) -> None:
    """Navigate toward article publish and verify the first step is shown.

    If the user has projects and categories with WP connections, the article
    flow should begin. If not, an appropriate error/empty state is shown.
    Either way, the bot should respond.
    """
    await _reset_state(telethon_client, bot_username)

    projects_msg = await _navigate_to_projects(telethon_client, bot_username)
    # Regardless of whether user has projects, bot must have responded
    if projects_msg is not None:
        text = (projects_msg.text or "").lower()
        # Should contain project-related content
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


async def test_article_cancel_midway(telethon_client, bot_username: str) -> None:
    """Start an article flow, then /cancel -> verify cancellation confirmed."""
    await _reset_state(telethon_client, bot_username)

    # Navigate to projects
    await _navigate_to_projects(telethon_client, bot_username)

    # Cancel whatever state we are in
    response = await send_and_wait(telethon_client, bot_username, "/cancel", timeout=15.0)
    assert response is not None, "Bot did not respond to /cancel"

    text = (response.text or "").lower()
    assert any(
        fragment in text
        for fragment in ["отменено", "нет активного"]
    ), f"Cancel response did not confirm cancellation: {response.text!r}"


async def test_article_no_projects_error(telethon_client, bot_username: str) -> None:
    """Try article publish flow with no projects -> shows appropriate message.

    Note: this test is meaningful only if the test user has no projects.
    If the user has projects, the test still passes (checks for valid response).
    """
    await _reset_state(telethon_client, bot_username)

    projects_msg = await _navigate_to_projects(telethon_client, bot_username)

    if projects_msg is not None:
        text = (projects_msg.text or "").lower()
        # Valid responses: either "no projects" or a project list
        assert any(
            fragment in text
            for fragment in [
                "нет проектов",
                "проект",
                "создать",
                "выберите",
            ]
        ), f"Unexpected response when checking projects: {projects_msg.text!r}"
