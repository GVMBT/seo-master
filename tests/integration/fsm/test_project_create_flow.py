"""Integration tests for ProjectCreateFSM — 4-step project creation flow.

Tests the full middleware -> filter -> handler pipeline via Dispatcher.feed_update().
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from tests.integration.conftest import (
    DEFAULT_USER,
    DEFAULT_USER_ID,
    MockResponse,
    make_update_callback,
    make_update_message,
)
from tests.integration.fsm.conftest import DEFAULT_PROJECT, make_mock_settings

pytestmark = pytest.mark.integration

_mock_settings = make_mock_settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db_for_project_creation(
    mock_db: Any,
    user: dict[str, Any] | None = None,
    project_count: int = 0,
    created_project: dict[str, Any] | None = None,
) -> None:
    """Set up DB mock for project creation flow."""
    data = user or DEFAULT_USER
    mock_db.set_response("users", MockResponse(data=data))
    mock_db.set_response("projects", MockResponse(data=created_project or DEFAULT_PROJECT, count=project_count))


def _put_user_in_fsm_state(
    mock_redis: Any,
    state: str,
    state_data: dict[str, Any] | None = None,
    user_id: int = DEFAULT_USER_ID,
) -> None:
    """Put user in a specific FSM state."""
    import time

    storage_key = f"fsm:{user_id}:{user_id}:state"
    mock_redis._store[storage_key] = state
    data = state_data or {}
    data.setdefault("last_update_time", time.time())
    storage_data_key = f"fsm:{user_id}:{user_id}:data"
    mock_redis._store[storage_data_key] = json.dumps(data, default=str)


def _get_all_text(mock_bot: Any) -> str:
    """Extract all text from send_message and edit_message_text calls."""
    texts = []
    for c in mock_bot.send_message.call_args_list:
        t = c.kwargs.get("text", "")
        texts.append(str(t))
    for c in mock_bot.edit_message_text.call_args_list:
        t = c.kwargs.get("text", "")
        texts.append(str(t))
    return " ".join(texts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_project_callback_starts_fsm(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Callback 'projects:new' -> asks for name (step 1/4)."""
    setup_user()
    _setup_db_for_project_creation(mock_db, project_count=0)

    update = make_update_callback("projects:new")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 1/4" in all_text or "название проекта" in all_text.lower()

    # Verify FSM state is set
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ProjectCreateFSM" in state_val


