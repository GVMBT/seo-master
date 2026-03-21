"""MTProto service — Pyrogram wrapper for Bot API gaps.

Used for operations not available via Telegram Bot API:
- channels.getForumTopics: list forum topics in a supergroup

Requires TELEGRAM_API_ID + TELEGRAM_API_HASH from https://my.telegram.org
Uses bot_token auth (not user session), in_memory (no session files).
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from pyrogram import Client
from pyrogram.raw.functions.channels import GetForumTopics
from pyrogram.raw.types import ForumTopic

log = structlog.get_logger()


@dataclass(frozen=True)
class TopicInfo:
    """Forum topic metadata."""

    thread_id: int
    name: str
    icon_color: int = 0


async def get_forum_topics(
    api_id: int,
    api_hash: str,
    bot_token: str,
    chat_id: int | str,
) -> list[TopicInfo]:
    """List forum topics in a supergroup via MTProto.

    Creates a temporary Pyrogram client with bot_token auth.
    Returns empty list on failure (graceful degradation).
    """
    if not api_id or not api_hash:
        log.warning("mtproto_not_configured", reason="TELEGRAM_API_ID/API_HASH not set")
        return []

    client = Client(
        name="seo_bot_topics",
        api_id=api_id,
        api_hash=api_hash,
        bot_token=bot_token,
        in_memory=True,
        no_updates=True,
    )
    try:
        async with client:
            peer = await client.resolve_peer(chat_id)
            result = await client.invoke(
                GetForumTopics(
                    channel=peer,  # type: ignore[arg-type]
                    offset_date=0,
                    offset_id=0,
                    offset_topic=0,
                    limit=100,
                ),
            )
            topics: list[TopicInfo] = []
            for topic in result.topics:
                if isinstance(topic, ForumTopic):
                    topics.append(
                        TopicInfo(
                            thread_id=topic.id,
                            name=topic.title,
                            icon_color=topic.icon_color or 0,
                        ),
                    )
            return topics
    except Exception:
        log.exception("mtproto_get_forum_topics_failed", chat_id=chat_id)
        return []
