"""Keyboard builders for ScheduleSetup flow.

6 builders: category list, platform list, days toggle, count select,
time slots toggle, schedule summary.
"""

from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Category, PlatformConnection, PlatformSchedule

# Day labels (short form for callbacks, display Russian names)
_DAYS = [
    ("mon", "Пн"),
    ("tue", "Вт"),
    ("wed", "Ср"),
    ("thu", "Чт"),
    ("fri", "Пт"),
    ("sat", "Сб"),
    ("sun", "Вс"),
]

# Time slots: 06:00 to 23:00
_TIME_SLOTS = [f"{h:02d}:00" for h in range(6, 24)]

# Platform display names
_PLATFORM_NAMES: dict[str, str] = {
    "wordpress": "WP",
    "telegram": "TG",
    "vk": "VK",
    "pinterest": "Pin",
}


def scheduler_category_list_kb(
    categories: list[Category],
    project_id: int,
) -> InlineKeyboardBuilder:
    """Category list for scheduler entry point."""
    builder = InlineKeyboardBuilder()
    for cat in categories:
        name = cat.name[:40] + "..." if len(cat.name) > 40 else cat.name
        builder.button(text=name, callback_data=f"sched:cat:{cat.id}")
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder


def scheduler_platform_list_kb(
    connections: list[PlatformConnection],
    schedules: list[PlatformSchedule],
    category_id: int,
    project_id: int,
) -> InlineKeyboardBuilder:
    """Platform connections with schedule status indicators."""
    builder = InlineKeyboardBuilder()

    # Build schedule lookup by connection_id
    sched_by_conn: dict[int, PlatformSchedule] = {}
    for s in schedules:
        sched_by_conn[s.connection_id] = s

    for conn in connections:
        platform = _PLATFORM_NAMES.get(conn.platform_type, conn.platform_type)
        identifier = conn.identifier[:20] + "..." if len(conn.identifier) > 20 else conn.identifier
        sched = sched_by_conn.get(conn.id)
        if sched and sched.enabled:
            status = " [ON]"
        elif sched:
            status = " [OFF]"
        else:
            status = ""
        text = f"{platform}: {identifier}{status}"
        builder.button(text=text, callback_data=f"sched:cat:{category_id}:plt:{conn.id}")

    builder.button(text="К планировщику", callback_data=f"project:{project_id}:scheduler")
    builder.adjust(1)
    return builder


def schedule_days_kb(selected: set[str]) -> InlineKeyboardBuilder:
    """7 day toggle buttons + [Готово]. Layout: 7 + 1."""
    builder = InlineKeyboardBuilder()
    for day_code, day_name in _DAYS:
        marker = " *" if day_code in selected else ""
        builder.button(text=f"{day_name}{marker}", callback_data=f"sched:day:{day_code}")
    builder.button(text="Готово", callback_data="sched:days:done")
    builder.adjust(7, 1)
    return builder


def schedule_count_kb() -> InlineKeyboardBuilder:
    """Posts per day: [1][2][3][4][5]. Layout: 5."""
    builder = InlineKeyboardBuilder()
    for n in range(1, 6):
        builder.button(text=str(n), callback_data=f"sched:count:{n}")
    builder.adjust(5)
    return builder


def schedule_times_kb(
    selected: set[str],
    max_count: int,
) -> InlineKeyboardBuilder:
    """18 time slot toggles (06:00-23:00) + [Готово]. Layout: 6x3 + 1."""
    builder = InlineKeyboardBuilder()
    for slot in _TIME_SLOTS:
        marker = " *" if slot in selected else ""
        builder.button(text=f"{slot}{marker}", callback_data=f"sched:time:{slot}")
    builder.button(text=f"Готово ({len(selected)}/{max_count})", callback_data="sched:times:done")
    builder.adjust(6, 6, 6, 1)
    return builder


def schedule_summary_kb(
    schedule_id: int,
    category_id: int,
    project_id: int,
) -> InlineKeyboardBuilder:
    """Summary: [Отключить] [К планировщику]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Отключить", callback_data=f"schedule:{schedule_id}:toggle")
    builder.button(text="Удалить", callback_data=f"schedule:{schedule_id}:delete")
    builder.button(text="К планировщику", callback_data=f"project:{project_id}:scheduler")
    builder.adjust(2, 1)
    return builder
