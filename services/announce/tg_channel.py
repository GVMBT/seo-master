"""Анонс новой production-статьи в TG-канал (4G.tg).

Когда AI-публикация успешно прошла в production (sandbox=False, draft=False),
бот шлёт пост в канал указанный в `BAMBOODOM_TG_CHANNEL`.

Канал может быть `@username` или числовой `-100xxxxxxxxxx`. Бот должен
быть админом канала с правом «Post Messages».

Тихий режим: если переменная не задана или channel_id=='', анонс пропускается.
Если бот не админ — лог warning, пользователю не валим.
"""

from __future__ import annotations

from typing import Any

import structlog

from bot.config import get_settings

log = structlog.get_logger()


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


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def announce_article(
    bot: Any,
    title: str,
    url: str | None,
    excerpt: str = "",
    extra_text: str = "",
) -> bool:
    """Постит анонс в TG-канал. Возвращает True если успешно, False — если skip/error.

    Важно: НЕ бросает исключения. Любая ошибка → log.warning + return False.
    Это чтобы не валить публикацию статьи если канал недоступен.
    """
    channel = _resolve_channel()
    if not channel:
        log.debug("tg_announce_skipped_no_channel")
        return False

    text = _build_post_text(title, url, excerpt, extra_text=extra_text)
    try:
        await bot.send_message(channel, text, parse_mode="HTML", disable_web_page_preview=False)
        log.info("tg_announce_sent", channel=channel, title=title[:80])
        return True
    except Exception as exc:
        log.warning("tg_announce_failed", channel=channel, exc_info=True, error=str(exc)[:200])
        return False
