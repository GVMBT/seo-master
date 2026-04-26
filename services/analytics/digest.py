"""Утренний дайджест Bamboodom (4H).

Собирает в одно сообщение:
- Метрика: визиты/посетители/просмотры/отказы за вчера
- Топ-3 страницы за вчера
- Bamboodom: всего статей блога, опубликовано вчера
- Я.Вебмастер: дневная квота, отправлено за вчера

Всё с graceful degrade: если один канал упал, показываем остальные.
Используется кнопкой «Утренний дайджест» в админке + (в будущем) для
QStash cron в 07:00 МСК.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import structlog

from bot.config import get_settings
from bot.texts import bamboodom as TXT
from bot.texts.emoji import E
from bot.texts.screens import Screen
from integrations.yandex_metrika import (
    YandexMetrikaClient,
    YandexMetrikaError,
)
from integrations.yandex_webmaster import (
    YandexWebmasterClient,
    YandexWebmasterError,
)
from services.analytics.metrika_summary import (
    fmt_duration,
    fmt_int,
    fmt_percent,
    shorten_url,
)

log = structlog.get_logger()


@dataclass
class DigestData:
    metrika_summary: dict[str, Any] | None = None
    metrika_top: list[dict[str, Any]] = field(default_factory=list)
    blog_total: int | None = None
    blog_published_yesterday: int | None = None
    yw_quota: dict[str, Any] = field(default_factory=dict)
    yw_queue_count: int | None = None
    errors: list[str] = field(default_factory=list)


async def _fetch_metrika(data: DigestData) -> None:
    s = get_settings()
    if not s.yandex_metrika_token.get_secret_value() or not s.yandex_metrika_counter_id:
        return
    try:
        client = YandexMetrikaClient()
        data.metrika_summary = await client.get_summary("yesterday", "yesterday")
        data.metrika_top = await client.get_top_pages("yesterday", "yesterday", limit=3)
    except YandexMetrikaError as exc:
        data.errors.append(f"Метрика: {exc}")


async def _fetch_blog(data: DigestData) -> None:
    s = get_settings()
    if not s.bamboodom_blog_key.get_secret_value():
        return
    try:
        # Используем blog_list endpoint напрямую
        import httpx

        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        async with httpx.AsyncClient(timeout=10.0) as h:
            resp = await h.get(
                s.bamboodom_api_base,
                params={"action": "blog_list", "limit": 100},
                headers={"X-Blog-Key": s.bamboodom_blog_key.get_secret_value()},
            )
            resp.raise_for_status()
            payload = resp.json()
        items = payload.get("items") or []
        data.blog_total = int(payload.get("total") or len(items))
        # Считаем опубликованные «вчера»
        count_y = 0
        for it in items:
            if it.get("draft"):
                continue
            pub = str(it.get("published_at") or "")[:10]
            if pub == yesterday:
                count_y += 1
        data.blog_published_yesterday = count_y
    except Exception as exc:
        data.errors.append(f"blog_list: {exc}")


async def _fetch_yw(data: DigestData) -> None:
    s = get_settings()
    if not s.yandex_webmaster_token.get_secret_value():
        return
    try:
        client = YandexWebmasterClient()
        try:
            data.yw_quota = await client.get_recrawl_quota_info() or {}
        except YandexWebmasterError:
            data.yw_quota = {}
        try:
            history = await client.get_recrawl_quota()
            tasks = history.get("tasks") or []
            yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
            data.yw_queue_count = sum(1 for t in tasks if str(t.get("added_at") or "")[:10] == yesterday)
        except YandexWebmasterError:
            data.yw_queue_count = None
    except YandexWebmasterError as exc:
        data.errors.append(f"Я.Вебмастер: {exc}")


async def collect_digest() -> DigestData:
    """Параллельный сбор данных из всех источников. Graceful degrade."""
    data = DigestData()
    await asyncio.gather(
        _fetch_metrika(data),
        _fetch_blog(data),
        _fetch_yw(data),
        return_exceptions=False,
    )
    return data


def render_digest(data: DigestData) -> str:
    """Формирует текст дайджеста (HTML, parse_mode=HTML, для aiogram)."""
    today = dt.date.today().strftime("%d.%m.%Y")
    yesterday = (dt.date.today() - dt.timedelta(days=1)).strftime("%d.%m.%Y")

    screen = Screen(E.CHART, TXT.BAMBOODOM_DIGEST_TITLE).blank()
    screen = screen.line(TXT.BAMBOODOM_DIGEST_HEADER.format(today=today, yesterday=yesterday))

    # --- Метрика ---
    screen = screen.section(E.PULSE, TXT.BAMBOODOM_DIGEST_SECTION_TRAFFIC)
    if data.metrika_summary:
        m = data.metrika_summary
        screen = (
            screen.line(f"Визитов: {fmt_int(m['visits'])}")
            .line(f"Посетителей: {fmt_int(m['users'])}")
            .line(f"Просмотров: {fmt_int(m['pageviews'])}")
            .line(f"Отказов: {fmt_percent(m['bounce_rate'])}")
            .line(f"Время на сайте: {fmt_duration(m['avg_visit_duration'])}")
        )
        if data.metrika_top:
            screen = screen.blank().line("Топ-3 страницы:")
            for i, it in enumerate(data.metrika_top, start=1):
                url = shorten_url(it.get("url") or "—", max_len=40)
                pv = fmt_int(it.get("pageviews") or 0)
                screen = screen.line(f"  {i}. {url} — {pv}")
    else:
        screen = screen.line("— нет данных")

    # --- Блог ---
    screen = screen.section(E.DOC, TXT.BAMBOODOM_DIGEST_SECTION_BLOG)
    if data.blog_total is not None:
        screen = screen.line(f"Всего статей: {data.blog_total}")
        if data.blog_published_yesterday is not None:
            screen = screen.line(f"Опубликовано вчера: {data.blog_published_yesterday}")
    else:
        screen = screen.line("— нет данных (проверьте BAMBOODOM_BLOG_KEY)")

    # --- Я.Вебмастер ---
    screen = screen.section(E.SYNC, TXT.BAMBOODOM_DIGEST_SECTION_YW)
    quota = data.yw_quota or {}
    if quota:
        daily = quota.get("daily_quota")
        used = quota.get("used")
        rem = quota.get("quota_remainder")
        if daily is not None:
            if used is None and rem is not None:
                used = int(daily) - int(rem)
            screen = screen.line(f"Квота на сегодня: {used or 0} / {daily}")
    if data.yw_queue_count is not None:
        screen = screen.line(f"Отправлено вчера: {data.yw_queue_count}")
    if not quota and data.yw_queue_count is None:
        screen = screen.line("— нет данных")

    # --- Ошибки ---
    if data.errors:
        screen = screen.section(E.WARNING, "Сбои источников")
        for err in data.errors[:5]:
            screen = screen.line(f"  — {err[:120]}")

    return screen.build()


async def collect_and_render() -> str:
    data = await collect_digest()
    return render_digest(data)
