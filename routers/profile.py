"""Router: user profile — balance, expense history, referral program.

Source of truth: USER_FLOWS_AND_UI_MAP.md §Profile (lines 886-931).
Features: F18 (profile dashboard), F19 (referral system).
Edge cases: E01 (insufficient balance display).

All business logic delegated to TokenService (services/tokens.py).
"""

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from db.client import SupabaseClient
from db.models import TokenExpense, User
from keyboards.inline import profile_history_kb, profile_main_kb, profile_referral_kb
from routers._helpers import guard_callback_message
from services.tokens import TokenService

router = Router(name="profile")

# ---------------------------------------------------------------------------
# Operation type display names (for history)
# ---------------------------------------------------------------------------

_OP_LABELS: dict[str, str] = {
    "text_generation": "Генерация текста",
    "image_generation": "Генерация изображений",
    "keyword_generation": "Ключевые фразы",
    "audit": "Аудит сайта",
    "review": "Генерация отзывов",
    "description": "Описание категории",
    "competitor_analysis": "Анализ конкурентов",
    "purchase": "Покупка токенов",
    "refund": "Возврат токенов",
    "referral_bonus": "Реферальный бонус",
    "welcome_bonus": "Приветственный бонус",
    "api_openrouter": "API OpenRouter",
    "api_firecrawl": "API Firecrawl",
    "api_dataforseo": "API DataForSEO",
    "api_serper": "API Serper",
}


def _format_expense(exp: TokenExpense) -> str:
    """Format a single expense line for history display."""
    date_str = exp.created_at.strftime("%d.%m.%Y %H:%M") if exp.created_at else "—"
    label = _OP_LABELS.get(exp.operation_type, exp.operation_type)
    sign = "+" if exp.amount > 0 else ""
    return f"{date_str}  {label}  {sign}{exp.amount} токенов"


def _format_profile(user: User, stats: dict[str, int]) -> str:
    """Build profile display text (USER_FLOWS_AND_UI_MAP.md §Profile, lines 886-905)."""
    reg_date = user.created_at.strftime("%d.%m.%Y") if user.created_at else "—"
    role_label = "Администратор" if user.role == "admin" else "Пользователь"

    lines = [
        f"ID: {user.id}",
        f"Имя: {user.first_name or '—'} {user.last_name or ''}".rstrip(),
        f"Роль: {role_label}",
        f"Баланс: {user.balance} токенов",
        f"Дата регистрации: {reg_date}",
        "",
        f"Проектов: {stats['project_count']}",
        f"Категорий: {stats['category_count']}",
        f"Активных расписаний: {stats['schedule_count']}",
    ]

    schedule_count = stats["schedule_count"]
    if schedule_count > 0:
        posts_per_week = stats["posts_per_week"]
        tokens_per_week = stats["tokens_per_week"]
        tokens_per_month = stats["tokens_per_month"]
        weeks_left = round(user.balance / tokens_per_week, 1) if tokens_per_week > 0 else 0

        lines += [
            "",
            "Прогноз расходов:",
            f"  Постов в неделю: {posts_per_week}",
            f"  Токенов в неделю: ~{tokens_per_week}",
            f"  Токенов в месяц: ~{tokens_per_month}",
            f"  Хватит на: ~{weeks_left} недели",
        ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Service factory
# ---------------------------------------------------------------------------


def _make_service(db: SupabaseClient) -> TokenService:
    """Create TokenService with admin_id from settings (C1: GOD_MODE fix)."""
    return TokenService(db, admin_id=get_settings().admin_id)


# ---------------------------------------------------------------------------
# Profile main screen
# ---------------------------------------------------------------------------


async def _show_profile(
    target: Message,
    user: User,
    db: SupabaseClient,
    edit: bool = False,
) -> None:
    """Render profile for both reply-button and callback entry points."""
    service = _make_service(db)
    stats = await service.get_profile_stats(user)
    text = _format_profile(user, stats)
    kb = profile_main_kb().as_markup()

    if edit:
        await target.edit_text(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.callback_query(F.data == "profile:main")
async def cb_profile(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show profile via inline button."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    await _show_profile(msg, user, db, edit=True)
    await callback.answer()


# ---------------------------------------------------------------------------
# Expense history
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "profile:history")
async def cb_history(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show last 20 token expenses."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    service = _make_service(db)
    expenses = await service.get_history(user.id, limit=20)

    if not expenses:
        text = "История расходов пуста."
    else:
        lines = [_format_expense(exp) for exp in expenses]
        text = "Последние операции:\n\n" + "\n".join(lines)

    await msg.edit_text(text, reply_markup=profile_history_kb().as_markup())
    await callback.answer()


# ---------------------------------------------------------------------------
# Referral program (F19)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "profile:referral")
async def cb_referral(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show referral link and stats."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    service = _make_service(db)
    stats = await service.get_profile_stats(user)
    referral_bonus = await service.get_referral_bonus_total(user.id)

    bot_me = await callback.bot.me() if callback.bot else None  # type: ignore[union-attr]
    bot_username = bot_me.username if bot_me and bot_me.username else "SEOMasterBot"

    text = (
        f"Ваша ссылка: https://t.me/{bot_username}?start=ref_{user.id}\n\n"
        f"Приглашено: {stats['referral_count']} человек\n"
        f"Заработано: {referral_bonus} бонусных токенов\n\n"
        "Вы получаете 10% от каждой покупки приглашённого друга."
    )

    await msg.edit_text(
        text, reply_markup=profile_referral_kb(user.id, bot_username).as_markup()
    )
    await callback.answer()
