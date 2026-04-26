"""VK community wall.post анонс новой статьи (4L).

Использует community access token (создаётся в настройках группы → Работа с API).
Этот токен отличается от user OAuth tokens из services/publishers/vk.py.

Env:
- BAMBOODOM_VK_TOKEN — community access token (длинная строка, начинается с vk1.a...)
- BAMBOODOM_VK_GROUP_ID — числовой ID группы (положительное число, без минуса)

Если переменные не настроены — анонс скипается тихо (graceful degrade).
"""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from bot.config import get_settings

log = structlog.get_logger()

VK_API = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


async def announce_to_vk(title: str, url: str, excerpt: str = "", image_url: str = "") -> bool:
    """Публикует анонс в стену сообщества bamboodom-ru.

    Возвращает True если успех, False — skip / error (не валит публикацию).
    """
    s = get_settings()
    token = s.bamboodom_vk_token.get_secret_value() if s.bamboodom_vk_token else ""
    group_id = s.bamboodom_vk_group_id
    if not token or not group_id:
        log.debug("vk_announce_skipped_no_config")
        return False

    text_parts: list[str] = [title.strip()]
    if excerpt:
        text_parts.append("")
        text_parts.append(excerpt.strip()[:280])
    text_parts.append("")
    text_parts.append(url)
    message = "\n".join(text_parts)

    params: dict[str, Any] = {
        "owner_id": f"-{group_id}",
        "from_group": 1,
        "message": message,
        "access_token": token,
        "v": VK_API_VERSION,
    }
    # Если есть картинка — VK не принимает прямой URL, нужен upload.
    # Пока поддержка только текст+ссылка (VK сам сделает превью со страницы статьи
    # если на ней есть Open Graph теги).

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{VK_API}/wall.post", data=params, timeout=15.0)
        data = resp.json()
        if "error" in data:
            log.warning("vk_announce_error", err=data.get("error"))
            return False
        log.info("vk_announce_sent", post_id=(data.get("response") or {}).get("post_id"))
        return True
    except Exception as exc:
        log.warning("vk_announce_exception", error=str(exc)[:200])
        return False
