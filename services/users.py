"""User service — referral linking, user-level business logic.

Zero dependencies on Telegram/Aiogram.
"""

import structlog

from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import UserUpdate
from db.repositories.users import UsersRepository

log = structlog.get_logger()


class UsersService:
    """Business logic for user operations.

    Thin router rule: routers call UsersService instead of
    accessing UsersRepository directly (CR-77b).
    """

    def __init__(self, db: SupabaseClient) -> None:
        self._db = db
        self._users = UsersRepository(db)

    async def link_referrer(
        self,
        user_id: int,
        referrer_id: int,
        redis: RedisClient,
    ) -> bool:
        """Link a referrer to a newly created user.

        Validates:
        - Not self-referral
        - Referrer exists

        On success: updates user.referrer_id, invalidates user cache.
        Returns True if referrer was linked, False otherwise.
        """
        if referrer_id == user_id:
            log.warning("referral_self_referral_blocked", user_id=user_id)
            return False

        referrer = await self._users.get_by_id(referrer_id)
        if not referrer:
            log.warning("referral_invalid_referrer", referrer_id=referrer_id)
            return False

        await self._users.update(user_id, UserUpdate(referrer_id=referrer_id))

        # Invalidate cached user so downstream sees referrer_id
        await redis.delete(CacheKeys.user_cache(user_id))

        log.info("referral_linked", user_id=user_id, referrer_id=referrer_id)
        return True
