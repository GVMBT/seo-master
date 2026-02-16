"""Router: /start, /cancel, /help, main menu dashboard, reply button dispatch."""

import json
import math
import re

import httpx
import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import User, UserUpdate
from db.repositories.projects import ProjectsRepository
from db.repositories.users import UsersRepository
from keyboards.inline import dashboard_kb
from keyboards.reply import main_menu
from routers._helpers import guard_callback_message
from services.tokens import TokenService

log = structlog.get_logger()

router = Router(name="start")

# ---------------------------------------------------------------------------
# Help text (shared between /help command and help:main callback)
# ---------------------------------------------------------------------------

_HELP_TEXT = (
    "SEO Master Bot — AI-генерация контента для вашего сайта.\n\n"
    "Как начать:\n"
    "1. Создайте проект (название, компания, сайт)\n"
    "2. Добавьте категорию и ключевые фразы\n"
    "3. Нажмите «Написать статью»\n\n"
    "Команды:\n"
    "/start — главное меню\n"
    "/cancel — отменить текущее действие\n"
    "/help — эта справка"
)


# ---------------------------------------------------------------------------
# Dashboard text builder
# ---------------------------------------------------------------------------


async def _build_dashboard_text(user: User, db: SupabaseClient, is_new_user: bool = False) -> str:
    """Build main menu dashboard text with stats.

    Three variants (PIPELINE_UX_PROPOSAL.md section 3.1, section 16.5):
    - New user: welcome + token grant + CTA
    - Returning without projects: balance + CTA
    - Returning with projects: balance + stats + articles_left forecast
    """
    if is_new_user:
        return (
            "Добро пожаловать в SEO Master Bot!\n\n"
            "Я создаю SEO-статьи и посты для вашего бизнеса "
            "с помощью AI и публикую на сайт.\n\n"
            "Вам начислено 1500 токенов (~5 статей).\n"
            "Начните с создания проекта."
        )

    service = TokenService(db, admin_ids=get_settings().admin_ids)
    stats = await service.get_profile_stats(user)

    if stats["project_count"] == 0:
        return f"Баланс: {user.balance} токенов\n\nУ вас пока нет проектов.\nСоздайте первый — это займёт 30 секунд."

    # Default avg article cost: ~320 tokens (2000 words + 4 images)
    avg_article_cost = 320
    articles_left = math.floor(user.balance / avg_article_cost) if avg_article_cost > 0 else 0

    lines = [f"Баланс: {user.balance} токенов", ""]
    lines.append(f"Проектов: {stats['project_count']} | Категорий: {stats['category_count']}")
    if stats["schedule_count"] > 0:
        lines.append(f"Расписаний: {stats['schedule_count']} | Постов/нед: {stats['posts_per_week']}")
    lines.append(f"Хватит на: ~{articles_left} статей")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /start (with optional deep link: ref_{id}, pinterest_auth_{nonce})
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r"^ref_(\d+)$")


async def _send_dashboard(
    message: Message,
    user: User,
    db: SupabaseClient,
    is_new_user: bool = False,
    redis: RedisClient | None = None,
) -> None:
    """Send dashboard: restore reply-KB + dashboard with inline navigation.

    Two messages because Telegram API doesn't allow mixing
    ReplyKeyboardMarkup and InlineKeyboardMarkup in one message.

    Pipeline checkpoint check (section 16.10): if the user has an interrupted
    pipeline session in Redis, show a resume prompt before the dashboard.
    """
    # 1. Restore compact reply keyboard (Menu + Write Article)
    await message.answer(
        "Используйте кнопки ниже для быстрого доступа.",
        reply_markup=main_menu(is_admin=user.role == "admin"),
    )

    # 2. Check pipeline checkpoint (section 16.10, E49)
    if redis and not is_new_user:
        checkpoint_raw = await redis.get(CacheKeys.pipeline_state(user.id))
        if checkpoint_raw:
            checkpoint: dict[str, object] = json.loads(checkpoint_raw)
            from keyboards.pipeline import pipeline_resume_kb

            project_name = "?"
            project_id = checkpoint.get("project_id")
            if project_id and isinstance(project_id, int):
                project = await ProjectsRepository(db).get_by_id(project_id)
                if project and project.user_id == user.id:
                    project_name = project.name
                else:
                    # Checkpoint references a project the user no longer owns --
                    # clean up the stale checkpoint and skip resume prompt.
                    await redis.delete(CacheKeys.pipeline_state(user.id))
                    project_name = ""
            if project_name:
                current_step = checkpoint.get("current_step", "?")
                await message.answer(
                    f"У вас есть незавершённая статья:\nПроект: {project_name}\nОстановились на: {current_step}\n",
                    reply_markup=pipeline_resume_kb().as_markup(),
                )

    # 3. Dashboard with inline navigation
    text = await _build_dashboard_text(user, db, is_new_user=is_new_user)
    await message.answer(text, reply_markup=dashboard_kb().as_markup())


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    is_new_user: bool = False,
) -> None:
    """Handle /start with deep link payload (referral, Pinterest OAuth stub)."""
    await state.clear()

    payload = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""

    # Referral: /start ref_12345
    match = _REF_RE.match(payload)
    if match:
        referrer_id = int(match.group(1))
        repo = UsersRepository(db)
        # Validate referrer exists (P4.2), one-time, no self-referral
        referrer = await repo.get_by_id(referrer_id)
        if referrer and user.referrer_id is None and referrer_id != user.id:
            await repo.update(user.id, UserUpdate(referrer_id=referrer_id))

    # Pinterest OAuth: /start pinterest_auth_{nonce}
    if payload.startswith("pinterest_auth_"):
        from routers.platforms.connections import handle_pinterest_deep_link

        await handle_pinterest_deep_link(message, state, user, db, redis, http_client, payload)
        return

    await _send_dashboard(message, user, db, is_new_user=is_new_user, redis=redis)


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    is_new_user: bool = False,
) -> None:
    """Handle plain /start — clear FSM, show dashboard."""
    await state.clear()
    await _send_dashboard(message, user, db, is_new_user=is_new_user, redis=redis)


