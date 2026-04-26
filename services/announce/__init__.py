"""Анонсы новых статей в TG/VK/Pinterest через connections-based publishers."""

from services.announce.social import announce_to_social
from services.announce.tg_channel import announce_article

__all__ = ["announce_article", "announce_to_social"]
