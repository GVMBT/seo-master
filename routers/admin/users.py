"""Admin user features: new-user notification, recent active users list."""

import html

import structlog
from aiogram import Bot, F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.config import get_settings
from bot.helpers import safe_edit_text, safe_message
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.client import SupabaseClient
from db.models import User
from db.repositories.projects import ProjectsRepository
from db.repositories.users import UsersRepository

log = structlog.get_logger()
router = Router()


# ---------------------------------------------------------------------------
# 1. New user notification → admin
# ---------------------------------------------------------------------------


async def notify_admin_new_user(bot: Bot, user: User) -> None:
    """Send notification to all admins about a new user registration.

    Call this from the /start handler when is_new_user=True.
    """
    settings = get_settings()
    name_parts = [p for p in (user.first_name, user.last_name) if p]
    name = html.escape(" ".join(name_parts)) if name_parts else "\u2014"
    uname = f"@{html.escape(user.username)}" if user.username else "\u2014"

    text = (
        f"{E.USER} <b>Новый пользователь</b>\n"
        f"\n"
        f"Имя: {name}\n"
        f"Username: {uname}\n"
        f"ID: <code>{user.id}</code>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Карточка", callback_data=f"admin:user:{user.id}:card")],
        ]
    )

    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=kb)
        except Exception:
            log.warning("admin_new_user_notify_failed", admin_id=admin_id, user_id=user.id)


# ---------------------------------------------------------------------------
# 2. Recent active users list
# ---------------------------------------------------------------------------

_BACK_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
    ]
)


def _is_admin(user: User) -> bool:
    return user.role == "admin"


@router.callback_query(F.data == "admin:user_lookup")
async def user_lookup_start(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show recent active users + prompt for manual lookup."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    users_repo = UsersRepository(db)
    projects_repo = ProjectsRepository(db)

    # Fetch 10 most recently active users
    recent = await _fetch_recent_users(users_repo, projects_repo, limit=10)

    s = Screen(E.USER, "ПОЛЬЗОВАТЕЛИ")
    s.section(E.CHART, "Последние активные")

    for u in recent:
        name_part = u["username"] or u["name"] or str(u["id"])
        status = "paid" if u["paid"] else "free"
        status_icon = E.CHECK if u["paid"] else E.CLOSE
        projects_str = u["projects"]
        date_str = u["last_active"]
        s.line(
            f"  {status_icon} {html.escape(name_part)} "
            f"<code>{u['id']}</code>"
        )
        s.line(
            f"      {date_str} | {projects_str} пр. | {status}"
        )

    s.hint("Отправьте ID или @username для карточки")

    # Keyboard: each user as a button + manual input
    rows: list[list[InlineKeyboardButton]] = []
    for u in recent[:5]:
        label = u["username"] or u["name"] or str(u["id"])
        rows.append([
            InlineKeyboardButton(
                text=f"{label}",
                callback_data=f"admin:user:{u['id']}:card",
            )
        ])
    rows.append([InlineKeyboardButton(text="Поиск вручную", callback_data="admin:user_search")])
    rows.append([InlineKeyboardButton(text="К панели", callback_data="admin:panel")])

    await safe_edit_text(msg, s.build(), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


@router.callback_query(F.data == "admin:user_search")
async def user_search_manual(
    callback: CallbackQuery,
    user: User,
    state: "FSMContext",
) -> None:
    """Switch to manual user lookup FSM (existing flow in dashboard.py)."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    from aiogram.fsm.context import FSMContext as _FSM
    from bot.fsm_utils import ensure_no_active_fsm

    # Import FSM state from dashboard
    from routers.admin.dashboard import UserLookupFSM

    if isinstance(state, _FSM):
        await ensure_no_active_fsm(state)
        await state.set_state(UserLookupFSM.waiting_input)

    text = (
        Screen(E.USER, S.ADMIN_USER_LOOKUP_TITLE)
        .blank()
        .line(S.ADMIN_USER_LOOKUP_PROMPT)
        .hint("Поиск по Telegram ID или @username")
        .build()
    )
    await safe_edit_text(
        msg,
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Назад", callback_data="admin:user_lookup")],
                [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
            ]
        ),
    )
    await callback.answer()


async def _fetch_recent_users(
    users_repo: UsersRepository,
    projects_repo: ProjectsRepository,
    limit: int = 10,
) -> list[dict]:
    """Fetch recent active users with their project count and payment status."""
    # Query users ordered by last_activity desc
    resp = (
        await users_repo._db.table("users")
        .select("id, username, first_name, last_name, last_activity, role, balance, created_at")
        .not_.is_("last_activity", "null")
        .order("last_activity", desc=True)
        .limit(limit)
        .execute()
    )
    rows = resp.data if resp.data else []

    # Check payment status + project count for each user
    result = []
    for row in rows:
        uid = row["id"]
        # Quick project count
        p_count = await projects_repo.get_count_by_user(uid)

        # Determine if paid: balance > 1500 (initial) or role != user
        paid = row.get("balance", 0) > 1500 or row.get("role") == "admin"
        # Check if they made any payment (more accurate)
        pay_resp = (
            await users_repo._db.table("payments")
            .select("id", count="exact")
            .eq("user_id", uid)
            .eq("status", "completed")
            .limit(1)
            .execute()
        )
        if pay_resp.count and pay_resp.count > 0:
            paid = True

        # Format date
        la = row.get("last_activity")
        date_str = str(la)[:10] if la else "\u2014"

        name_parts = [p for p in (row.get("first_name"), row.get("last_name")) if p]
        name = " ".join(name_parts) if name_parts else None

        result.append({
            "id": uid,
            "username": f"@{row['username']}" if row.get("username") else None,
            "name": name,
            "last_active": date_str,
            "projects": p_count,
            "paid": paid,
        })

    return result
