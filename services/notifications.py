"""Notification batch builder — generates (user_id, text) lists.

Triggered by QStash cron. Zero Telegram deps (only builds text).
"""

from __future__ import annotations

import structlog

from db.client import SupabaseClient
from db.repositories.publications import PublicationsRepository
from db.repositories.users import UsersRepository

log = structlog.get_logger()

# Inactivity threshold for reactivation (days)
_REACTIVATION_DAYS = 14


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
                "\u26a0\ufe0f <b>Низкий баланс</b>\n\n"
                f"\U0001f4b0 Баланс: {u.balance} токенов\n\n"
                "Этого может не хватить для автопубликации. Пополните баланс."
            )
            result.append((u.id, text))
        log.info("notify_low_balance_built", count=len(result), threshold=threshold)
        return result

    async def build_weekly_digest(self) -> list[tuple[int, str]]:
        """Active users (last 30 days) with notify_news=True.

        H24: Uses batch query instead of N+1 per-user queries.
        Returns list of (user_id, message_text).
        """
        users = await self._users.get_active_users(days=30)
        eligible = [u for u in users if u.notify_news]
        if not eligible:
            log.info("notify_weekly_digest_built", count=0)
            return []

        # H24: single batch query for all publication counts
        pubs = PublicationsRepository(self._db)
        user_ids = [u.id for u in eligible]
        pub_counts = await pubs.get_stats_by_users_batch(user_ids)

        result: list[tuple[int, str]] = []
        for u in eligible:
            total = pub_counts.get(u.id, 0)
            text = (
                "\U0001f4ca <b>Еженедельный дайджест</b>\n\n"
                f"\U0001f4dd Публикаций за все время: {total}\n"
                f"\U0001f4b0 Баланс: {u.balance} токенов\n\n"
                "Продолжайте публиковать контент!"
            )
            result.append((u.id, text))
        log.info("notify_weekly_digest_built", count=len(result))
        return result

    async def build_reactivation(self) -> list[tuple[int, str]]:
        """Inactive users (>14 days) for reactivation.

        Returns list of (user_id, message_text).
        """
        users = await self._users.get_inactive_users(days=_REACTIVATION_DAYS)
        result: list[tuple[int, str]] = []
        for u in users:
            text = (
                "\U0001f44b <b>Мы скучаем!</b>\n\n"
                f"Вы не заходили более {_REACTIVATION_DAYS} дней.\n"
                f"\U0001f4b0 На балансе: {u.balance} токенов.\n\n"
                "Вернитесь и продолжите публикации!"
            )
            result.append((u.id, text))
        log.info("notify_reactivation_built", count=len(result))
        return result
