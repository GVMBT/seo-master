"""AuthMiddleware + FSMInactivityMiddleware."""

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from cache.client import RedisClient
from cache.keys import USER_CACHE_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import User, UserCreate, UserUpdate
from db.repositories.users import UsersRepository

log = structlog.get_logger()


class AuthMiddleware(BaseMiddleware):
    """Inner middleware (#2): auto-registers user, injects data["user"] and data["is_admin"].

    Uses Redis cache (5 min TTL) to avoid Supabase calls on every request.
    Cache miss → Supabase get_or_create → cache result.
    last_activity is updated only on cache miss (every ~5 min).
    """

    def __init__(self, admin_ids: list[int]) -> None:
        self._admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        redis: RedisClient = data["redis"]
        cache_key = CacheKeys.user_cache(tg_user.id)

        # Try Redis cache first
        cached = await redis.get(cache_key)
        if cached is not None:
            user = User(**json.loads(cached))
            data["user"] = user
            data["is_new_user"] = False
            data["is_admin"] = user.id in self._admin_ids
            return await handler(event, data)

        # Cache miss — hit Supabase
        db: SupabaseClient = data["db"]
        repo = UsersRepository(db)

        user, is_new = await repo.get_or_create(
            UserCreate(
                id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
            )
        )

        # Auto-promote: ADMIN_IDS is the single source of truth for admin role
        if user.id in self._admin_ids and user.role != "admin":
            await repo.update(user.id, UserUpdate(role="admin"))
            user = user.model_copy(update={"role": "admin"})
            log.info("admin_auto_promoted", user_id=user.id)

        # Cache user in Redis (5 min TTL)
        await redis.set(
            cache_key,
            json.dumps(user.model_dump(), ensure_ascii=False, default=str),
            ex=USER_CACHE_TTL,
        )

        data["user"] = user
        data["is_new_user"] = is_new
        data["is_admin"] = user.id in self._admin_ids
        return await handler(event, data)


class FSMInactivityMiddleware(BaseMiddleware):
    """Inner middleware (#4): auto-resets FSM after inactivity timeout.

    Checks last_update_time in state.data. If expired:
    - Clears FSM state
    - Sends "Сессия истекла" message
    - Drops the event

    Otherwise updates last_update_time.
    """

    def __init__(self, inactivity_timeout: int = 1800) -> None:
        self._timeout = inactivity_timeout

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        state: FSMContext | None = data.get("state")
        if state is None:
            return await handler(event, data)

        current_state = await state.get_state()
        if current_state is None:
            return await handler(event, data)

        state_data = await state.get_data()
        last_update = state_data.get("last_update_time")
        now = time.time()

        if last_update and (now - float(last_update)) > self._timeout:
            await state.clear()
            tg_user = data.get("event_from_user")
            log.info("fsm_inactivity_timeout", user_id=tg_user.id if tg_user else None)

            # For /start and /cancel — don't block, let the handler show Dashboard.
            # Pipeline checkpoint in Redis survives FSM clear (E49).
            if isinstance(event, Message) and event.text and event.text.startswith(("/start", "/cancel")):
                return await handler(event, data)

            await self._send_expired_message(event, data)
            return None  # drop event

        await state.update_data(last_update_time=now)
        return await handler(event, data)

    @staticmethod
    async def _send_expired_message(event: TelegramObject, data: dict[str, Any]) -> None:
        """Send session expired notification with a button to return to dashboard."""
        text = "⏳ Сессия истекла."
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 Меню", callback_data="nav:dashboard")],
            ]
        )
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb)
        elif isinstance(event, CallbackQuery):
            if event.message and not isinstance(event.message, InaccessibleMessage):
                await event.message.answer(text, reply_markup=kb)
            await event.answer()
