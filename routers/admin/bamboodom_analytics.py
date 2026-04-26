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


# ---------------------------------------------------------------------------
# 4I.1: bamboodom:analytics:ranks — позиции в Яндексе через DataForSEO
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:analytics:ranks")
async def bamboodom_analytics_ranks(callback: CallbackQuery, user: User, redis) -> None:
    """Прогон ключевиков через DataForSEO Yandex SERP (4I.1)."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    s = get_settings()
    if not s.dataforseo_login or not s.dataforseo_password.get_secret_value():
        text, kb = _wrap_error(TXT.BAMBOODOM_RANKS_NO_CONFIG)
        await safe_edit_text(msg, text, reply_markup=kb)
        await callback.answer()
        return

    await safe_edit_text(
        msg,
        Screen(E.SYNC, TXT.BAMBOODOM_RANKS_TITLE).blank().line(TXT.BAMBOODOM_RANKS_PROGRESS).build(),
        reply_markup=bamboodom_analytics_back_kb(),
    )
    await callback.answer()

    from integrations.dataforseo_yandex import DataForSEOError
    from services.keyword_tracker import run_check

    try:
        entries, cost_cents = await run_check(redis)
    except DataForSEOError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_RANKS_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return
    except Exception as exc:
        log.warning("ranks_failed", exc_info=True)
        text, kb = _wrap_error(TXT.BAMBOODOM_RANKS_FAIL.format(detail=repr(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    import datetime as _dt

    today = _dt.date.today().strftime("%d.%m.%Y")

    screen = (
        Screen(E.SEARCH_CHECK, TXT.BAMBOODOM_RANKS_TITLE)
        .blank()
        .line(TXT.BAMBOODOM_RANKS_HEAD.format(date=today))
        .blank()
    )
    if not entries:
        screen = screen.line("Нет данных. Список ключевиков пуст?")
    else:
        for e in entries:
            if e.position is None:
                screen = screen.line(TXT.BAMBOODOM_RANKS_LINE_NOTOP.format(kw=e.keyword))
                continue
            delta_str = ""
            if e.delta_week is not None and e.delta_week != 0:
                delta_str = f"  ↑ {abs(e.delta_week)}" if e.delta_week < 0 else f"  ↓ {e.delta_week}"
            screen = screen.line(TXT.BAMBOODOM_RANKS_LINE_TOP.format(pos=e.position, kw=e.keyword, delta=delta_str))

    screen = screen.blank().line(TXT.BAMBOODOM_RANKS_COST.format(cents=cost_cents))
    screen = screen.hint(TXT.BAMBOODOM_RANKS_LEGEND)
    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_analytics_back_kb())


# ---------------------------------------------------------------------------
# 4I.3: bamboodom:analytics:declining — просевшие статьи
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "bamboodom:analytics:declining")
async def bamboodom_analytics_declining(callback: CallbackQuery, user: User) -> None:
    """Сравнение трафика статей неделя-к-неделе. Просадка ≥30% — в отчёт (4I.3)."""
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
        Screen(E.SYNC, TXT.BAMBOODOM_DECLINING_TITLE).blank().line(TXT.BAMBOODOM_DECLINING_PROGRESS).build(),
        reply_markup=bamboodom_analytics_back_kb(),
    )
    await callback.answer()

    try:
        client = YandexMetrikaClient()
        # Период «неделя сейчас» = последние 7 дней (вчера-7 → вчера)
        # Период «прошлая неделя» = 14-7 дней назад
        cur = await client.get_top_pages("7daysAgo", "yesterday", limit=50)
        prev = await client.get_top_pages("14daysAgo", "8daysAgo", limit=50)
    except YandexMetrikaError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_ANALYTICS_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    prev_map = {it.get("url"): int(it.get("pageviews") or 0) for it in prev}
    declining: list[tuple[str, int, int, float]] = []
    for it in cur:
        url = it.get("url") or ""
        now_pv = int(it.get("pageviews") or 0)
        prev_pv = prev_map.get(url, 0)
        if prev_pv >= 10 and now_pv < prev_pv:
            delta_pct = 100.0 * (now_pv - prev_pv) / prev_pv
            if delta_pct <= -30.0:
                declining.append((url, prev_pv, now_pv, delta_pct))
    declining.sort(key=lambda x: x[3])  # самые большие просадки сверху

    from services.analytics.metrika_summary import shorten_url

    screen = Screen(E.WARNING, TXT.BAMBOODOM_DECLINING_TITLE).blank().line(TXT.BAMBOODOM_DECLINING_HEADER)
    if not declining:
        screen = screen.blank().line(f"{E.CHECK} {TXT.BAMBOODOM_DECLINING_EMPTY}")
    else:
        screen = screen.blank()
        for url, prev_pv, now_pv, delta in declining[:10]:
            screen = screen.line(
                TXT.BAMBOODOM_DECLINING_LINE.format(
                    url=shorten_url(url, 50),
                    prev=prev_pv,
                    now=now_pv,
                    delta=f"{delta:+.0f}%",
                )
            )
    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_analytics_back_kb())


# ---------------------------------------------------------------------------
# 4I.2: bamboodom:analytics:research — keyword research
# ---------------------------------------------------------------------------

_RESEARCH_SEEDS = {
    "wpc": "wpc панели",
    "flex": "гибкая керамика",
    "reiki": "реечные панели",
    "profiles": "алюминиевые профили xhs",
}
_RESEARCH_LABELS = {
    "wpc": "WPC панели",
    "flex": "Гибкая керамика",
    "reiki": "Реечные панели",
    "profiles": "Алюминиевые профили",
}


@router.callback_query(F.data == "bamboodom:analytics:research")
async def bamboodom_research_root(callback: CallbackQuery, user: User) -> None:
    """Корневой экран подбора тем — выбор категории (4I.2)."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    s = get_settings()
    if not s.dataforseo_login or not s.dataforseo_password.get_secret_value():
        text, kb = _wrap_error(TXT.BAMBOODOM_RANKS_NO_CONFIG)
        await safe_edit_text(msg, text, reply_markup=kb)
        await callback.answer()
        return

    from keyboards.bamboodom import bamboodom_research_kb

    text = Screen(E.LIGHTBULB, TXT.BAMBOODOM_RESEARCH_TITLE).blank().line(TXT.BAMBOODOM_RESEARCH_HINT).build()
    await safe_edit_text(msg, text, reply_markup=bamboodom_research_kb())
    await callback.answer()


