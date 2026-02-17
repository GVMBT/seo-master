"""Dashboard, /start, /cancel, navigation callbacks, reply text dispatch."""

import html
import json

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, InlineKeyboardMarkup, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from db.repositories.schedules import SchedulesRepository
from keyboards.inline import admin_panel_kb, dashboard_kb, dashboard_resume_kb
from keyboards.reply import main_menu_kb

log = structlog.get_logger()
router = Router()

# Average article cost for "~N articles" estimate (UX_PIPELINE.md section 2.5)
_AVG_ARTICLE_COST = 320


# ---------------------------------------------------------------------------
# Dashboard builder
# ---------------------------------------------------------------------------


async def _get_platform_flags(
    db: SupabaseClient,
    project_ids: list[int],
) -> tuple[bool, bool]:
    """Return (has_wp, has_social) across given projects."""
    has_wp = False
    has_social = False
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn_repo = ConnectionsRepository(db, cm)
    for pid in project_ids:
        ptypes = await conn_repo.get_platform_types_by_project(pid)
        if "wordpress" in ptypes:
            has_wp = True
        if any(p in ptypes for p in ("telegram", "vk", "pinterest")):
            has_social = True
        if has_wp and has_social:
            break
    return has_wp, has_social


async def _count_active_schedules(
    db: SupabaseClient,
    project_ids: list[int],
) -> int:
    """Count enabled schedules across given projects."""
    cats_repo = CategoriesRepository(db)
    sched_repo = SchedulesRepository(db)
    schedule_count = 0
    for pid in project_ids:
        cats = await cats_repo.get_by_project(pid)
        cat_ids = [c.id for c in cats]
        if cat_ids:
            schedules = await sched_repo.get_by_project(cat_ids)
            schedule_count += sum(1 for s in schedules if s.enabled)
    return schedule_count


def _build_dashboard_text(
    user: User,
    is_new_user: bool,
    project_count: int,
    schedule_count: int,
) -> str:
    """Build Dashboard text based on user state (UX_PIPELINE.md section 2.1-2.3, 2.7)."""
    name = html.escape(user.first_name or "")
    balance = user.balance

    # Balance warning overrides (section 2.7)
    if balance < 0:
        return (
            f"Баланс: {balance} токенов\n"
            f"Долг {abs(balance)} токенов будет списан при следующей покупке.\n"
            "Для генерации контента пополните баланс."
        )
    if balance == 0:
        return "Баланс: 0 токенов\nДля генерации контента нужно пополнить баланс."

    if is_new_user and project_count == 0:
        return (
            f"Привет{', ' + name if name else ''}! "
            "Я помогу создать и опубликовать SEO-контент.\n"
            f"Вам начислено {balance} токенов (~{balance // _AVG_ARTICLE_COST} статей на сайт).\n\n"
            "Что хотите сделать?"
        )
    if project_count > 0:
        articles_estimate = balance // _AVG_ARTICLE_COST
        lines = [f"Баланс: {balance:,} токенов".replace(",", " ")]
        lines.append(f"Проектов: {project_count} | Активных расписаний: {schedule_count}")
        lines.append(f"Хватит на: ~{articles_estimate} статей")
        return "\n".join(lines)

    # Returning user, 0 projects
    return (
        f"Баланс: {balance:,} токенов\n".replace(",", " ") + "У вас пока нет проектов.\n"
        "Создайте первый — это займёт 30 секунд."
    )