# ---------------------------------------------------------------------------
# /cancel — global, any FSM state
# ---------------------------------------------------------------------------


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext, user: User) -> None:
    """Cancel any active FSM and return to main menu."""
    current = await state.get_state()
    await state.clear()
    if current is not None:
        await message.answer("Действие отменено.", reply_markup=main_menu(is_admin=user.role == "admin"))
    else:
        await message.answer("Нет активного действия.", reply_markup=main_menu(is_admin=user.role == "admin"))


@router.message(F.text == "Отмена", StateFilter("*"))
async def btn_cancel(message: Message, state: FSMContext, user: User) -> None:
    """Reply keyboard [Отмена] button — same as /cancel."""
    current = await state.get_state()
    if current is not None:
        await state.clear()
        await message.answer("Действие отменено.", reply_markup=main_menu(is_admin=user.role == "admin"))
    else:
        await message.answer("Нет активного действия.", reply_markup=main_menu(is_admin=user.role == "admin"))


# ---------------------------------------------------------------------------
# /help
# ---------------------------------------------------------------------------


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """Show help text via /help command."""
    await message.answer(_HELP_TEXT)


# ---------------------------------------------------------------------------
# menu:main callback (inline button → dashboard)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "menu:main")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Return to main menu via inline button. Edits message to dashboard.

    Reply keyboard is already set — no need to send a second message.
    """
    await state.clear()
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    text = await _build_dashboard_text(user, db)
    await msg.edit_text(text, reply_markup=dashboard_kb().as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Reply button dispatch (bottom keyboard: Меню + Написать статью)
# ---------------------------------------------------------------------------


@router.message(F.text == "Меню")
async def btn_menu(message: Message, user: User, db: SupabaseClient) -> None:
    """Reply button [Меню] → dashboard with inline navigation."""
    text = await _build_dashboard_text(user, db)
    await message.answer(text, reply_markup=dashboard_kb().as_markup())


@router.message(F.text == "Написать статью")
async def btn_write_article(
    message: Message,
    user: User,
    db: SupabaseClient,
    state: FSMContext,
    redis: RedisClient,
) -> None:
    """Reply button [Написать статью] -- start article pipeline.

    PIPELINE_UX_PROPOSAL.md section 16.10: check for active pipeline checkpoint.
    If checkpoint exists, offer resume. Otherwise start fresh pipeline flow.
    """
    from bot.fsm_utils import ensure_no_active_fsm
    from keyboards.pipeline import pipeline_no_entities_kb, pipeline_project_list_kb, pipeline_resume_kb

    # Check for active pipeline checkpoint (E49)
    checkpoint_key = CacheKeys.pipeline_state(user.id)
    existing = await redis.get(checkpoint_key)
    if existing:
        checkpoint: dict[str, object] = json.loads(existing)
        current_step = checkpoint.get("current_step", "?")
        await message.answer(
            f"У вас есть незавершённая статья:\nОстановились на: {current_step}\n",
            reply_markup=pipeline_resume_kb().as_markup(),
        )
        return

    # E26: Clear any active FSM before entering pipeline
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Load user projects
    projects = await ProjectsRepository(db).get_by_user(user.id)
    if not projects:
        await message.answer(
            "Статья (1/5) — Проект\n\nУ вас нет проектов. Создайте первый проект.",
            reply_markup=pipeline_no_entities_kb("project").as_markup(),
        )
        return

    if len(projects) == 1:
        # Auto-select single project, proceed to WP step
        from routers.publishing.pipeline.article import ArticlePipelineFSM, show_wp_selection

        await state.set_state(ArticlePipelineFSM.select_wp)
        await state.update_data(project_id=projects[0].id)
        sent = await message.answer("Статья (2/5) — WordPress\n\nПроверяю подключения...")
        await show_wp_selection(sent, user, db, projects[0].id, state)
        return

    # Multiple projects -- show selection list with last-used hint
    from db.repositories.publications import PublicationsRepository
    from routers.publishing.pipeline.article import ArticlePipelineFSM

    recent_logs = await PublicationsRepository(db).get_by_user(user.id, limit=1)
    last_project_id = recent_logs[0].project_id if recent_logs else None

    await state.set_state(ArticlePipelineFSM.select_project)
    await message.answer(
        "Статья (1/5) — Проект\n\nДля какого проекта?",
        reply_markup=pipeline_project_list_kb(projects, last_used_id=last_project_id).as_markup(),
    )


@router.callback_query(F.data == "stats:all")
async def cb_stub(callback: CallbackQuery) -> None:
    """Stub for not-yet-implemented inline button features."""
    await callback.answer("В разработке.", show_alert=True)


# ---------------------------------------------------------------------------
# Non-text FSM guard: photo/video/sticker during active FSM → error message
# ---------------------------------------------------------------------------


@router.message(~F.text & ~F.document, StateFilter("*"))
async def fsm_non_text_guard(message: Message) -> None:
    """Reject non-text messages during any active FSM flow.

    StateFilter("*") matches any non-None state, so this handler only fires
    when the user is in an FSM flow and sends non-text content.
    """
    await message.answer("Пожалуйста, отправьте текстовое сообщение.")
