"""AuthMiddleware + FSMInactivityMiddleware."""

import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InaccessibleMessage, Message, TelegramObject

from db.client import SupabaseClient
from db.models import UserCreate
from db.repositories.users import UsersRepository
from keyboards.reply import main_menu

log = structlog.get_logger()


class AuthMiddleware(BaseMiddleware):
    """Inner middleware (#2): auto-registers user, injects data["user"] and data["is_admin"].

    On every incoming event with a user:
    1. Get or create user in DB (only updates username/name if changed)
    2. Set data["user"] = User model
    3. Set data["is_admin"] = bool (user.id == ADMIN_ID)
    """

    def __init__(self, admin_id: int) -> None:
        self._admin_id = admin_id

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        if tg_user is None:
            return await handler(event, data)

        db: SupabaseClient = data["db"]
        repo = UsersRepository(db)

        user, _is_new = await repo.get_or_create(
            UserCreate(
                id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                last_name=tg_user.last_name,
            )
        )

        data["user"] = user
        data["is_new_user"] = _is_new
        data["is_admin"] = user.id == self._admin_id
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
            await self._send_expired_message(event, data)
            return None  # drop event

        await state.update_data(last_update_time=now)
        return await handler(event, data)

    @staticmethod
    async def _send_expired_message(event: TelegramObject, data: dict[str, Any]) -> None:
        """Send session expired notification and restore main menu keyboard."""
        text = "Сессия истекла. Начните заново."
        is_admin = data.get("is_admin", False)
        kb = main_menu(is_admin=is_admin)
        if isinstance(event, Message):
            await event.answer(text, reply_markup=kb)
        elif isinstance(event, CallbackQuery):
            if event.message and not isinstance(event.message, InaccessibleMessage):
                await event.message.answer(text, reply_markup=kb)
            await event.answer()
