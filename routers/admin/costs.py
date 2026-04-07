"""Admin costs: real API spending from OpenRouter Activity + external balances."""

import asyncio
import base64
from collections import defaultdict

import httpx
import structlog
from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.config import get_settings
from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.models import User

log = structlog.get_logger()
router = Router()

_BACK_TO_PANEL_KB = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
    ]
)


def _is_admin(user: User) -> bool:
    return user.role == "admin"


# ---------------------------------------------------------------------------
# OpenRouter: credits + activity by model
# ---------------------------------------------------------------------------


async def _fetch_openrouter_credits(
    http: httpx.AsyncClient, api_key: str
) -> float | None:
    """GET /api/v1/credits -> remaining credits in USD."""
    try:
        resp = await http.get(
            "https://openrouter.ai/api/v1/credits",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=8.0,
        )
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            total = data.get("total_credits", 0)
            used = data.get("total_usage", 0)
            return round(total - used, 2)
    except Exception:
        log.warning("openrouter_credits_fetch_failed", exc_info=True)
    return None


async def _fetch_openrouter_activity(
    http: httpx.AsyncClient, api_key: str
) -> list[dict]:
    """GET /api/v1/activity -> last 30 days usage by model."""
    try:
        resp = await http.get(
            "https://openrouter.ai/api/v1/activity",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("data", [])
    except Exception:
        log.warning("openrouter_activity_fetch_failed", exc_info=True)
    return []


def _aggregate_activity(raw: list[dict]) -> dict[str, dict]:
    """Aggregate activity data by model: total cost, request count, tokens."""
    by_model: dict[str, dict] = defaultdict(
        lambda: {"cost": 0.0, "requests": 0, "tokens_in": 0, "tokens_out": 0}
    )
    for entry in raw:
        model = entry.get("model", "unknown")
        # Shorten model name: "anthropic/claude-sonnet-4.5" -> "Claude Sonnet 4.5"
        cost = float(entry.get("total_cost", 0) or 0)
        reqs = int(entry.get("num_requests", 0) or 0)
        t_in = int(entry.get("tokens_input", 0) or entry.get("usage", 0) or 0)
        t_out = int(entry.get("tokens_output", 0) or 0)
        by_model[model]["cost"] += cost
        by_model[model]["requests"] += reqs
        by_model[model]["tokens_in"] += t_in
        by_model[model]["tokens_out"] += t_out
    return dict(by_model)


def _short_model_name(slug: str) -> str:
    """Shorten OpenRouter model slugs for display."""
    parts = slug.split("/")
    name = parts[-1] if len(parts) > 1 else slug
    name = name.replace("-preview", "")
    replacements = {
        "claude-sonnet-4.5": "Claude Sonnet 4.5",
        "claude-4.5-sonnet": "Claude Sonnet 4.5",
        "deepseek-v3.2": "DeepSeek V3.2",
        "gpt-5.2": "GPT 5.2",
        "gpt-4o": "GPT 4o",
        "sonar-pro-search": "Perplexity Sonar",
        "gemini-3.1-flash-image": "Gemini Flash (img)",
        "gemini-2.5-flash-image": "Gemini Flash (img)",
        "gemini-2.5-flash": "Gemini Flash",
        "gemini-3.1-flash": "Gemini Flash",
    }
    for pattern, label in replacements.items():
        if pattern in name:
            return label
    return name[:25]


def _format_count(n: int) -> str:
    """Format request count: 1234 -> 1.2k."""
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


# ---------------------------------------------------------------------------
# DataForSEO: balance
# ---------------------------------------------------------------------------


async def _fetch_dataforseo_balance(
    http: httpx.AsyncClient, login: str, password: str
) -> float | None:
    """GET /v3/appendix/user_data -> account balance."""
    if not login or not password:
        return None
    try:
        cred = base64.b64encode(f"{login}:{password}".encode()).decode()
        resp = await http.get(
            "https://api.dataforseo.com/v3/appendix/user_data",
            headers={"Authorization": f"Basic {cred}"},
            timeout=8.0,
        )
        if resp.status_code == 200:
            tasks = resp.json().get("tasks", [])
            if tasks and tasks[0].get("result"):
                result = tasks[0]["result"][0]
                money = result.get("money", {})
                balance = money.get("balance", 0)
                return round(float(balance), 2)
    except Exception:
        log.warning("dataforseo_balance_fetch_failed", exc_info=True)
    return None


# ---------------------------------------------------------------------------
# Handler: admin:api_costs (replaces the old one in dashboard.py)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin:api_costs")
async def admin_api_costs_v2(
    callback: CallbackQuery,
    user: User,
    http_client: httpx.AsyncClient,
) -> None:
    """Show real API costs from OpenRouter + balances from external services."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    settings = get_settings()
    or_key = settings.openrouter_api_key.get_secret_value()
    dfs_login = settings.dataforseo_login
    dfs_password = settings.dataforseo_password.get_secret_value()

    # Fetch all data in parallel
    or_credits, or_activity, dfs_balance = await asyncio.gather(
        _fetch_openrouter_credits(http_client, or_key),
        _fetch_openrouter_activity(http_client, or_key),
        _fetch_dataforseo_balance(http_client, dfs_login, dfs_password),
    )

    # Aggregate activity by model
    by_model = _aggregate_activity(or_activity)

    # Sort by cost descending
    sorted_models = sorted(by_model.items(), key=lambda x: x[1]["cost"], reverse=True)

    # Total cost across all models
    total_cost = sum(v["cost"] for v in by_model.values())

    # Build screen text
    s = Screen(E.WALLET, S.API_COSTS_TITLE)

    # -- Balances --
    s.section(E.DOLLAR, "Балансы")
    or_str = f"${or_credits:.2f}" if or_credits is not None else "\u2014"
    s.line(f"OpenRouter: {or_str}")
    dfs_str = f"${dfs_balance:.2f}" if dfs_balance is not None else "\u2014"
    s.line(f"DataForSEO: {dfs_str}")
    s.line("Anthropic (BYOK): console")
    s.line("Google AI (BYOK): бесплатный тир")

    # -- Total cost 30d --
    s.section(E.CHART, "Расходы за 30 дней")
    s.line(f"Итого: <b>${total_cost:.2f}</b>")

    # -- Per-model breakdown (top 8) --
    if sorted_models:
        s.blank()
        for model_slug, stats in sorted_models[:8]:
            name = _short_model_name(model_slug)
            cost = stats["cost"]
            reqs = _format_count(stats["requests"])
            if cost >= 0.01:
                s.line(f"  {name}: ${cost:.2f} ({reqs})")

    s.hint("Данные OpenRouter Activity за 30 дней")

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Обновить", callback_data="admin:api_costs")],
            [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
        ]
    )

    await safe_edit_text(msg, s.build(), reply_markup=kb)
    await callback.answer()