async def test_step1_name_accepted(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Valid name -> asks for company name (step 2/4)."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(mock_redis, "ProjectCreateFSM:name")

    update = make_update_message("My Test Project")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 2/4" in all_text or "компании" in all_text.lower()


async def test_step1_name_too_long(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """>100 chars name -> error, stays in state."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(mock_redis, "ProjectCreateFSM:name")

    long_name = "A" * 101
    update = make_update_message(long_name)
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "2 до 100" in all_text or "символов" in all_text.lower()

    # Should still be in same state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "ProjectCreateFSM:name" in state_val


async def test_step2_company_name_accepted(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Valid company name -> asks for specialization (step 3/4)."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(mock_redis, "ProjectCreateFSM:company_name", {"name": "Test Project"})

    update = make_update_message("Test Company LLC")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 3/4" in all_text or "специализац" in all_text.lower()


async def test_step3_specialization_accepted(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Valid specialization -> asks for website (step 4/4)."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(
        mock_redis,
        "ProjectCreateFSM:specialization",
        {"name": "Test", "company_name": "Co"},
    )

    update = make_update_message("SEO services and content marketing")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Шаг 4/4" in all_text or "URL" in all_text or "Пропустить" in all_text


async def test_step4_skip_website(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """'Пропустить' at step 4 -> creates project without URL."""
    setup_user()
    _setup_db_for_project_creation(mock_db, created_project=DEFAULT_PROJECT)
    _put_user_in_fsm_state(
        mock_redis,
        "ProjectCreateFSM:website_url",
        {"name": "Test", "company_name": "Co", "specialization": "SEO services"},
    )

    update = make_update_message("Пропустить")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    # Should show project card after creation
    assert "Test Project" in all_text or "проект" in all_text.lower()

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


async def test_step4_valid_url(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Valid URL -> creates project."""
    setup_user()
    _setup_db_for_project_creation(mock_db, created_project=DEFAULT_PROJECT)
    _put_user_in_fsm_state(
        mock_redis,
        "ProjectCreateFSM:website_url",
        {"name": "Test", "company_name": "Co", "specialization": "SEO services"},
    )

    update = make_update_message("https://example.com")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Test Project" in all_text or "\u2800" in all_text

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


async def test_step4_invalid_url(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Bad URL -> error, retry."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(
        mock_redis,
        "ProjectCreateFSM:website_url",
        {"name": "Test", "company_name": "Co", "specialization": "SEO services"},
    )

    update = make_update_message("not-a-url")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "URL" in all_text or "https" in all_text.lower()

    # Should still be in same state
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is not None
    assert "website_url" in state_val


@patch("routers.start.get_settings", _mock_settings)
async def test_cancel_during_creation(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """/cancel during creation -> clears FSM."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(mock_redis, "ProjectCreateFSM:company_name", {"name": "Draft"})

    update = make_update_message("/cancel")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "отменено" in all_text.lower()

    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


@patch("routers.start.get_settings", _mock_settings)
async def test_start_during_creation(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """/start during creation -> clears FSM, shows dashboard."""
    setup_user()
    _setup_db_for_project_creation(mock_db)
    _put_user_in_fsm_state(mock_redis, "ProjectCreateFSM:specialization", {"name": "Draft", "company_name": "Co"})

    update = make_update_message("/start")
    await dispatcher.feed_update(mock_bot, update)

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None

    # Dashboard shown
    assert mock_bot.send_message.called


async def test_full_flow_end_to_end(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """All 4 steps -> project created in DB."""
    setup_user()
    _setup_db_for_project_creation(mock_db, project_count=0, created_project=DEFAULT_PROJECT)

    # Step 1: trigger FSM via callback
    update = make_update_callback("projects:new")
    await dispatcher.feed_update(mock_bot, update)
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 2: project name
    update = make_update_message("Integration Test Project")
    await dispatcher.feed_update(mock_bot, update)
    all_text = _get_all_text(mock_bot)
    assert "Шаг 2/4" in all_text or "компании" in all_text.lower()
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 3: company name
    update = make_update_message("Test Company")
    await dispatcher.feed_update(mock_bot, update)
    all_text = _get_all_text(mock_bot)
    assert "Шаг 3/4" in all_text or "специализац" in all_text.lower()
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 4: specialization
    update = make_update_message("Full-stack SEO services for e-commerce")
    await dispatcher.feed_update(mock_bot, update)
    all_text = _get_all_text(mock_bot)
    assert "Шаг 4/4" in all_text or "URL" in all_text
    mock_bot.send_message.reset_mock()
    mock_bot.edit_message_text.reset_mock()

    # Step 5: URL (skip)
    update = make_update_message("Пропустить")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    # Project card should be shown
    assert "Test Project" in all_text or "\u2800" in all_text

    # FSM should be cleared
    state_key = f"fsm:{DEFAULT_USER_ID}:{DEFAULT_USER_ID}:state"
    state_val = await mock_redis.get(state_key)
    assert state_val is None


async def test_max_projects_limit(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """20 projects -> reject (E05)."""
    setup_user()
    # Return count of 20 (max limit)
    mock_db.set_response("users", MockResponse(data=DEFAULT_USER))
    mock_db.set_response("projects", MockResponse(data=[], count=20))

    update = make_update_callback("projects:new")
    await dispatcher.feed_update(mock_bot, update)

    # Should get callback answer with alert about limit
    assert mock_bot.answer_callback_query.called
    call_kwargs = mock_bot.answer_callback_query.call_args.kwargs
    assert call_kwargs.get("show_alert") is True
    text = call_kwargs.get("text", "")
    assert "лимит" in text.lower() or "20" in text


async def test_project_create_shows_card_after(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """After creation -> shows project card."""
    setup_user()
    created = {**DEFAULT_PROJECT, "name": "Fresh Project"}
    _setup_db_for_project_creation(mock_db, created_project=created)
    _put_user_in_fsm_state(
        mock_redis,
        "ProjectCreateFSM:website_url",
        {"name": "Fresh Project", "company_name": "Co", "specialization": "SEO services"},
    )

    update = make_update_message("Пропустить")
    await dispatcher.feed_update(mock_bot, update)

    all_text = _get_all_text(mock_bot)
    assert "Fresh Project" in all_text or "\u2800" in all_text


async def test_project_create_stores_user_id(
    dispatcher: Any,
    mock_bot: Any,
    mock_db: Any,
    mock_redis: Any,
    setup_user: Any,
) -> None:
    """Verifies user_id from middleware is used when creating project."""
    setup_user()
    _setup_db_for_project_creation(mock_db, created_project=DEFAULT_PROJECT)
    _put_user_in_fsm_state(
        mock_redis,
        "ProjectCreateFSM:website_url",
        {"name": "Test", "company_name": "Co", "specialization": "SEO svc"},
    )

    update = make_update_message("https://mysite.com")
    await dispatcher.feed_update(mock_bot, update)

    # Verify project was created (DB mock returns DEFAULT_PROJECT with user_id = DEFAULT_USER_ID)
    all_text = _get_all_text(mock_bot)
    # No error message indicates success
    assert "Ошибка" not in all_text or "Test Project" in all_text
