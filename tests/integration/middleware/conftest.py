"""Fixtures specific to middleware integration tests.

The key challenge is that aiogram's message.answer() internally calls
`await bot(SendMessage(...))`, so the mock bot must support __call__ as async.

Additionally, aiogram Router objects are module-level singletons that can only
be attached to one parent. We must detach them between fixture invocations.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Dispatcher, Router
from aiogram.types import Chat, Message

from bot.middlewares import (
    AuthMiddleware,
    DBSessionMiddleware,
    FSMInactivityMiddleware,
    LoggingMiddleware,
    ThrottlingMiddleware,
)
from cache.fsm_storage import UpstashFSMStorage
from tests.integration.conftest import (
    ADMIN_ID,
    MockRedisClient,
    MockSupabaseClient,
)


def _make_fake_message(**kwargs: Any) -> MagicMock:
    """Create a fake Message-like object returned from bot API calls."""
    msg = MagicMock(spec=Message)
    msg.message_id = kwargs.get("message_id", 1)
    msg.chat = MagicMock(spec=Chat)
    msg.chat.id = kwargs.get("chat_id", 123456789)
    msg.text = kwargs.get("text", "response")
    return msg



@pytest.fixture
def mock_bot() -> AsyncMock:
    """Override parent mock_bot with one that supports async __call__.

    Aiogram's Method.emit() does `return await bot(method)`, so the bot
    must be async-callable. Using AsyncMock as the base ensures that
    `await bot(...)` works.
    """
    bot = AsyncMock()
    bot.id = 1234567890
    bot.token = "123:FAKE"

    # Core API methods (for test assertions on call counts)
    bot.send_message = AsyncMock(return_value=_make_fake_message())
    bot.edit_message_text = AsyncMock(return_value=_make_fake_message())
    bot.edit_message_reply_markup = AsyncMock(return_value=_make_fake_message())
    bot.answer_callback_query = AsyncMock(return_value=True)
    bot.delete_message = AsyncMock(return_value=True)
    bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
    bot.set_webhook = AsyncMock(return_value=True)
    bot.session = MagicMock()
    bot.session.close = AsyncMock()

    _send_tracker = bot.send_message

    async def _bot_call(method: Any) -> Any:
        """Handle `await bot(method)` from aiogram Method.emit()."""
        method_name = type(method).__name__
        fake_msg = _make_fake_message()

        if method_name == "SendMessage":
            await _send_tracker(method.chat_id, method.text, reply_markup=method.reply_markup)
            return fake_msg
        if method_name == "EditMessageText":
            await bot.edit_message_text(
                chat_id=method.chat_id,
                message_id=method.message_id,
                text=method.text,
            )
            return fake_msg
        if method_name == "DeleteMessage":
            await bot.delete_message(chat_id=method.chat_id, message_id=method.message_id)
            return True
        if method_name == "AnswerCallbackQuery":
            await bot.answer_callback_query(method.callback_query_id)
            return True
        if method_name == "SetMyCommands":
            return True

        return fake_msg

    bot.side_effect = _bot_call
    return bot


@pytest.fixture
def dispatcher(
    mock_db: MockSupabaseClient,
    mock_redis: MockRedisClient,
    mock_http_client: MagicMock,
    mock_settings: MagicMock,
    mock_services: dict[str, MagicMock],
) -> Dispatcher:
    """Override parent dispatcher with router detachment support.

    Aiogram Router singletons can only have one parent. Between tests
    we must detach them before re-including in a new Dispatcher.
    """
    storage = UpstashFSMStorage(mock_redis, state_ttl=86400)
    dp = Dispatcher(storage=storage)

    # Outer middleware: inject DB, Redis, httpx
    dp.update.outer_middleware(DBSessionMiddleware(mock_db, mock_redis, mock_http_client))

    # Inner middleware on all event types
    for observer in (dp.message, dp.callback_query, dp.pre_checkout_query):
        observer.middleware(AuthMiddleware(ADMIN_ID))
        observer.middleware(ThrottlingMiddleware(mock_redis))
        observer.middleware(FSMInactivityMiddleware(1800))
        observer.middleware(LoggingMiddleware())

    # Import individual routers — these are module-level singletons
    from routers.admin import router as admin_router
    from routers.analysis import router as analysis_router
    from routers.categories import router as categories_router
    from routers.help import router as help_router
    from routers.payments import router as payments_router
    from routers.platforms import router as platforms_router
    from routers.profile import router as profile_router
    from routers.projects import router as projects_router
    from routers.publishing import router as publishing_router
    from routers.settings import router as settings_router
    from routers.start import router as start_router
    from routers.tariffs import router as tariffs_router

    all_routers = [
        admin_router, help_router, start_router, projects_router,
        categories_router, platforms_router, publishing_router,
        analysis_router, profile_router, settings_router,
        tariffs_router, payments_router,
    ]

    # Detach top-level routers from any existing parent (aiogram singleton constraint)
    # We only detach from the root/test_root level, NOT internal sub-routers
    for r in all_routers:
        if r._parent_router is not None:
            parent = r._parent_router
            if r in parent.sub_routers:
                parent.sub_routers.remove(r)
            r._parent_router = None

    # Build fresh root and include
    root = Router(name="test_root")
    for r in all_routers:
        root.include_router(r)

    dp.include_router(root)

    # Inject service mocks into workflow_data
    for name, svc in mock_services.items():
        dp.workflow_data[name] = svc

    return dp
