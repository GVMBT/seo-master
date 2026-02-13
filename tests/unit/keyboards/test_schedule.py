"""Tests for keyboards/schedule.py — schedule keyboard builders."""

from __future__ import annotations

from db.models import Category, PlatformConnection, PlatformSchedule
from keyboards.schedule import (
    schedule_count_kb,
    schedule_days_kb,
    schedule_summary_kb,
    schedule_times_kb,
    scheduler_category_list_kb,
    scheduler_platform_list_kb,
)

# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_category(**overrides) -> Category:
    defaults = {"id": 1, "project_id": 1, "name": "Test Category"}
    defaults.update(overrides)
    return Category(**defaults)


def _make_connection(**overrides) -> PlatformConnection:
    defaults = {
        "id": 1, "project_id": 1, "platform_type": "wordpress",
        "status": "active", "credentials": {}, "identifier": "test.com",
    }
    defaults.update(overrides)
    return PlatformConnection(**defaults)


def _make_schedule(**overrides) -> PlatformSchedule:
    defaults = {
        "id": 1, "category_id": 1, "platform_type": "wordpress",
        "connection_id": 1, "enabled": False, "status": "active",
    }
    defaults.update(overrides)
    return PlatformSchedule(**defaults)


# ---------------------------------------------------------------------------
# scheduler_category_list_kb
# ---------------------------------------------------------------------------


def test_category_list_has_categories() -> None:
    cats = [_make_category(id=1, name="SEO"), _make_category(id=2, name="SMM")]
    kb = scheduler_category_list_kb(cats, project_id=1)
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert "SEO" in texts
    assert "SMM" in texts


def test_category_list_has_back_button() -> None:
    kb = scheduler_category_list_kb([_make_category()], project_id=5)
    markup = kb.as_markup()
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "project:5:card" in callbacks


# ---------------------------------------------------------------------------
# scheduler_platform_list_kb
# ---------------------------------------------------------------------------


def test_platform_list_shows_on_off() -> None:
    conns = [_make_connection(id=1), _make_connection(id=2, platform_type="telegram", identifier="@chan")]
    scheds = [_make_schedule(connection_id=1, enabled=True)]
    kb = scheduler_platform_list_kb(conns, scheds, category_id=10, project_id=1)
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert any("[ON]" in t for t in texts)
    assert not any("[ON]" in t for t in texts if "@chan" in t)


def test_platform_list_no_schedules() -> None:
    conns = [_make_connection()]
    kb = scheduler_platform_list_kb(conns, [], category_id=10, project_id=1)
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert not any("[ON]" in t or "[OFF]" in t for t in texts if "WP" in t)


# ---------------------------------------------------------------------------
# schedule_days_kb
# ---------------------------------------------------------------------------


def test_days_kb_selected_highlighted() -> None:
    kb = schedule_days_kb({"mon", "fri"})
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert "Пн *" in texts
    assert "Пт *" in texts
    assert "Ср" in texts  # Not selected  # noqa: RUF001


def test_days_kb_none_selected() -> None:
    kb = schedule_days_kb(set())
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert all("*" not in t for t in texts if t != "Готово")


def test_days_kb_has_done_button() -> None:
    kb = schedule_days_kb(set())
    markup = kb.as_markup()
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "sched:days:done" in callbacks


# ---------------------------------------------------------------------------
# schedule_count_kb
# ---------------------------------------------------------------------------


def test_count_kb_has_5_buttons() -> None:
    kb = schedule_count_kb()
    markup = kb.as_markup()
    buttons = [b for row in markup.inline_keyboard for b in row]
    assert len(buttons) == 5
    assert buttons[0].text == "1"
    assert buttons[4].text == "5"


# ---------------------------------------------------------------------------
# schedule_times_kb
# ---------------------------------------------------------------------------


def test_times_kb_selected_highlighted() -> None:
    kb = schedule_times_kb({"09:00", "15:00"}, max_count=2)
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert "09:00 *" in texts
    assert "15:00 *" in texts
    assert "10:00" in texts


def test_times_kb_done_shows_count() -> None:
    kb = schedule_times_kb({"09:00"}, max_count=3)
    markup = kb.as_markup()
    texts = [b.text for row in markup.inline_keyboard for b in row]
    assert any("1/3" in t for t in texts)


# ---------------------------------------------------------------------------
# schedule_summary_kb
# ---------------------------------------------------------------------------


def test_summary_kb_buttons() -> None:
    kb = schedule_summary_kb(schedule_id=1, category_id=10, project_id=1)
    markup = kb.as_markup()
    callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
    assert "schedule:1:toggle" in callbacks
    assert "schedule:1:delete" in callbacks
    assert "project:1:scheduler" in callbacks
