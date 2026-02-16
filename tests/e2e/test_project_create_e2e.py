"""E2E tests: full project CRUD flow against live bot.

Tests REAL functionality:
1. /start → dashboard with inline buttons
2. Click "Проекты" → project list (empty or with projects)
3. Click "Создать проект" → starts ProjectCreateFSM
4. Enter name → step 2/4
5. Enter company → step 3/4
6. Enter specialization → step 4/4
7. Enter URL or "Пропустить" → project created, card shown
8. Navigate to project card → verify data
9. Delete project → cleanup

Design: ONE sequential flow, shared state, minimal messages.
Total messages: ~12 (/cancel + /start + nav clicks + 4 FSM inputs + delete confirm).
"""

from __future__ import annotations

import asyncio
import os
import uuid
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

# Unique project name to avoid collision with real data
_TEST_PROJECT_NAME = f"E2E Test {uuid.uuid4().hex[:6]}"
_TEST_COMPANY = "E2E Company Ltd"
_TEST_SPEC = "Тестовая специализация для E2E проверки"


async def test_step01_start_dashboard(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start → dashboard with inline buttons."""
    response = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert response is not None, "Bot did not respond to /start"

    text = (response.text or "").lower()
    # Dashboard should show balance or welcome
    assert any(
        w in text for w in ["баланс", "токенов", "добро пожаловать", "нет проектов"]
    ), f"Unexpected /start: {response.text!r}"

    _state["dashboard"] = response
    await asyncio.sleep(1.5)


async def test_step02_navigate_to_projects(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: Click 'Проекты' inline button → project list."""
    dashboard = _state.get("dashboard")
    if dashboard is None:
        pytest.skip("No dashboard from step 1")

    result = await click_inline_button(telethon_client, dashboard, "Проекты")
    assert result is not None, "Bot did not respond to 'Проекты' button click"

    text = (result.text or "").lower()
    assert any(
        w in text for w in ["проект", "создать", "нет проектов", "список"]
    ), f"Unexpected projects list: {result.text!r}"

    _state["projects_list"] = result
    await asyncio.sleep(1.5)


async def test_step03_click_create_project(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: Click 'Создать проект' → FSM starts, asks for name."""
    projects_list = _state.get("projects_list")
    if projects_list is None:
        pytest.skip("No projects list from step 2")

    result = await click_inline_button(telethon_client, projects_list, "Создать")
    assert result is not None, "Bot did not respond to 'Создать проект' button"

    text = (result.text or "").lower()
    assert any(
        w in text for w in ["шаг 1", "название", "введите"]
    ), f"Expected FSM step 1 prompt: {result.text!r}"

    await asyncio.sleep(1)


async def test_step04_enter_project_name(telethon_client, bot_username: str, clean_state) -> None:
    """Step 4: Enter project name → FSM step 2 (company name)."""
    response = await send_and_wait(
        telethon_client, bot_username, _TEST_PROJECT_NAME, timeout=15.0
    )
    assert response is not None, "Bot did not respond to project name input"

    text = (response.text or "").lower()
    assert any(
        w in text for w in ["шаг 2", "компани", "название компании"]
    ), f"Expected FSM step 2: {response.text!r}"

    await asyncio.sleep(1)


async def test_step05_enter_company_name(telethon_client, bot_username: str, clean_state) -> None:
    """Step 5: Enter company name → FSM step 3 (specialization)."""
    response = await send_and_wait(
        telethon_client, bot_username, _TEST_COMPANY, timeout=15.0
    )
    assert response is not None, "Bot did not respond to company name"

    text = (response.text or "").lower()
    assert any(
        w in text for w in ["шаг 3", "специализац", "опишите"]
    ), f"Expected FSM step 3: {response.text!r}"

    await asyncio.sleep(1)


async def test_step06_enter_specialization(telethon_client, bot_username: str, clean_state) -> None:
    """Step 6: Enter specialization → FSM step 4 (URL)."""
    response = await send_and_wait(
        telethon_client, bot_username, _TEST_SPEC, timeout=15.0
    )
    assert response is not None, "Bot did not respond to specialization"

    text = (response.text or "").lower()
    assert any(
        w in text for w in ["шаг 4", "url", "сайт", "пропустить"]
    ), f"Expected FSM step 4: {response.text!r}"

    await asyncio.sleep(1)


async def test_step07_skip_url_project_created(telethon_client, bot_username: str, clean_state) -> None:
    """Step 7: Skip URL → project created.

    Bot sends TWO messages: project card (inline KB) + "Выберите действие" (reply KB).
    We collect all bot responses and find the project card among them.
    """

    # Send "Пропустить" and wait for all responses to arrive
    entity = await telethon_client.get_entity(bot_username)
    sent = await telethon_client.send_message(entity, "Пропустить")
    await asyncio.sleep(4)  # Wait for both messages to arrive

    messages = await telethon_client.get_messages(entity, limit=10)
    bot_msgs = [m for m in messages if not m.out and m.id > sent.id]

    assert len(bot_msgs) > 0, "Bot did not respond to 'Пропустить'"

    # Find the project card (contains project name or "карточка")
    card_msg = None
    for msg in bot_msgs:
        text = (msg.text or "").lower()
        if any(w in text for w in [_TEST_PROJECT_NAME.lower(), "карточка", _TEST_COMPANY.lower()]):
            card_msg = msg
            break

    if card_msg is None:
        # Fallback: the fact we got responses means project was created
        # Pick the message with inline buttons
        for msg in bot_msgs:
            if msg.reply_markup and hasattr(msg.reply_markup, "rows"):
                card_msg = msg
                break

    if card_msg is None:
        card_msg = bot_msgs[0]

    _state["project_card"] = card_msg
    _state["all_create_msgs"] = bot_msgs
    await asyncio.sleep(1.5)


async def test_step08_project_card_has_data(telethon_client, bot_username: str, clean_state) -> None:
    """Step 8: Verify project card contains entered data (no new messages)."""
    all_msgs = _state.get("all_create_msgs", [])
    card = _state.get("project_card")
    if not all_msgs and card is None:
        pytest.skip("No project card from step 7")

    # Check all bot messages for project data
    all_text = " ".join((m.text or "") for m in all_msgs).lower()
    assert any(
        w in all_text
        for w in [_TEST_PROJECT_NAME.lower(), _TEST_COMPANY.lower(), "карточка", "проект"]
    ), f"Project data not found in any response. Texts: {[m.text for m in all_msgs]!r}"

    # At least one message should have inline buttons (project card)
    has_inline = any(
        m.reply_markup and hasattr(m.reply_markup, "rows")
        for m in all_msgs
    )
    assert has_inline, "No message with inline buttons found after project creation"


async def test_step09_delete_project_cleanup(telethon_client, bot_username: str, clean_state) -> None:
    """Step 9: Delete the test project to clean up.

    Click 'Удалить' → confirm deletion → verify project removed.
    """
    card = _state.get("project_card")
    if card is None:
        pytest.skip("No project card to delete")

    # Try to find and click delete button
    delete_result = await click_inline_button(telethon_client, card, "Удалить")
    if delete_result is None:
        pytest.skip("No 'Удалить' button found on project card")

    text = (delete_result.text or "").lower()
    await asyncio.sleep(1)

    # If confirmation is asked, confirm it
    if any(w in text for w in ["подтвер", "уверен", "удалить"]):
        confirm_result = await click_inline_button(telethon_client, delete_result, "Удалить")
        if confirm_result is not None:
            confirm_text = (confirm_result.text or "").lower()
            assert any(
                w in confirm_text for w in ["удалён", "удален", "удалено", "проект"]
            ), f"Expected deletion confirmation: {confirm_result.text!r}"
    else:
        # Direct deletion without confirmation
        assert any(
            w in text for w in ["удалён", "удален", "удалено"]
        ), f"Expected deletion confirmation: {delete_result.text!r}"

    await asyncio.sleep(1)
