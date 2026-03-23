"""Telegram connection wizard (ConnectTelegramFSM)."""

import time
from collections.abc import Sequence

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound, TelegramUnauthorizedError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.connections import TG_STEP1_CHANNEL, TG_STEP2_BOT_SETUP, TG_STEP3_TOPIC
from bot.texts.emoji import E
from bot.texts.screens import Screen
from bot.validators import TG_CHANNEL_RE
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from keyboards.inline import cancel_kb, connection_list_kb, menu_kb
from routers.platforms._shared import _cancel_connection_wizard
from services.connections import ConnectionService

log = structlog.get_logger()
router = Router()


class ConnectTelegramFSM(StatesGroup):
    channel = State()
    token = State()
    topic = State()  # forum topic selection (if is_forum)


@router.callback_query(F.data.regexp(r"^conn:\d+:add:telegram$"))
async def start_tg_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start Telegram connection wizard."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    project_id = int(cb_data.split(":")[1])
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await callback.answer(S.PROJECT_NOT_FOUND, show_alert=True)
        return

    # Rule: 1 project = max 1 Telegram connection
    conn_svc = ConnectionService(db, http_client)
    existing_tg = await conn_svc.get_by_project_and_platform(project_id, "telegram")
    if existing_tg:
        await callback.answer(
            S.CONNECTIONS_TG_ALREADY,
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(S.FSM_INTERRUPTED.format(name=interrupted))

    await state.set_state(ConnectTelegramFSM.channel)
    await state.update_data(last_update_time=time.time(), connect_project_id=project_id)

    await msg.answer(
        TG_STEP1_CHANNEL,
        reply_markup=cancel_kb(f"conn:{project_id}:tg_cancel"),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()


@router.message(ConnectTelegramFSM.channel, F.text)
async def tg_process_channel(message: Message, state: FSMContext) -> None:
    """TG step 1: channel identifier."""
    text = (message.text or "").strip()
    if text == "\u041e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    if not TG_CHANNEL_RE.match(text):
        await message.answer(S.VALIDATION_CHANNEL_INVALID)
        return

    # Normalize to consistent format
    channel_id = text
    if text.startswith("https://t.me/") or text.startswith("http://t.me/") or text.startswith("t.me/"):
        channel_id = "@" + text.split("/")[-1]

    data = await state.update_data(tg_channel=channel_id)
    pid = data.get("connect_project_id", 0)
    await state.set_state(ConnectTelegramFSM.token)
    await message.answer(
        TG_STEP2_BOT_SETUP,
        reply_markup=cancel_kb(f"conn:{pid}:tg_cancel"),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@router.message(ConnectTelegramFSM.token, F.text)
async def tg_process_token(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """TG step 2: bot token -- validate and create connection."""
    text = (message.text or "").strip()

    if text == "\u041e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    # Delete message with token for security (after cancel check)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("failed_to_delete_token_message", reason=str(exc))

    # Validate bot token format (roughly: digits:alphanumeric)
    if ":" not in text or len(text) < 30:
        await message.answer(S.VALIDATION_TOKEN_INVALID)
        return

    data = await state.get_data()
    channel_id = data["tg_channel"]
    project_id = int(data["connect_project_id"])

    # Validate via getMe + check admin status (single try/finally for session cleanup)
    temp_bot = Bot(token=text)
    try:
        try:
            bot_info = await temp_bot.get_me()
        except TelegramUnauthorizedError:
            await message.answer(S.CONN_TG_INVALID_TOKEN)
            return
        except Exception as exc:
            log.warning("tg_connect_bot_check_failed", error=str(exc))
            await message.answer(S.CONN_TG_INVALID_TOKEN)
            return

        # Check bot is admin of the channel
        try:
            admins = await temp_bot.get_chat_administrators(channel_id)
        except TelegramBadRequest as exc:
            log.warning("tg_connect_channel_error", channel=channel_id, error=str(exc))
            await message.answer(S.CONN_TG_VERIFY_ERROR.format(channel=channel_id))
            return
        except Exception as exc:
            log.warning("tg_connect_admin_check_failed", channel=channel_id, error=str(exc))
            await message.answer(S.CONN_TG_VERIFY_ERROR.format(channel=channel_id))
            return

        bot_is_admin = any(a.user.id == bot_info.id for a in admins)
        if not bot_is_admin:
            await message.answer(
                S.CONN_VK_NOT_ADMIN.format(username=bot_info.username or "", channel=channel_id),
            )
            return

        # Detect forum (supergroup with topics enabled)
        try:
            chat_obj = await temp_bot.get_chat(channel_id)
            is_forum = getattr(chat_obj, "is_forum", False) or False
        except Exception:
            log.warning("tg_forum_detect_failed", channel=channel_id)
            is_forum = False
    finally:
        await temp_bot.session.close()

    conn_svc = ConnectionService(db, http_client)

    # Rule: 1 project = max 1 Telegram connection
    existing_tg = await conn_svc.get_by_project_and_platform(project_id, "telegram")
    if existing_tg:
        await message.answer(S.CONN_TG_ALREADY_SHORT)
        return

    # E41: Telegram requires GLOBAL uniqueness -- channel must not be connected by ANY user
    existing = await conn_svc.get_by_identifier_global(channel_id, "telegram")
    if existing:
        await message.answer(S.CONN_TG_GLOBAL_DUP.format(channel=channel_id))
        log.warning("tg_global_duplicate_blocked", channel=channel_id, existing_conn=existing.id)
        return

    # Save token for later use (topic step or direct creation)
    await state.update_data(
        tg_bot_token=text,
        tg_bot_username=bot_info.username or "",
        tg_is_forum=is_forum,
    )

    if is_forum:
        # Forum detected -- fetch topic list via MTProto and show selector
        settings = get_settings()
        from services.external.mtproto import get_forum_topics

        topics = await get_forum_topics(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash.get_secret_value(),
            bot_token=text,
            chat_id=channel_id,
        )
        await state.update_data(tg_topics=[{"id": t.thread_id, "name": t.name} for t in topics])
        await state.set_state(ConnectTelegramFSM.topic)
        await message.answer(
            TG_STEP3_TOPIC,
            reply_markup=_tg_topic_selector_kb(project_id, topics),
        )
        return

    # Regular channel -- create connection immediately
    await _finalize_tg_connection(message, state, user, db, http_client)


async def _finalize_tg_connection(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    *,
    topic_name: str | None = None,
    thread_id: int | None = None,
) -> None:
    """Create Telegram connection with optional forum topic."""
    data = await state.get_data()
    channel_id = data["tg_channel"]
    project_id = int(data["connect_project_id"])
    token = data["tg_bot_token"]
    bot_username = data.get("tg_bot_username", "")

    await state.clear()

    raw_creds: dict[str, str | int] = {"bot_token": token, "channel_id": channel_id}
    if thread_id is not None:
        raw_creds["message_thread_id"] = thread_id

    metadata: dict[str, str | int] = {"bot_username": bot_username}
    if topic_name:
        metadata["topic_name"] = topic_name

    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="telegram",
            identifier=channel_id,
            metadata=metadata,
        ),
        raw_credentials=raw_creds,
    )

    log.info(
        "telegram_connected",
        conn_id=conn.id, project_id=project_id,
        channel=channel_id, thread_id=thread_id,
    )

    connections = await conn_svc.get_by_project(project_id)

    if topic_name:
        success_text = S.CONN_TG_SUCCESS_TOPIC.format(channel=channel_id, topic=topic_name)
        hint_text = S.CONN_TG_HINT_TOPIC.format(topic=topic_name)
    else:
        success_text = S.CONN_TG_SUCCESS.format(channel=channel_id)
        hint_text = S.CONN_TG_HINT

    conn_text = (
        Screen(E.CHECK, S.CONN_CONNECTED_TITLE)
        .blank()
        .line(success_text)
        .hint(hint_text)
        .build()
    )
    await message.answer(
        conn_text,
        reply_markup=connection_list_kb(connections, project_id),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def _tg_topic_selector_kb(
    project_id: int,
    topics: Sequence[object] | None = None,
) -> InlineKeyboardMarkup:
    """Keyboard for forum topic selection: list of real topics + General + Cancel."""
    from services.external.mtproto import TopicInfo

    rows: list[list[InlineKeyboardButton]] = []
    if topics:
        for t in topics:
            if isinstance(t, TopicInfo):
                rows.append([InlineKeyboardButton(
                    text=f"\U0001f4cc {t.name}",
                    callback_data=f"conn:{project_id}:tg_topic:{t.thread_id}",
                )])
    rows.append([InlineKeyboardButton(
        text="\U0001f4ec \u0412 \u043e\u0441\u043d\u043e\u0432\u043d\u043e\u0439 \u0447\u0430\u0442",
        callback_data=f"conn:{project_id}:tg_topic:0",
    )])
    rows.append([InlineKeyboardButton(
        text="\u274c \u041e\u0442\u043c\u0435\u043d\u0430",
        callback_data=f"conn:{project_id}:tg_cancel",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(
    ConnectTelegramFSM.topic,
    F.data.regexp(r"^conn:\d+:tg_topic:\d+$"),
)
async def tg_topic_choice(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Handle forum topic selection -- real topic ID or 0 for General."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    thread_id = int(cb_data.split(":")[-1])

    if thread_id == 0:
        # General / no topic
        await _finalize_tg_connection(msg, state, user, db, http_client)
        await callback.answer()
        return

    # Find topic name from stored list
    data = await state.get_data()
    topics_data: list[dict[str, object]] = data.get("tg_topics", [])
    topic_name = next(
        (str(t["name"]) for t in topics_data if t.get("id") == thread_id),
        f"Topic #{thread_id}",
    )

    await _finalize_tg_connection(
        msg, state, user, db, http_client,
        topic_name=topic_name, thread_id=thread_id,
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Cancel handler
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:\d+:tg_cancel$"))
async def cancel_tg_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Cancel Telegram connection via inline button."""
    await _cancel_connection_wizard(callback, state, user, db, http_client, project_service_factory)
