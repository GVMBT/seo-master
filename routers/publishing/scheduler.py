"""Scheduler: presets, manual FSM (ScheduleSetupFSM), disable (UX_TOOLBOX section 13)."""

import html as html_mod

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_message
from db.models import User
from keyboards.inline import (
    _DAY_LABELS,
    _PRESETS,
    schedule_count_kb,
    schedule_days_kb,
    schedule_times_kb,
    scheduler_cat_list_kb,
    scheduler_config_kb,
    scheduler_conn_list_kb,
    scheduler_crosspost_kb,
    scheduler_social_cat_list_kb,
    scheduler_social_config_kb,
    scheduler_social_conn_list_kb,
)
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()


def _extract_selected_from_keyboard(
    markup: InlineKeyboardMarkup | None,
) -> list[int]:
    """Extract selected connection IDs from cross-post keyboard checkmarks."""
    if not markup:
        return []
    selected: list[int] = []
    for row in markup.inline_keyboard:
        for btn in row:
            if btn.callback_data and btn.callback_data.endswith(":toggle") and btn.text.startswith("\u2713"):
                parts = btn.callback_data.split(":")
                if len(parts) >= 4:
                    selected.append(int(parts[3]))
    return selected


class ScheduleSetupFSM(StatesGroup):
    select_days = State()
    select_count = State()
    select_times = State()