@router.callback_query(F.data.startswith("bamboodom:research:"))
async def bamboodom_research_category(callback: CallbackQuery, user: User) -> None:
    """Подобрать темы для конкретной категории материала."""
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    category = (callback.data or "").split(":")[-1]
    seed = _RESEARCH_SEEDS.get(category)
    label = _RESEARCH_LABELS.get(category, category)
    if not seed:
        await callback.answer("Неизвестная категория", show_alert=True)
        return

    from keyboards.bamboodom import bamboodom_research_kb

    await safe_edit_text(
        msg,
        Screen(E.SYNC, TXT.BAMBOODOM_RESEARCH_TITLE)
        .blank()
        .line(f"Категория: {label}")
        .line(TXT.BAMBOODOM_RESEARCH_PROGRESS)
        .build(),
        reply_markup=bamboodom_research_kb(),
    )
    await callback.answer()

    from integrations.dataforseo_yandex import (
        DataForSEOError,
        DataForSEOYandexClient,
    )

    try:
        client = DataForSEOYandexClient()
        suggestions = await client.keywords_for_seed(seed=seed, limit=50)
    except DataForSEOError as exc:
        text, kb = _wrap_error(TXT.BAMBOODOM_RESEARCH_FAIL.format(detail=str(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return
    except Exception as exc:
        log.warning("research_failed", exc_info=True)
        text, kb = _wrap_error(TXT.BAMBOODOM_RESEARCH_FAIL.format(detail=repr(exc)[:200]))
        await safe_edit_text(msg, text, reply_markup=kb)
        return

    # Фильтрация: только запросы с volume >= 30, исключить точное совпадение с seed
    filtered = [v for v in suggestions if v.volume >= 30 and v.phrase.lower().strip() != seed.lower().strip()]
    filtered.sort(key=lambda v: v.volume, reverse=True)

    screen = (
        Screen(E.LIGHTBULB, TXT.BAMBOODOM_RESEARCH_TITLE)
        .blank()
        .line(f"Категория: {label}")
        .line(f"Seed: {seed}")
        .blank()
    )
    if not filtered:
        screen = screen.line("Ничего не нашлось — попробуйте другую категорию.")
    else:
        screen = screen.line("Топ запросов по частотности (от Яндекс.Wordstat):")
        for i, v in enumerate(filtered[:15], start=1):
            comp = ""
            if v.competition is not None:
                if v.competition < 0.34:
                    comp = " 🟢"
                elif v.competition < 0.67:
                    comp = " 🟡"
                else:
                    comp = " 🔴"
            screen = screen.line(f"{i}. {v.phrase} — {v.volume:,}/мес{comp}".replace(",", " "))
        screen = screen.blank().hint("🟢 низкая конкуренция, 🟡 средняя, 🔴 высокая.")

    await safe_edit_text(msg, screen.build(), reply_markup=bamboodom_research_kb())


# ---------------------------------------------------------------------------
# 4I.4: bamboodom:analytics:schedule — авторасписание дайджеста
# ---------------------------------------------------------------------------


def _build_schedule_text(status: dict) -> str:
    active = bool(status.get("active"))
    screen = Screen(E.SCHEDULE, TXT.BAMBOODOM_SCHEDULE_TITLE).blank()
    if active:
        screen = screen.line(TXT.BAMBOODOM_SCHEDULE_ACTIVE)
        sid = status.get("schedule_id") or "—"
        screen = screen.line(TXT.BAMBOODOM_SCHEDULE_ID.format(sid=sid))
    else:
        screen = screen.line(TXT.BAMBOODOM_SCHEDULE_INACTIVE)
        url = status.get("url")
        if not url:
            screen = screen.blank().line(f"{E.WARNING} {TXT.BAMBOODOM_SCHEDULE_NO_PUBLIC_URL}")
    return screen.build()


@router.callback_query(F.data == "bamboodom:analytics:schedule")
async def bamboodom_schedule_root(callback: CallbackQuery, user: User, redis) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    from keyboards.bamboodom import bamboodom_digest_schedule_kb
    from services.analytics.digest_schedule import status

    st = await status(redis)
    await safe_edit_text(
        msg,
        _build_schedule_text(st),
        reply_markup=bamboodom_digest_schedule_kb(active=st.get("active", False)),
    )
    await callback.answer()


@router.callback_query(F.data == "bamboodom:analytics:schedule_on")
async def bamboodom_schedule_on(callback: CallbackQuery, user: User, redis) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    from keyboards.bamboodom import bamboodom_digest_schedule_kb
    from services.analytics.digest_schedule import create_schedule, status

    ok, info = await create_schedule(redis)
    st = await status(redis)
    head = TXT.BAMBOODOM_SCHEDULE_CREATED.format(sid=info) if ok else TXT.BAMBOODOM_SCHEDULE_FAIL.format(detail=info)
    text = (
        Screen(E.SCHEDULE, TXT.BAMBOODOM_SCHEDULE_TITLE)
        .blank()
        .line(head)
        .blank()
        .line(_build_schedule_text(st).split("\n", 2)[-1] if st else "")
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=bamboodom_digest_schedule_kb(st.get("active", False)))
    await callback.answer()


@router.callback_query(F.data == "bamboodom:analytics:schedule_off")
async def bamboodom_schedule_off(callback: CallbackQuery, user: User, redis) -> None:
    if not _is_admin(user):
        await callback.answer(S.ADMIN_ACCESS_DENIED, show_alert=True)
        return
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return
    from keyboards.bamboodom import bamboodom_digest_schedule_kb
    from services.analytics.digest_schedule import delete_schedule, status

    ok, info = await delete_schedule(redis)
    st = await status(redis)
    head = TXT.BAMBOODOM_SCHEDULE_DELETED if ok else TXT.BAMBOODOM_SCHEDULE_FAIL.format(detail=info)
    text = Screen(E.SCHEDULE, TXT.BAMBOODOM_SCHEDULE_TITLE).blank().line(head).build()
    await safe_edit_text(msg, text, reply_markup=bamboodom_digest_schedule_kb(st.get("active", False)))
    await callback.answer()
