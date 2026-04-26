"""Pinterest Pin создание для новой статьи (4L).

Использует Pinterest API v5: POST /v5/pins с image_url + link + title + description.

Env:
- BAMBOODOM_PINTEREST_TOKEN — access_token (60-day, refresh manually)
- BAMBOODOM_PINTEREST_BOARD_ID — ID борды куда постить

Если переменные не настроены или у статьи нет image_url — skip.
"""

from __future__ import annotations

import httpx
import structlog

from bot.config import get_settings

log = structlog.get_logger()

PINTEREST_API = "https://api.pinterest.com/v5"


async def announce_to_pinterest(
    title: str,
    url: str,
    image_url: str = "",
    description: str = "",
) -> bool:
    """Создаёт Pin с картинкой, ссылкой на статью и описанием.

    Без image_url Pin создать нельзя — Pinterest требует медиа.
    Возвращает True если Pin создан, False — skip / error.
    """
    s = get_settings()
    token = s.bamboodom_pinterest_token.get_secret_value() if s.bamboodom_pinterest_token else ""
    board_id = s.bamboodom_pinterest_board_id
    if not token or not board_id:
        log.debug("pin_announce_skipped_no_config")
        return False
    if not image_url:
        log.debug("pin_announce_skipped_no_image")
        return False

    payload = {
        "board_id": board_id,
        "title": title[:100],
        "description": (description or title)[:500],
        "link": url,
        "media_source": {
            "source_type": "image_url",
            "url": image_url,
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{PINTEREST_API}/pins", json=payload, headers=headers, timeout=20.0)
        if resp.status_code >= 400:
            log.warning("pin_announce_http", status=resp.status_code, body=resp.text[:200])
            return False
        data = resp.json()
        log.info("pin_announce_sent", pin_id=data.get("id"))
        return True
    except Exception as exc:
        log.warning("pin_announce_exception", error=str(exc)[:200])
        return False
