"""Router: ScheduleSetupFSM + schedule navigation, toggle, delete.

FSM_SPEC.md: ScheduleSetupFSM (3 states: select_days, select_count, select_times).
"""

import html

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.schedules import SchedulesRepository
from keyboards.schedule import (
    schedule_count_kb,
    schedule_days_kb,
    schedule_summary_kb,
    schedule_times_kb,
    scheduler_category_list_kb,
    scheduler_platform_list_kb,
)
from routers._helpers import guard_callback_message
from services.scheduler import SchedulerService

log = structlog.get_logger()

router = Router(name="publishing_scheduler")


# ---------------------------------------------------------------------------
# FSM definition
# ---------------------------------------------------------------------------


class ScheduleSetupFSM(StatesGroup):
    select_days = State()
    select_count = State()
    select_times = State()


# ---------------------------------------------------------------------------
# Navigation: project -> categories -> platforms
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):scheduler$"))
async def cb_scheduler_categories(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show category list for scheduler."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    categories = await CategoriesRepository(db).get_by_project(project_id)
    if not categories:
        await callback.answer("Сначала добавьте категорию.", show_alert=True)
        return

    await msg.edit_text(
        "Планировщик автопубликаций\n\nВыберите категорию:",
        reply_markup=scheduler_category_list_kb(categories, project_id).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^sched:cat:(\d+)$"))
async def cb_scheduler_platforms(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show platform connections with schedule status for a category."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    category_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]

    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    connections = await ConnectionsRepository(db, cm).get_by_project(project.id)
    schedules = await SchedulesRepository(db).get_by_category(category_id)

    if not connections:
        await callback.answer("Сначала подключите платформу.", show_alert=True)
        return

    await msg.edit_text(
        f"Расписание для «{html.escape(category.name)}»\n\nВыберите платформу:",
        reply_markup=scheduler_platform_list_kb(connections, schedules, category_id, project.id).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: ScheduleSetupFSM (3 steps)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched:cat:(\d+):plt:(\d+)$"))
async def cb_schedule_start(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Start ScheduleSetupFSM: select days."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[2])
    connection_id = int(parts[4])

    # Verify ownership
    category = await CategoriesRepository(db).get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn = await ConnectionsRepository(db, cm).get_by_id(connection_id)
    if not conn or conn.project_id != project.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ScheduleSetupFSM.select_days)
    await state.update_data(
        category_id=category_id,
        connection_id=connection_id,
        platform_type=conn.platform_type,
        project_id=project.id,
        selected_days=[],
    )

    await msg.edit_text(
        "Шаг 1/3. Выберите дни публикации:",
        reply_markup=schedule_days_kb(set()).as_markup(),
    )
    await callback.answer()


@router.callback_query(ScheduleSetupFSM.select_days, F.data.regexp(r"^sched:day:(\w+)$"))
async def cb_schedule_toggle_day(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle day selection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    day = callback.data.split(":")[2]  # type: ignore[union-attr]
    data = await state.get_data()
    selected = set(data.get("selected_days", []))

    if day in selected:
        selected.discard(day)
    else:
        selected.add(day)

    await state.update_data(selected_days=list(selected))
    await msg.edit_reply_markup(reply_markup=schedule_days_kb(selected).as_markup())
    await callback.answer()


@router.callback_query(ScheduleSetupFSM.select_days, F.data == "sched:days:done")
async def cb_schedule_days_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm days selection, move to count."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    selected = set(data.get("selected_days", []))

    if not selected:
        await callback.answer("Выберите хотя бы один день.", show_alert=True)
        return

    await state.set_state(ScheduleSetupFSM.select_count)
    await msg.edit_text(
        "Шаг 2/3. Сколько публикаций в день?",
        reply_markup=schedule_count_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(ScheduleSetupFSM.select_count, F.data.regexp(r"^sched:count:(\d)$"))
async def cb_schedule_count(callback: CallbackQuery, state: FSMContext) -> None:
    """Select posts per day count, move to time selection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    count = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    if count < 1 or count > 5:
        await callback.answer("Выберите от 1 до 5.", show_alert=True)
        return

    await state.update_data(posts_per_day=count, selected_times=[])
    await state.set_state(ScheduleSetupFSM.select_times)
    await msg.edit_text(
        f"Шаг 3/3. Выберите {count} время(-ён) публикации:",
        reply_markup=schedule_times_kb(set(), max_count=count).as_markup(),
    )
    await callback.answer()


@router.callback_query(ScheduleSetupFSM.select_times, F.data.regexp(r"^sched:time:(\d{2}:\d{2})$"))
async def cb_schedule_toggle_time(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle time slot selection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    time_slot = callback.data.split(":time:")[1]  # type: ignore[union-attr]
    data = await state.get_data()
    selected = set(data.get("selected_times", []))
    max_count = data.get("posts_per_day", 1)

    if time_slot in selected:
        selected.discard(time_slot)
    else:
        if len(selected) >= max_count:
            await callback.answer(f"Максимум {max_count} слотов.", show_alert=True)
            return
        selected.add(time_slot)

    await state.update_data(selected_times=list(selected))
    await msg.edit_reply_markup(reply_markup=schedule_times_kb(selected, max_count=max_count).as_markup())
    await callback.answer()


@router.callback_query(ScheduleSetupFSM.select_times, F.data == "sched:times:done")
async def cb_schedule_times_done(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    scheduler_service: SchedulerService,
) -> None:
    """Confirm time selection, create schedule with QStash."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    data = await state.get_data()
    selected_times = sorted(data.get("selected_times", []))
    posts_per_day = data.get("posts_per_day", 1)

    if len(selected_times) != posts_per_day:
        await callback.answer(f"Выберите ровно {posts_per_day} слотов.", show_alert=True)
        return

    await state.clear()

    # Resolve timezone from project
    project = await ProjectsRepository(db).get_by_id(data["project_id"])
    timezone = project.timezone if project else "Europe/Moscow"

    try:
        schedule = await scheduler_service.create_schedule(
            category_id=data["category_id"],
            connection_id=data["connection_id"],
            platform_type=data["platform_type"],
            days=sorted(data.get("selected_days", [])),
            times=selected_times,
            posts_per_day=posts_per_day,
            user_id=user.id,
            project_id=data["project_id"],
            timezone=timezone,
        )
    except Exception:
        log.exception("schedule_create_failed", user_id=user.id)
        await msg.edit_text("Ошибка создания расписания. Попробуйте позже.")
        await callback.answer()
        return

    days_str = ", ".join(sorted(data.get("selected_days", [])))
    times_str = ", ".join(selected_times)
    weekly_cost = SchedulerService.estimate_weekly_cost(
        len(data.get("selected_days", [])), posts_per_day, data["platform_type"]
    )

    await msg.edit_text(
        f"Расписание создано!\n\n"
        f"Дни: {days_str}\n"
        f"Время: {times_str}\n"
        f"Публикаций в день: {posts_per_day}\n"
        f"Примерный расход: ~{weekly_cost} токенов/неделю",
        reply_markup=schedule_summary_kb(schedule.id, data["category_id"], data["project_id"]).as_markup(),
    )
    await callback.answer("Расписание создано!")


# ---------------------------------------------------------------------------
# Schedule management: toggle, delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^schedule:(\d+):toggle$"))
async def cb_schedule_toggle(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    scheduler_service: SchedulerService,
) -> None:
    """Toggle schedule enabled/disabled."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    schedule_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    sched_repo = SchedulesRepository(db)
    schedule = await sched_repo.get_by_id(schedule_id)
    if not schedule:
        await callback.answer("Расписание не найдено.", show_alert=True)
        return

    # Verify ownership
    category = await CategoriesRepository(db).get_by_id(schedule.category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Расписание не найдено.", show_alert=True)
        return

    new_enabled = not schedule.enabled
    try:
        await scheduler_service.toggle_schedule(
            schedule_id,
            new_enabled,
            user.id,
            project.id,
            project.timezone,
        )
    except Exception:
        log.exception("schedule_toggle_failed", schedule_id=schedule_id)
        await callback.answer("Ошибка. Попробуйте позже.", show_alert=True)
        return

    status_text = "включено" if new_enabled else "отключено"
    await callback.answer(f"Расписание {status_text}.")

    # Refresh platform list
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    connections = await ConnectionsRepository(db, cm).get_by_project(project.id)
    schedules = await sched_repo.get_by_category(schedule.category_id)

    await msg.edit_text(
        f"Расписание для «{html.escape(category.name)}»\n\nВыберите платформу:",
        reply_markup=scheduler_platform_list_kb(connections, schedules, schedule.category_id, project.id).as_markup(),
    )


@router.callback_query(F.data.regexp(r"^schedule:(\d+):delete$"))
async def cb_schedule_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    scheduler_service: SchedulerService,
) -> None:
    """Delete schedule with QStash cleanup."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    schedule_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    sched_repo = SchedulesRepository(db)
    schedule = await sched_repo.get_by_id(schedule_id)
    if not schedule:
        await callback.answer("Расписание не найдено.", show_alert=True)
        return

    category = await CategoriesRepository(db).get_by_id(schedule.category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Расписание не найдено.", show_alert=True)
        return

    try:
        await scheduler_service.delete_schedule(schedule_id)
    except Exception:
        log.exception("schedule_delete_failed", schedule_id=schedule_id)
        await callback.answer("Ошибка удаления. Попробуйте позже.", show_alert=True)
        return

    await callback.answer("Расписание удалено.")

    # Refresh platform list
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    connections = await ConnectionsRepository(db, cm).get_by_project(project.id)
    schedules = await sched_repo.get_by_category(schedule.category_id)

    await msg.edit_text(
        f"Расписание для «{html.escape(category.name)}»\n\nВыберите платформу:",
        reply_markup=scheduler_platform_list_kb(connections, schedules, schedule.category_id, project.id).as_markup(),
    )