async def _build_dashboard(
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build Dashboard text + keyboard based on user state."""
    projects_repo = ProjectsRepository(db)
    projects = await projects_repo.get_by_user(user.id)
    project_count = len(projects)
    project_ids = [p.id for p in projects]

    has_wp = False
    has_social = False
    schedule_count = 0
    if project_count > 0:
        has_wp, has_social = await _get_platform_flags(db, project_ids)
        schedule_count = await _count_active_schedules(db, project_ids)

    text = _build_dashboard_text(user, is_new_user, project_count, schedule_count)

    # Check pipeline checkpoint (section 2.6)
    checkpoint_text = await _get_checkpoint_text(redis, user.id)

    kb = dashboard_kb(
        has_wp=has_wp,
        has_social=has_social,
        balance=user.balance,
    )

    if checkpoint_text:
        text += checkpoint_text
        return text, dashboard_resume_kb()

    return text, kb


async def _get_checkpoint_text(redis: RedisClient, user_id: int) -> str:
    """Get pipeline checkpoint resume text, or empty string."""
    checkpoint_raw = await redis.get(CacheKeys.pipeline_state(user_id))
    if not checkpoint_raw:
        return ""
    try:
        checkpoint = json.loads(checkpoint_raw)
        project_name = html.escape(checkpoint.get("project_name", ""))
        step = checkpoint.get("step_label", "подготовка")
        return f"\n\nУ вас есть незавершённая статья:\nПроект: {project_name}\nОстановились на: {step}"
    except (json.JSONDecodeError, TypeError):
        return ""


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    is_admin: bool,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Handle /start command — show Dashboard."""
    await ensure_no_active_fsm(state)

    # Parse deep link args
    args = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if args.startswith("referrer_"):
        log.info("deep_link_referral", referrer_arg=args)
        # Referral tracking handled by AuthMiddleware on user creation
    elif args.startswith("pinterest_auth_"):
        log.info("deep_link_pinterest", nonce_arg=args)
        # TODO Phase F2: handle Pinterest OAuth callback

    text, kb = await _build_dashboard(user, is_new_user, db, redis)
    if is_new_user:
        # First interaction: set persistent reply keyboard
        await message.answer(text, reply_markup=main_menu_kb(is_admin))
    else:
        await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# /cancel command
# ---------------------------------------------------------------------------


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    is_admin: bool,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Handle /cancel — clear FSM + show Dashboard."""
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await message.answer(f"Процесс ({interrupted}) отменён.")

    text, kb = await _build_dashboard(user, is_new_user, db, redis)
    await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# Navigation callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:dashboard")
async def nav_dashboard(
    callback: CallbackQuery,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Navigate to Dashboard via editMessageText."""
    text, kb = await _build_dashboard(user, is_new_user, db, redis)
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


## nav:projects is handled by routers/projects/list.py
## nav:profile is handled by routers/profile.py
## nav:tokens is handled by routers/tariffs.py


# ---------------------------------------------------------------------------
# Pipeline stubs
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:article:start")
async def pipeline_article_start(callback: CallbackQuery) -> None:
    """Stub: Article pipeline — coming in Phase F5."""
    await callback.answer("Статьи — скоро!", show_alert=True)


@router.callback_query(F.data == "pipeline:social:start")
async def pipeline_social_start(callback: CallbackQuery) -> None:
    """Stub: Social pipeline — coming in Phase F5."""
    await callback.answer("Посты — скоро!", show_alert=True)


@router.callback_query(F.data == "pipeline:resume")
async def pipeline_resume(callback: CallbackQuery) -> None:
    """Stub: Resume pipeline — coming in Phase F5."""
    await callback.answer("Возобновление — скоро!", show_alert=True)


@router.callback_query(F.data == "pipeline:restart")
async def pipeline_restart(callback: CallbackQuery) -> None:
    """Stub: Restart pipeline — coming in Phase F5."""
    await callback.answer("Перезапуск — скоро!", show_alert=True)


@router.callback_query(F.data == "pipeline:cancel")
async def pipeline_cancel(callback: CallbackQuery, redis: RedisClient, user: User) -> None:
    """Cancel active pipeline checkpoint."""
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await callback.answer("Pipeline отменён.")
    if callback.message and not isinstance(callback.message, InaccessibleMessage):
        await callback.message.delete()


@router.callback_query(F.data.startswith("pipeline:"))
async def pipeline_stale_catchall(callback: CallbackQuery) -> None:
    """Catch-all for stale pipeline callbacks after FSM timeout/cancel.

    Without this, clicks on old pipeline keyboards silently drop
    (no handler matches without FSM state) → "spinning clock" forever.
    """
    await callback.answer("Сессия завершена. Начните заново.", show_alert=True)


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery) -> None:
    """No-op callback for pagination counters and spacer buttons."""
    await callback.answer()


# ---------------------------------------------------------------------------
# Reply text dispatch (persistent keyboard)
# ---------------------------------------------------------------------------


@router.message(F.text == "АДМИНКА")
async def admin_entry(message: Message, user: User) -> None:
    """Admin panel entry via reply keyboard."""
    if user.role != "admin":
        return  # Silently ignore for non-admins
    await message.answer(
        "<b>Админ-панель</b>",
        reply_markup=admin_panel_kb(),
    )


@router.message(F.text == "Меню")
async def reply_menu(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    is_admin: bool,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Reply keyboard: Menu button → Dashboard."""
    await ensure_no_active_fsm(state)
    text, kb = await _build_dashboard(user, is_new_user, db, redis)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == "Написать статью")
async def reply_article(message: Message, state: FSMContext) -> None:
    """Reply keyboard: Write Article → stub."""
    await ensure_no_active_fsm(state)
    await message.answer("Статьи — скоро! Используйте Dashboard.")


@router.message(F.text == "Создать пост")
async def reply_social(message: Message, state: FSMContext) -> None:
    """Reply keyboard: Create Post → stub."""
    await ensure_no_active_fsm(state)
    await message.answer("Посты — скоро! Используйте Dashboard.")


@router.message(F.text == "Отмена")
async def reply_cancel(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    is_admin: bool,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Reply keyboard: Cancel → clear FSM, show Dashboard."""
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await message.answer(f"Процесс ({interrupted}) отменён.")
    text, kb = await _build_dashboard(user, is_new_user, db, redis)
    await message.answer(text, reply_markup=kb)
