"""Admin panel — Bamboodom: раздел «Аналитика» (4F).

Получает данные из Яндекс.Метрики (Stat API v1) и рендерит сводки в админке.
Все запросы идут с OAuth-токеном из YANDEX_METRIKA_TOKEN, счётчик
YANDEX_METRIKA_COUNTER_ID. Сторона B уже установила счётчик `108576638` в
shared.js, нам только токен с правом metrika:read.

Регистрируется в routers/admin/__init__.py перед bamboodom.router (чтобы
не было коллизий с bamboodom:articles handler).
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.config import get_settings
from bot.helpers import safe_edit_text, safe_message
from bot.texts import bamboodom as TXT
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from db.models import User
from integrations.yandex_metrika import (
    YandexMetrikaAuthError,
    YandexMetrikaClient,
    YandexMetrikaError,
)
from keyboards.bamboodom import (
    bamboodom_analytics_back_kb,
    bamboodom_analytics_kb,
)
from services.analytics.metrika_summary import (
    fmt_duration,
    fmt_int,
    fmt_percent,
    summarize_search_phrases,
    summarize_top_pages,
    summarize_traffic_sources,
)

log = structlog.get_logger()
router = Router()


def _is_admin(user: User) -> bool:
    return user.role == "admin"


def _check_token() -> str | None:
    s = get_settings()
    if not s.yandex_metrika_token.get_secret_value():
        return TXT.BAMBOODOM_ANALYTICS_NO_TOKEN
    if not s.yandex_metrika_counter_id:
        return TXT.BAMBOODOM_ANALYTICS_NO_COUNTER
    return None


def _wrap_error(msg: str, kb=None):
    """Возвращает (text, kb) для error-экрана."""
    text = Screen(E.WARNING, TXT.BAMBOODOM_ANALYTICS_TITLE).blank().line(f"{E.CLOSE} {msg}").build()
    return text, (kb or bamboodom_analytics_back_kb())


def _build_progress_text(title: str) -> str:
    return Screen(E.SYNC, title).blank().line(TXT.BAMBOODOM_ANALYTICS_PROGRESS).build()


# ---------------------------------------------------------------------------
# bamboodom:analytics — корневой экран подменю
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:analytics")
async def bamboodom_analytics_root(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    err = _check_token()
    if err:
        text = Screen(E.WARNING, TXT.BAMBOODOM_ANALYTICS_TITLE).blank().line(f"{E.CLOSE} {err}").build()
        await safe_edit_text(msg, text, reply_markup=bamboodom_analytics_kb())
        await callback.answer()
        return

    text = (
        Screen(E.CHART, TXT.BAMBOODOM_ANALYTICS_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_ANALYTICS_SUBTITLE)
        .blank()
        .hint(TXT.BAMBOODOM_ANALYTICS_HINT)
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_analytics_kb())
    await callback.answer()


# ---------------------------------------------------------------------------
# Helpers для сводки
# ---------------------------------------------------------------------------


async def _render_summary(callback: CallbackQuery, title: str, date1: str, date2: str) -> None:
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    err = _check_token()
    if err:
        text, kb = _wrap_error(err)
        await safe_edit_text(msg, text, reply_markup=kb)
        await callback.answer()
        return

    await safe_edit_text(msg, _build_progress_text(title), reply_markup=bamboodom_analytics_back_kb())
    await callback.answer()

    try:
        client = YandexMetrikaClient()
        data = await client.get_summary(date1=date1, date2=date2)
    except YandexMetrikaAuthError:
        text, kb = _wrap_error(TXT.BAMBOODOM_ANALYTICS_AUTH_FAIL)
        await safe_edit_text(msg, text, reply_markup=kb)
        return
    except YandexMetrikaError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_ANALYTICS_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    period_label = f"{data['date1']} — {data['date2']}" if data["date1"] != data["date2"] else data["date1"]
    text = (
        Screen(E.CHART, title)
        .blank()
        .field(E.SCHEDULE, TXT.BAMBOODOM_SUMMARY_LABEL_PERIOD, period_label)
        .field(E.PULSE, TXT.BAMBOODOM_SUMMARY_LABEL_VISITS, fmt_int(data["visits"]))
        .field(E.USER, TXT.BAMBOODOM_SUMMARY_LABEL_USERS, fmt_int(data["users"]))
        .field(E.DOC, TXT.BAMBOODOM_SUMMARY_LABEL_PAGEVIEWS, fmt_int(data["pageviews"]))
        .field(E.WARNING, TXT.BAMBOODOM_SUMMARY_LABEL_BOUNCE, fmt_percent(data["bounce_rate"]))
        .field(E.SCHEDULE, TXT.BAMBOODOM_SUMMARY_LABEL_DURATION, fmt_duration(data["avg_visit_duration"]))
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_analytics_back_kb())


# ---------------------------------------------------------------------------
# Конкретные отчёты
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:analytics:yesterday")
async def bamboodom_summary_yesterday(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await _render_summary(callback, TXT.BAMBOODOM_SUMMARY_TITLE_YESTERDAY, "yesterday", "yesterday")


@router.callback_query(F.data == "bamboodom:analytics:week")
async def bamboodom_summary_week(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    await _render_summary(callback, TXT.BAMBOODOM_SUMMARY_TITLE_WEEK, "7daysAgo", "yesterday")


@router.callback_query(F.data == "bamboodom:analytics:top_pages")
async def bamboodom_top_pages(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    err = _check_token()
    if err:
        text, kb = _wrap_error(err)
        await safe_edit_text(msg, text, reply_markup=kb)
        await callback.answer()
        return

    await safe_edit_text(
        msg,
        _build_progress_text(TXT.BAMBOODOM_TOP_PAGES_TITLE),
        reply_markup=bamboodom_analytics_back_kb(),
    )
    await callback.answer()
    try:
        client = YandexMetrikaClient()
        items = await client.get_top_pages()
    except YandexMetrikaError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_ANALYTICS_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    screen = Screen(E.CHART, TXT.BAMBOODOM_TOP_PAGES_TITLE).blank()
    if not items:
        screen = screen.line(TXT.BAMBOODOM_TOP_PAGES_EMPTY)
    else:
        for line in summarize_top_pages(items, limit=10):
            screen = screen.line(line)
        screen = screen.blank().hint(TXT.BAMBOODOM_TOP_PAGES_HINT)
    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_analytics_back_kb())


@router.callback_query(F.data == "bamboodom:analytics:sources")
async def bamboodom_traffic_sources(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    err = _check_token()
    if err:
        text, kb = _wrap_error(err)
        await safe_edit_text(msg, text, reply_markup=kb)
        await callback.answer()
        return

    await safe_edit_text(
        msg,
        _build_progress_text(TXT.BAMBOODOM_SOURCES_TITLE),
        reply_markup=bamboodom_analytics_back_kb(),
    )
    await callback.answer()
    try:
        client = YandexMetrikaClient()
        items = await client.get_traffic_sources()
    except YandexMetrikaError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_ANALYTICS_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    screen = Screen(E.CHART, TXT.BAMBOODOM_SOURCES_TITLE).blank()
    if not items:
        screen = screen.line(TXT.BAMBOODOM_SOURCES_EMPTY)
    else:
        total = sum(int(it.get("visits") or 0) for it in items)
        for line in summarize_traffic_sources(items, total=total):
            screen = screen.line(line)
    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_analytics_back_kb())


@router.callback_query(F.data == "bamboodom:analytics:queries")
async def bamboodom_search_queries(callback: CallbackQuery, user: User) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    err = _check_token()
    if err:
        text, kb = _wrap_error(err)
        await safe_edit_text(msg, text, reply_markup=kb)
        await callback.answer()
        return

    await safe_edit_text(
        msg,
        _build_progress_text(TXT.BAMBOODOM_QUERIES_TITLE),
        reply_markup=bamboodom_analytics_back_kb(),
    )
    await callback.answer()
    try:
        client = YandexMetrikaClient()
        items = await client.get_top_search_phrases()
    except YandexMetrikaError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_ANALYTICS_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    screen = Screen(E.SEARCH_CHECK, TXT.BAMBOODOM_QUERIES_TITLE).blank()
    if not items:
        screen = screen.line(TXT.BAMBOODOM_QUERIES_EMPTY)
    else:
        for line in summarize_search_phrases(items, limit=10):
            screen = screen.line(line)
        screen = screen.blank().hint(TXT.BAMBOODOM_QUERIES_HINT)
    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_analytics_back_kb())


# ---------------------------------------------------------------------------
# bamboodom:analytics:digest — утренний дайджест (4H)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:analytics:digest")
async def bamboodom_analytics_digest(callback: CallbackQuery, user: User) -> None:
    """Утренний дайджест: всё в одном сообщении.

    Источники: Метрика + blog_list + Я.Вебмастер. Каждый источник опционален —
    если что-то упало, в дайджесте появится секция «Сбои источников».
    """
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await safe_edit_text(
        msg,
        Screen(E.SYNC, TXT.BAMBOODOM_DIGEST_TITLE).blank().line(TXT.BAMBOODOM_DIGEST_PROGRESS).build(),
        reply_markup=bamboodom_analytics_back_kb(),
    )
    await callback.answer()

    from services.analytics.digest import collect_and_render

    try:
        text = await collect_and_render()
    except Exception as exc:
        log.warning("digest_failed", exc_info=True)
        text = Screen(E.WARNING, TXT.BAMBOODOM_DIGEST_TITLE).blank().line(f"{E.CLOSE} {repr(exc)[:200]}").build()
    await safe_edit_text(msg, text, reply_markup=bamboodom_analytics_back_kb())
