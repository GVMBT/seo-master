"""Tests for scheduler social keyboards (cross-posting, split UI).

Covers:
- scheduler_social_cat_list_kb (social category list)
- scheduler_social_conn_list_kb (social connections with cross-post badges)
- scheduler_crosspost_kb (cross-post toggle checkboxes)
- scheduler_social_config_kb (social config with cross-post button)
- project_card_kb split (articles + social buttons)
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from keyboards.inline import (
    project_card_kb,
    scheduler_crosspost_kb,
    scheduler_social_cat_list_kb,
    scheduler_social_config_kb,
    scheduler_social_conn_list_kb,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(
    id: int = 1,
    platform_type: str = "telegram",
    identifier: str = "test_channel",
    status: str = "active",
) -> MagicMock:
    conn = MagicMock()
    conn.id = id
    conn.platform_type = platform_type
    conn.identifier = identifier
    conn.status = status
    return conn


def _make_schedule(
    connection_id: int = 1,
    enabled: bool = True,
    schedule_days: list[str] | None = None,
    cross_post_connection_ids: list[int] | None = None,
) -> MagicMock:
    sched = MagicMock()
    sched.connection_id = connection_id
    sched.enabled = enabled
    sched.schedule_days = schedule_days or ["mon", "wed", "fri"]
    sched.cross_post_connection_ids = cross_post_connection_ids or []
    return sched


def _make_cat(id: int = 10, name: str = "SEO") -> MagicMock:
    cat = MagicMock()
    cat.id = id
    cat.name = name
    return cat


def _get_all_callbacks(kb: Any) -> list[str]:
    """Extract all callback_data from keyboard."""
    return [
        btn.callback_data
        for row in kb.inline_keyboard
        for btn in row
        if btn.callback_data
    ]


def _get_all_texts(kb: Any) -> list[str]:
    """Extract all button texts from keyboard."""
    return [btn.text for row in kb.inline_keyboard for btn in row]


# ---------------------------------------------------------------------------
# project_card_kb split (articles + social buttons)
# ---------------------------------------------------------------------------


def test_project_card_has_articles_and_social_buttons() -> None:
    """project_card_kb has separate articles and social buttons."""
    kb = project_card_kb(42)
    callbacks = _get_all_callbacks(kb)
    texts = _get_all_texts(kb)

    assert "project:42:sched_articles" in callbacks
    assert "project:42:sched_social" in callbacks
    assert any("татьи" in t for t in texts)  # "Статьи"
    assert any("оцсети" in t for t in texts)  # "Соцсети"
    # Old single scheduler button should NOT exist
    assert "project:42:scheduler" not in callbacks


# ---------------------------------------------------------------------------
# scheduler_social_cat_list_kb
# ---------------------------------------------------------------------------


def test_social_cat_list_shows_categories() -> None:
    """Social category list shows categories with correct callback prefix."""
    cats = [_make_cat(10, "SEO"), _make_cat(20, "Furniture")]
    kb = scheduler_social_cat_list_kb(cats, project_id=5)
    callbacks = _get_all_callbacks(kb)

    assert "sched_social:5:cat:10" in callbacks
    assert "sched_social:5:cat:20" in callbacks
    assert "project:5:card" in callbacks  # back button


def test_social_cat_list_empty() -> None:
    """Social category list with no categories only shows back button."""
    kb = scheduler_social_cat_list_kb([], project_id=5)
    callbacks = _get_all_callbacks(kb)
    assert callbacks == ["project:5:card"]


# ---------------------------------------------------------------------------
# scheduler_social_conn_list_kb
# ---------------------------------------------------------------------------


def test_social_conn_list_filters_social_only() -> None:
    """Social connection list filters out non-social platforms (wordpress)."""
    connections = [
        _make_conn(1, "wordpress", "test.com"),
        _make_conn(2, "telegram", "@channel"),
        _make_conn(3, "vk", "VK Group"),
    ]
    schedules: dict[int, Any] = {}
    kb = scheduler_social_conn_list_kb(connections, schedules, cat_id=10, project_id=5)
    callbacks = _get_all_callbacks(kb)

    # WP should be filtered out
    assert "sched_social:10:conn:1" not in callbacks
    assert "sched_social:10:conn:2" in callbacks
    assert "sched_social:10:conn:3" in callbacks


def test_social_conn_list_shows_cross_post_badge() -> None:
    """Social connection list shows cross-post count badge."""
    connections = [_make_conn(2, "telegram", "@channel")]
    schedules = {
        2: _make_schedule(connection_id=2, enabled=True, cross_post_connection_ids=[3, 4])
    }
    kb = scheduler_social_conn_list_kb(connections, schedules, cat_id=10, project_id=5)
    texts = _get_all_texts(kb)

    matching = [t for t in texts if "+2" in t and "кросс" in t.lower()]
    assert len(matching) == 1


def test_social_conn_list_no_schedule_label() -> None:
    """Connection without schedule shows 'no schedule' label."""
    connections = [_make_conn(2, "telegram", "@channel")]
    schedules: dict[int, Any] = {}
    kb = scheduler_social_conn_list_kb(connections, schedules, cat_id=10, project_id=5)
    texts = _get_all_texts(kb)

    matching = [t for t in texts if "нет расписания" in t]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# scheduler_crosspost_kb
# ---------------------------------------------------------------------------


def test_crosspost_kb_excludes_lead_connection() -> None:
    """Cross-post toggle excludes the lead (source) connection."""
    conns = [
        _make_conn(1, "telegram", "@lead"),
        _make_conn(2, "vk", "VK Group"),
        _make_conn(3, "pinterest", "Board"),
    ]
    kb = scheduler_crosspost_kb(cat_id=10, conn_id=1, social_connections=conns, selected_ids=[])
    callbacks = _get_all_callbacks(kb)

    # Lead (conn_id=1) should NOT be toggleable
    toggle_cbs = [cb for cb in callbacks if ":toggle" in cb]
    assert len(toggle_cbs) == 2  # VK + Pinterest, not Telegram lead


def test_crosspost_kb_shows_selected_checkmarks() -> None:
    """Selected cross-post targets show checkmark prefix."""
    conns = [
        _make_conn(1, "telegram", "@lead"),
        _make_conn(2, "vk", "VK Group"),
        _make_conn(3, "pinterest", "Board"),
    ]
    kb = scheduler_crosspost_kb(cat_id=10, conn_id=1, social_connections=conns, selected_ids=[2])
    texts = _get_all_texts(kb)

    vk_texts = [t for t in texts if "VK" in t and "Group" in t]
    assert len(vk_texts) == 1
    assert vk_texts[0].startswith("\u2713")  # checkmark

    pin_texts = [t for t in texts if "Board" in t]
    assert len(pin_texts) == 1
    assert not pin_texts[0].startswith("\u2713")  # no checkmark


def test_crosspost_kb_has_save_and_cancel() -> None:
    """Cross-post keyboard has save and cancel buttons."""
    conns = [_make_conn(1, "telegram"), _make_conn(2, "vk")]
    kb = scheduler_crosspost_kb(cat_id=10, conn_id=1, social_connections=conns, selected_ids=[])
    callbacks = _get_all_callbacks(kb)

    assert "sched_xp:10:1:save" in callbacks
    assert "sched_social:10:conn:1" in callbacks  # cancel -> back to config


def test_crosspost_kb_callback_within_64_bytes() -> None:
    """All cross-post callbacks fit within 64-byte limit."""
    conns = [
        _make_conn(1, "telegram"),
        _make_conn(99999, "vk"),  # large ID
    ]
    kb = scheduler_crosspost_kb(cat_id=99999, conn_id=99999, social_connections=conns, selected_ids=[])
    callbacks = _get_all_callbacks(kb)

    for cb in callbacks:
        assert len(cb.encode("utf-8")) <= 64, f"Callback too long: {cb} ({len(cb.encode())} bytes)"


# ---------------------------------------------------------------------------
# scheduler_social_config_kb
# ---------------------------------------------------------------------------


def test_social_config_shows_crosspost_when_schedule_and_other_social() -> None:
    """Cross-post button appears only when has_schedule AND has_other_social."""
    kb = scheduler_social_config_kb(cat_id=10, conn_id=1, has_schedule=True, has_other_social=True)
    callbacks = _get_all_callbacks(kb)
    assert "sched_xp:10:1:config" in callbacks


def test_social_config_hides_crosspost_no_other_social() -> None:
    """Cross-post button hidden when no other social connections."""
    kb = scheduler_social_config_kb(cat_id=10, conn_id=1, has_schedule=True, has_other_social=False)
    callbacks = _get_all_callbacks(kb)
    assert "sched_xp:10:1:config" not in callbacks


def test_social_config_hides_crosspost_no_schedule() -> None:
    """Cross-post button hidden when no schedule exists."""
    kb = scheduler_social_config_kb(cat_id=10, conn_id=1, has_schedule=False, has_other_social=True)
    callbacks = _get_all_callbacks(kb)
    assert "sched_xp:10:1:config" not in callbacks


def test_social_config_disable_only_when_has_schedule() -> None:
    """Disable button appears only when schedule exists."""
    kb_with = scheduler_social_config_kb(cat_id=10, conn_id=1, has_schedule=True)
    kb_without = scheduler_social_config_kb(cat_id=10, conn_id=1, has_schedule=False)

    cbs_with = _get_all_callbacks(kb_with)
    cbs_without = _get_all_callbacks(kb_without)

    assert "sched:10:1:disable" in cbs_with
    assert "sched:10:1:disable" not in cbs_without
