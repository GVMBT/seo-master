"""Анонс новой production-статьи в TG-канал (4G.tg).

Когда AI-публикация успешно прошла в production (sandbox=False, draft=False),
бот шлёт пост в канал указанный в `BAMBOODOM_TG_CHANNEL`.

Канал может быть `@username` или числовой `-100xxxxxxxxxx`. Бот должен
быть админом канала с правом «Post Messages».

Тихий режим: если переменная не задана или channel_id=='', анонс пропускается.
Если бот не админ — лог warning, пользователю не валим.

4W (2026-04-27): теперь принимаем cover_url. Если cover есть — постим как
send_photo с caption (TG лимит caption 1024 chars), без cover — fallback
на send_message как раньше.
"""

from __future__ import annotations

from typing import Any

import structlog

from bot.config import get_settings

log = structlog.get_logger()


# TG limit for send_photo caption is 1024 characters.
_TG_CAPTION_MAX = 1024


def _resolve_channel() -> str | None:
    s = get_settings()
    raw = (s.bamboodom_tg_channel or "").strip()
    if not raw:
        return None
    # Если просто 'name' без @ — считаем что username
    if not raw.startswith("@") and not raw.startswith("-"):
        raw = "@" + raw
    return raw


def _build_post_text(
    title: str,
    url: str | None,
    excerpt: str = "",
    extra_text: str = "",
) -> str:
    """Формирует HTML-пост для канала. Тайтл + excerpt + первый абзац + ссылка.

    v14 (2026-04-26): excerpt лимит 280 → 600, плюс опциональный
    extra_text (первый p-блок статьи) ещё до 700 символов. Раньше
    пост был слишком короткий — теперь даём читателю первый кусок
    статьи перед кликом.
    """
    parts: list[str] = []
    parts.append(f"<b>{_escape_html(title.strip())}</b>")
    if excerpt:
        parts.append("")
        parts.append(_escape_html(excerpt.strip()[:600]))
    if extra_text:
        parts.append("")
        parts.append(_escape_html(extra_text.strip()[:700]))
    if url:
        parts.append("")
        parts.append(f'<a href="{_escape_html(url)}">Читать на bamboodom.ru</a>')
    return "\n".join(parts)


def _build_caption(
    title: str,
    url: str | None,
    excerpt: str = "",
    extra_text: str = "",
) -> str:
    """4W: caption-вариант для send_photo с лимитом 1024 chars.

    Стратегия: тайтл всегда, потом ссылка, потом excerpt+extra по остатку.
    Так чтобы клик на статью был всегда доступен, даже если текст обрезался.
    """
    title_html = f"<b>{_escape_html(title.strip())}</b>"
    link_html = (
        f'<a href="{_escape_html(url)}">Читать на bamboodom.ru</a>' if url else ""
    )
    fixed = title_html + ("\n\n" + link_html if link_html else "")
    fixed_len = len(fixed)
    # Reserve a few chars for separators between excerpt and extra_text.
    budget = _TG_CAPTION_MAX - fixed_len - 8
    if budget <= 0:
        return fixed[:_TG_CAPTION_MAX]

    body_parts: list[str] = []
    body_remaining = budget
    if excerpt:
        chunk = _escape_html(excerpt.strip())[: min(600, body_remaining)]
        if chunk:
            body_parts.append(chunk)
            body_remaining -= len(chunk) + 2
    if extra_text and body_remaining > 60:
        chunk = _escape_html(extra_text.strip())[: min(700, body_remaining)]
        if chunk:
            body_parts.append(chunk)

    body = "\n\n".join(body_parts).strip()
    if not body:
        return fixed
    out = title_html + "\n\n" + body
    if link_html:
        out += "\n\n" + link_html
    return out[:_TG_CAPTION_MAX]


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def announce_article(
    bot: Any,
    title: str,
    url: str | None,
    excerpt: str = "",
    extra_text: str = "",
    cover_url: str | None = None,
) -> bool:
    """Постит анонс в TG-канал. Возвращает True если успешно, False — если skip/error.

    Важно: НЕ бросает исключения. Любая ошибка → log.warning + return False.
    Это чтобы не валить публикацию статьи если канал недоступен.

    4W (2026-04-27): если cover_url задан, постим через send_photo с caption.
    Иначе fallback на send_message с full text. Если send_photo упал
    (например URL недоступен) — пробуем send_message, чтобы хоть текст ушёл.
    """
    channel = _resolve_channel()
    if not channel:
        log.debug("tg_announce_skipped_no_channel")
        return False

    cover_clean = (cover_url or "").strip()

    if cover_clean:
        caption = _build_caption(title, url, excerpt, extra_text=extra_text)
        try:
            await bot.send_photo(
                channel,
                photo=cover_clean,
                caption=caption,
                parse_mode="HTML",
            )
            log.info(
                "tg_announce_sent",
                channel=channel,
                title=title[:80],
                with_cover=True,
            )
            return True
        except Exception as exc:
            log.warning(
                "tg_announce_photo_failed_fallback_to_text",
                channel=channel,
                cover=cover_clean[:120],
                error=str(exc)[:200],
            )
            # fall through to send_message fallback below

    text = _build_post_text(title, url, excerpt, extra_text=extra_text)
    try:
        await bot.send_message(
            channel, text, parse_mode="HTML", disable_web_page_preview=False
        )
        log.info(
            "tg_announce_sent",
            channel=channel,
            title=title[:80],
            with_cover=False,
        )
        return True
    except Exception as exc:
        log.warning(
            "tg_announce_failed",
            channel=channel,
            exc_info=True,
            error=str(exc)[:200],
        )
        return False
