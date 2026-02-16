"""Notification batch builder — generates (user_id, text) lists.

Triggered by QStash cron. Zero Telegram deps (only builds text).
"""

from __future__ import annotations

import structlog

from db.client import SupabaseClient
from db.repositories.publications import PublicationsRepository
from db.repositories.users import UsersRepository

log = structlog.get_logger()


class NotifyService:
    """Build notification batches for different trigger types."""

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._users = UsersRepository(db)

    async def build_low_balance(self, threshold: int = 100) -> list[tuple[int, str]]:
        """Users with balance < threshold and notify_balance=True.

        Returns list of (user_id, message_text).
        """
        users = await self._users.get_low_balance_users(threshold)
        result: list[tuple[int, str]] = []
        for u in users:
            text = (
                f"<b>Баланс: {u.balance} токенов</b>\n\n"
                "Этого может не хватить для автопубликации.\n"
                "Пополните баланс, чтобы не пропустить запланированные посты."
            )
            result.append((u.id, text))
        log.info("notify_low_balance_built", count=len(result), threshold=threshold)
        return result

    async def build_weekly_digest(self) -> list[tuple[int, str]]:
        """Active users (last 30 days) with notify_news=True.

        Returns list of (user_id, message_text).
        """
        users = await self._users.get_active_users(days=30)
        pubs = PublicationsRepository(self._db)
        result: list[tuple[int, str]] = []

        for u in users:
            if not u.notify_news:
                continue
            stats = await pubs.get_stats_by_user(u.id)
            total = stats.get("total_publications", 0)
            text = (
                "<b>Еженедельный дайджест</b>\n\n"
                f"Публикаций за все время: {total}\n"
                f"Баланс: {u.balance} токенов\n\n"
                "Продолжайте публиковать контент для роста SEO-позиций!"
            )
            result.append((u.id, text))
        log.info("notify_weekly_digest_built", count=len(result))
        return result

    async def build_reactivation(self) -> list[tuple[int, str]]:
        """Inactive users (>14 days) for reactivation.

        Returns list of (user_id, message_text).
        """
        users = await self._users.get_inactive_users(days=14)
        result: list[tuple[int, str]] = []
        for u in users:
            text = (
                "<b>Мы скучаем!</b>\n\n"
                f"Вы не заходили {14}+ дней.\n"
                f"У вас на балансе: {u.balance} токенов.\n\n"
                "Вернитесь и продолжите публиковать SEO-контент!"
            )
            result.append((u.id, text))
        log.info("notify_reactivation_built", count=len(result))
        return result