# ---------------------------------------------------------------------------
# Entry: from nav:scheduler (pipeline result screen, H4 fix)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:scheduler")
async def nav_scheduler(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Navigate to scheduler from pipeline result (no project context).

    If user has 1 project — go directly to its scheduler.
    If multiple — show project selection list.
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    projects = await scheduler_service.get_user_projects(user.id)
    if not projects:
        await callback.answer(
            "Сначала создайте проект в \U0001f4cb Меню \u2192 \U0001f4c1 Мои проекты",
            show_alert=True,
        )
        return

    if len(projects) == 1:
        project = projects[0]
        cats = await scheduler_service.get_project_categories(project.id, user.id)
        if not cats:
            await callback.answer("Сначала создайте категорию в карточке проекта", show_alert=True)
            return
        await msg.edit_text(
            "<b>Статьи — Планировщик</b>\n\nВыберите категорию:",
            reply_markup=scheduler_cat_list_kb(cats, project.id),
        )
        await callback.answer()
        return

    # Multiple projects — show selection
    rows: list[list[InlineKeyboardButton]] = []
    for p in projects:
        rows.append(
            [
                InlineKeyboardButton(
                    text=p.name,
                    callback_data=f"project:{p.id}:scheduler",
                ),
            ]
        )
    rows.append([InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard")])
    await msg.edit_text(
        "<b>Планировщик</b>\n\nВыберите проект:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Entry: from project card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:scheduler$"))
async def scheduler_entry(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Legacy entry — redirect to articles scheduler."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cats = await scheduler_service.get_project_categories(project_id, user.id)
    if cats is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    if not cats:
        await callback.answer("Сначала создайте категорию в карточке проекта", show_alert=True)
        return

    await msg.edit_text(
        "<b>Статьи — Планировщик</b>\n\nВыберите категорию:",
        reply_markup=scheduler_cat_list_kb(cats, project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^project:\d+:sched_articles$"))
async def scheduler_articles_entry(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Articles scheduler entry — filters WP-only connections downstream."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cats = await scheduler_service.get_project_categories(project_id, user.id)
    if cats is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    if not cats:
        await callback.answer("Сначала создайте категорию в карточке проекта", show_alert=True)
        return

    await msg.edit_text(
        "<b>Статьи — Планировщик</b>\n\nВыберите категорию:",
        reply_markup=scheduler_cat_list_kb(cats, project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^project:\d+:sched_social$"))
async def scheduler_social_entry(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Social scheduler entry — filters social connections."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    social_conns = await scheduler_service.get_social_connections(project_id, user.id)
    if social_conns is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    if not social_conns:
        await callback.answer("Нет подключённых соцсетей", show_alert=True)
        return

    cats = await scheduler_service.get_project_categories(project_id, user.id)
    if not cats:
        await callback.answer("Сначала создайте категорию в карточке проекта", show_alert=True)
        return

    await msg.edit_text(
        "<b>Соцсети — Планировщик</b>\n\nВыберите категорию:",
        reply_markup=scheduler_social_cat_list_kb(cats, project_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Category -> connections list
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^scheduler:\d+:cat:\d+$"))
async def scheduler_category(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Show connections with schedule summaries."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[1])
    cat_id = int(parts[3])

    connections = await scheduler_service.get_project_connections(project_id, user.id)
    if connections is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    if not connections:
        await callback.answer("Нет подключений. Добавьте платформу.", show_alert=True)
        return

    schedules_map = await scheduler_service.get_category_schedules_map(cat_id)

    await msg.edit_text(
        "<b>Подключения</b>\n\nВыберите подключение для настройки расписания:",
        reply_markup=scheduler_conn_list_kb(connections, schedules_map, cat_id, project_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Back to connection list from config
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^scheduler:\d+:conn_list$"))
async def scheduler_conn_list_back(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Navigate back to connection list -- reconstruct category context."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    ctx = await scheduler_service.verify_category_ownership(cat_id, user.id)
    if not ctx:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    connections = await scheduler_service.get_project_connections(ctx.project.id, user.id)
    schedules_map = await scheduler_service.get_category_schedules_map(cat_id)

    await msg.edit_text(
        "<b>Подключения</b>\n\nВыберите подключение для настройки расписания:",
        reply_markup=scheduler_conn_list_kb(connections or [], schedules_map, cat_id, ctx.project.id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Connection -> config screen
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^scheduler:\d+:conn:\d+$"))
async def scheduler_connection(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Show schedule config for a connection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[3])

    ctx = await scheduler_service.verify_category_ownership(cat_id, user.id)
    if not ctx:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    schedules_map = await scheduler_service.get_category_schedules_map(cat_id)
    existing = schedules_map.get(conn_id)

    text = "<b>Настройка расписания</b>\n\n"
    if existing and existing.enabled:
        days_str = ", ".join(_DAY_LABELS.get(d, d) for d in existing.schedule_days)
        times_str = ", ".join(existing.schedule_times)
        text += f"Текущее расписание:\nДни: {days_str}\nВремя: {times_str}\nПостов/день: {existing.posts_per_day}\n\n"
    text += "Выберите вариант:"

    await msg.edit_text(
        text,
        reply_markup=scheduler_config_kb(
            cat_id,
            conn_id,
            existing is not None and existing.enabled,
            schedule_days=existing.schedule_days if existing and existing.enabled else None,
            posts_per_day=existing.posts_per_day if existing and existing.enabled else 0,
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Preset schedule
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched:\d+:\d+:preset:(1w|3w|daily)$"))
async def scheduler_preset(
    callback: CallbackQuery,
    user: User,
    scheduler_service: SchedulerService,
) -> None:
    """Apply preset schedule."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[2])
    preset_key = parts[4]

    preset = _PRESETS[preset_key]
    days, times, posts_per_day = preset[1], preset[2], preset[3]

    try:
        result = await scheduler_service.apply_schedule(
            cat_id, conn_id, user.id, days, times, posts_per_day,
        )
    except Exception:
        log.exception("preset_schedule_creation_failed", cat_id=cat_id, conn_id=conn_id, preset=preset_key)
        await callback.answer("Ошибка создания расписания", show_alert=True)
        return

    if not result:
        await callback.answer("Категория или подключение не найдены", show_alert=True)
        return

    await msg.edit_text(
        f"Расписание установлено!\n\n"
        f"Подключение: {result.connection.identifier}\n"
        f"Режим: {preset[0]}\n"
        f"Ориент. расход: ~{result.weekly_cost} токенов/нед",
        reply_markup=scheduler_config_kb(
            cat_id,
            conn_id,
            has_schedule=True,
            schedule_days=days,
            posts_per_day=posts_per_day,
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Disable schedule
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched:\d+:\d+:disable$"))
async def scheduler_disable(
    callback: CallbackQuery,
    user: User,
    scheduler_service: SchedulerService,
) -> None:
    """Disable and delete schedule."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[2])

    ok = await scheduler_service.disable_connection_schedule(cat_id, conn_id, user.id)
    if not ok:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    await msg.edit_text(
        "Расписание отключено.",
        reply_markup=scheduler_config_kb(cat_id, conn_id, has_schedule=False),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Manual setup entry -> FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched:\d+:\d+:manual$"))
async def scheduler_manual(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService, state: FSMContext,
) -> None:
    """Enter manual schedule setup FSM."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[2])

    # Verify ownership (callback_data tampering protection)
    ctx = await scheduler_service.verify_category_ownership(cat_id, user.id)
    if not ctx:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Check if schedule already exists (to restore button state on cancel)
    sched_has_schedule = await scheduler_service.has_active_schedule(cat_id, conn_id)

    await state.update_data(
        sched_cat_id=cat_id,
        sched_conn_id=conn_id,
        sched_days=[],
        sched_has_schedule=sched_has_schedule,
    )
    await state.set_state(ScheduleSetupFSM.select_days)

    await msg.edit_text(
        "<b>Настройка расписания</b>\n\nВыберите дни публикации:",
        reply_markup=schedule_days_kb(set()),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: toggle day
# ---------------------------------------------------------------------------


@router.callback_query(
    ScheduleSetupFSM.select_days,
    F.data.regexp(r"^sched:day:(mon|tue|wed|thu|fri|sat|sun)$"),
)
async def schedule_day_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle day selection in FSM."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    day = callback.data.split(":")[-1]  # type: ignore[union-attr]
    data = await state.get_data()
    selected: set[str] = set(data.get("sched_days", []))

    if day in selected:
        selected.discard(day)
    else:
        selected.add(day)

    await state.update_data(sched_days=sorted(selected))
    await msg.edit_reply_markup(reply_markup=schedule_days_kb(selected))
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: days done
# ---------------------------------------------------------------------------


@router.callback_query(ScheduleSetupFSM.select_days, F.data == "sched:days:done")
async def schedule_days_done(callback: CallbackQuery, state: FSMContext) -> None:
    """Validate at least 1 day selected, move to count."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    selected = data.get("sched_days", [])

    if not selected:
        await callback.answer("Выберите хотя бы один день", show_alert=True)
        return

    await state.set_state(ScheduleSetupFSM.select_count)
    await msg.edit_text(
        "<b>Настройка расписания</b>\n\nСколько постов в день?",
        reply_markup=schedule_count_kb(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: count select
# ---------------------------------------------------------------------------


@router.callback_query(ScheduleSetupFSM.select_count, F.data.regexp(r"^sched:count:[1-5]$"))
async def schedule_count_select(callback: CallbackQuery, state: FSMContext) -> None:
    """Store count, move to time selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    count = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    await state.update_data(sched_count=count, sched_times=[])
    await state.set_state(ScheduleSetupFSM.select_times)

    await msg.edit_text(
        f"<b>Настройка расписания</b>\n\nВыберите {count} временных слотов:",
        reply_markup=schedule_times_kb(set(), count),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: toggle time
# ---------------------------------------------------------------------------


@router.callback_query(ScheduleSetupFSM.select_times, F.data.regexp(r"^sched:time:\d{2}:00$"))
async def schedule_time_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle time slot selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # callback_data = "sched:time:10:00" -> extract "10:00"
    parts = callback.data.split(":")  # type: ignore[union-attr]
    time_str = f"{parts[2]}:{parts[3]}"

    data = await state.get_data()
    selected: set[str] = set(data.get("sched_times", []))
    required: int = data.get("sched_count", 1)

    if time_str in selected:
        selected.discard(time_str)
    elif len(selected) < required:
        selected.add(time_str)
    else:
        await callback.answer(f"Максимум {required} слотов", show_alert=True)
        return

    await state.update_data(sched_times=sorted(selected))
    await msg.edit_reply_markup(reply_markup=schedule_times_kb(selected, required))
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: times done -> save
# ---------------------------------------------------------------------------


@router.callback_query(ScheduleSetupFSM.select_times, F.data == "sched:times:done")
async def schedule_times_done(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    scheduler_service: SchedulerService,
) -> None:
    """Validate time count, create schedule."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    selected_times: list[str] = sorted(data.get("sched_times", []))
    required: int = data.get("sched_count", 1)

    if len(selected_times) != required:
        await callback.answer(f"Выберите ровно {required} слотов", show_alert=True)
        return

    cat_id: int = data["sched_cat_id"]
    conn_id: int = data["sched_conn_id"]
    selected_days: list[str] = sorted(data.get("sched_days", []))

    try:
        result = await scheduler_service.apply_schedule(
            cat_id, conn_id, user.id, selected_days, selected_times, required,
        )
    except Exception:
        log.exception("manual_schedule_creation_failed", cat_id=cat_id, conn_id=conn_id)
        await callback.answer("Ошибка создания расписания", show_alert=True)
        await state.clear()
        return

    if not result:
        await callback.answer("Категория или подключение не найдены", show_alert=True)
        await state.clear()
        return

    await state.clear()

    days_str = ", ".join(_DAY_LABELS.get(d, d) for d in selected_days)
    times_str = ", ".join(selected_times)

    await msg.edit_text(
        f"Расписание установлено!\n\n"
        f"Дни: {days_str}\n"
        f"Время: {times_str}\n"
        f"Постов/день: {required}\n"
        f"Ориент. расход: ~{result.weekly_cost} токенов/нед",
        reply_markup=scheduler_config_kb(
            cat_id,
            conn_id,
            has_schedule=True,
            schedule_days=list(selected_days),
            posts_per_day=required,
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Social: connection list for category
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched_social:\d+:cat:\d+$"))
async def scheduler_social_category(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Show social connections with schedule summaries for a category."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    project_id = int(parts[1])
    cat_id = int(parts[3])

    social_conns = await scheduler_service.get_social_connections(project_id, user.id)
    if social_conns is None:
        await callback.answer("Проект не найден", show_alert=True)
        return
    if not social_conns:
        await callback.answer("Нет подключённых соцсетей", show_alert=True)
        return

    schedules_map = await scheduler_service.get_category_schedules_map(cat_id)

    await msg.edit_text(
        "<b>Соцсети — Подключения</b>\n\nВыберите подключение для настройки расписания:",
        reply_markup=scheduler_social_conn_list_kb(social_conns, schedules_map, cat_id, project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^scheduler:\d+:social_conn_list$"))
async def scheduler_social_conn_list_back(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Navigate back to social connection list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cat_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    ctx = await scheduler_service.verify_category_ownership(cat_id, user.id)
    if not ctx:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    social_conns = await scheduler_service.get_social_connections(ctx.project.id, user.id)
    schedules_map = await scheduler_service.get_category_schedules_map(cat_id)

    await msg.edit_text(
        "<b>Соцсети — Подключения</b>\n\nВыберите подключение для настройки расписания:",
        reply_markup=scheduler_social_conn_list_kb(social_conns or [], schedules_map, cat_id, ctx.project.id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Social: connection config
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched_social:\d+:conn:\d+$"))
async def scheduler_social_connection(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Show social schedule config with cross-post option."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[3])

    ctx = await scheduler_service.verify_category_ownership(cat_id, user.id)
    if not ctx:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    schedules_map = await scheduler_service.get_category_schedules_map(cat_id)
    existing = schedules_map.get(conn_id)

    social_conns = await scheduler_service.get_social_connections(ctx.project.id, user.id)
    has_other_social = len(social_conns or []) > 1

    text = "<b>Настройка расписания (соцсети)</b>\n\n"
    if existing and existing.enabled:
        days_str = ", ".join(_DAY_LABELS.get(d, d) for d in existing.schedule_days)
        times_str = ", ".join(existing.schedule_times)
        text += f"Текущее расписание:\nДни: {days_str}\nВремя: {times_str}\nПостов/день: {existing.posts_per_day}\n"
        if existing.cross_post_connection_ids:
            text += f"Кросс-постинг: {len(existing.cross_post_connection_ids)} платформ\n"
        text += "\n"
    text += "Выберите вариант:"

    await msg.edit_text(
        text,
        reply_markup=scheduler_social_config_kb(
            cat_id,
            conn_id,
            existing is not None and existing.enabled,
            has_other_social,
            schedule_days=existing.schedule_days if existing and existing.enabled else None,
            posts_per_day=existing.posts_per_day if existing and existing.enabled else 0,
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Cross-post config
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^sched_xp:\d+:\d+:config$"))
async def scheduler_crosspost_config(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Show cross-post toggle screen."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[2])

    config = await scheduler_service.get_crosspost_config(cat_id, conn_id, user.id)
    if not config:
        await callback.answer("Категория или подключение не найдены", show_alert=True)
        return

    lead_name = html_mod.escape(config.lead_connection.identifier)
    text = (
        f"<b>Кросс-постинг</b>\n\n"
        f"Ведущая платформа: {config.lead_connection.platform_type.capitalize()} ({lead_name})\n\n"
        "Выберите платформы для автоматической адаптации поста.\n"
        "Стоимость: ~10 ток/пост за кросс-пост."
    )

    await msg.edit_text(
        text,
        reply_markup=scheduler_crosspost_kb(
            cat_id, conn_id, config.social_connections, config.selected_ids,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^sched_xp:\d+:\d+:\d+:toggle$"))
async def scheduler_crosspost_toggle(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Toggle a cross-post target connection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[2])
    target_conn_id = int(parts[3])

    social_conns = await scheduler_service.get_social_connections_by_category(cat_id, user.id)
    if social_conns is None:
        await callback.answer("Категория не найдена", show_alert=True)
        return

    # P0-3: verify target_conn_id belongs to this project's social connections
    project_conn_ids = {c.id for c in social_conns}
    if target_conn_id not in project_conn_ids:
        await callback.answer("Подключение не найдено", show_alert=True)
        return

    # P0-2: read current selection from keyboard markup, not DB (avoids losing intermediate toggles)
    selected_ids: list[int] = _extract_selected_from_keyboard(msg.reply_markup)

    if target_conn_id in selected_ids:
        selected_ids.remove(target_conn_id)
    else:
        selected_ids.append(target_conn_id)

    await msg.edit_reply_markup(
        reply_markup=scheduler_crosspost_kb(cat_id, conn_id, social_conns, selected_ids),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^sched_xp:\d+:\d+:save$"))
async def scheduler_crosspost_save(
    callback: CallbackQuery, user: User, scheduler_service: SchedulerService,
) -> None:
    """Save cross_post_connection_ids to schedule."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    cat_id = int(parts[1])
    conn_id = int(parts[2])

    selected_ids = _extract_selected_from_keyboard(msg.reply_markup)

    result = await scheduler_service.update_crosspost(cat_id, conn_id, user.id, selected_ids)
    if not result:
        await callback.answer("Расписание не найдено", show_alert=True)
        return

    result_msg = (
        f"Кросс-постинг сохранён: {result.count} платформ."
        if result.count
        else "Кросс-постинг отключён."
    )

    await msg.edit_text(
        result_msg,
        reply_markup=scheduler_social_config_kb(
            cat_id,
            conn_id,
            has_schedule=True,
            has_other_social=result.has_other_social,
            schedule_days=result.schedule.schedule_days,
            posts_per_day=result.schedule.posts_per_day,
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: cancel
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "sched:cancel", ScheduleSetupFSM.select_days)
@router.callback_query(F.data == "sched:cancel", ScheduleSetupFSM.select_count)
@router.callback_query(F.data == "sched:cancel", ScheduleSetupFSM.select_times)
async def schedule_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel manual schedule setup, return to connection config."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    cat_id = data.get("sched_cat_id")
    conn_id = data.get("sched_conn_id")
    has_schedule = data.get("sched_has_schedule", False)
    await state.clear()

    if cat_id and conn_id:
        await msg.edit_text(
            "Настройка расписания отменена.",
            reply_markup=scheduler_config_kb(int(cat_id), int(conn_id), has_schedule=bool(has_schedule)),
        )
    else:
        await msg.edit_text("Настройка расписания отменена.")
    await callback.answer()
