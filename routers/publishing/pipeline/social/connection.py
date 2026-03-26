"""Social Pipeline — step 2: connection selection + inline connect wizards (F6.2).

FSM: SocialPipelineFSM states connect_tg_channel..connect_pinterest_board
     (8 states, FSM_SPEC.md section 2.2).
UX: UX_PIPELINE.md section 5.2, section 8.9.
Rules: .claude/rules/pipeline.md, security.md.

Design decisions:
- Inline wizards run WITHIN SocialPipelineFSM (not delegating to ConnectTelegramFSM).
- TG bot validation (Bot(token).get_me()) happens in handler, NOT in ConnectionService:
  aiogram.Bot is a Telegram dependency, services/ must remain Telegram-free.
- Pinterest board selection: stub in F6.2 (full impl requires Pinterest API /boards).
- VK: user provides group URL/ID → resolve → classic OAuth with group_ids.
"""

from __future__ import annotations

import html
import secrets
from collections.abc import Sequence

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from bot.validators import TG_CHANNEL_RE
from cache.client import RedisClient
from cache.keys import PINTEREST_AUTH_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from keyboards.inline import cancel_kb, menu_kb
from keyboards.pipeline import (
    pipeline_no_projects_kb,
    pipeline_projects_kb,
    social_connections_kb,
    social_no_connections_kb,
)
from routers.publishing.pipeline._common import (
    SocialPipelineFSM,
    save_checkpoint,
)
from services.connections import ConnectionService
from services.oauth.vk import VKOAuthError, VKOAuthService, parse_vk_group_input

log = structlog.get_logger()
router = Router()

_TOTAL_STEPS = 5

# Step header prefixes for social pipeline screens
_LH = f"{E.LINK} "   # Connection step (step 2)
_SH = f"{E.MEGAPHONE} "  # Project step (step 1, back nav)


# ---------------------------------------------------------------------------
# Step 2 entry: connection selection (shared helpers)
# ---------------------------------------------------------------------------


async def _show_connection_step(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
    *,
    http_client: httpx.AsyncClient,
    auto_skip: bool = True,
) -> None:
    """Show connection selection (step 2).

    UX_PIPELINE.md section 5.2:
    - 0 connections -> show platform picker
    - 1 connection -> auto-select, skip to step 3 (unless auto_skip=False)
    - >1 connections -> show list
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    from routers.publishing.pipeline.social.social import _show_category_step

    conn_svc = ConnectionService(db, http_client)
    social_conns = await conn_svc.get_social_connections(project_id)

    if len(social_conns) == 0:
        text = (
            Screen(E.LINK, S.POST_CONNECTION_TITLE.format(total=_TOTAL_STEPS))
            .blank()
            .line(S.POST_CONNECTION_EMPTY)
            .build()
        )
        await safe_edit_text(
            msg,
            text,
            reply_markup=social_no_connections_kb(),
        )
        await state.set_state(SocialPipelineFSM.select_connection)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_connection",
            pipeline_type="social",
            project_id=project_id,
            project_name=project_name,
        )
        return

    if len(social_conns) == 1 and auto_skip:
        conn = social_conns[0]
        await state.update_data(
            connection_id=conn.id, platform_type=conn.platform_type,
            connection_identifier=conn.identifier,
        )
        await _show_category_step(
            callback,
            state,
            user,
            db=db,
            redis=redis,
            project_id=project_id,
            project_name=project_name,
        )
        return

    text = (
        Screen(E.LINK, S.POST_CONNECTION_TITLE.format(total=_TOTAL_STEPS))
        .blank()
        .line(S.POST_CONNECTION_QUESTION)
        .build()
    )
    await safe_edit_text(
        msg,
        text,
        reply_markup=social_connections_kb(social_conns, project_id),
    )
    await state.set_state(SocialPipelineFSM.select_connection)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_connection",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
    )


async def _show_connection_step_msg(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_id: int,
    project_name: str,
    *,
    http_client: httpx.AsyncClient,
) -> None:
    """Show connection selection via message (non-edit context)."""
    from routers.publishing.pipeline.social.social import _show_category_step_msg

    conn_svc = ConnectionService(db, http_client)
    social_conns = await conn_svc.get_social_connections(project_id)

    if len(social_conns) == 0:
        text = (
            Screen(E.LINK, S.POST_CONNECTION_TITLE.format(total=_TOTAL_STEPS))
            .blank()
            .line(S.POST_CONNECTION_EMPTY)
            .build()
        )
        await message.answer(
            text,
            reply_markup=social_no_connections_kb(),
        )
        await state.set_state(SocialPipelineFSM.select_connection)
        await save_checkpoint(
            redis,
            user.id,
            current_step="select_connection",
            pipeline_type="social",
            project_id=project_id,
            project_name=project_name,
        )
        return

    if len(social_conns) == 1:
        conn = social_conns[0]
        await state.update_data(
            connection_id=conn.id, platform_type=conn.platform_type,
            connection_identifier=conn.identifier,
        )
        await _show_category_step_msg(
            message,
            state,
            user,
            db=db,
            redis=redis,
            project_id=project_id,
            project_name=project_name,
        )
        return

    text = (
        Screen(E.LINK, S.POST_CONNECTION_TITLE.format(total=_TOTAL_STEPS))
        .blank()
        .line(S.POST_CONNECTION_QUESTION)
        .build()
    )
    await message.answer(
        text,
        reply_markup=social_connections_kb(social_conns, project_id),
    )
    await state.set_state(SocialPipelineFSM.select_connection)
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_connection",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
    )


# ---------------------------------------------------------------------------
# Back navigation: step 2 -> step 1 (project selection)
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_connection,
    F.data == "pipeline:social:back_project",
)
async def pipeline_back_to_project(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Go back from step 2 (connection) to step 1 (project selection)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    proj_svc = project_service_factory(db)
    projects = await proj_svc.list_by_user(user.id)

    if not projects:
        text = (
            Screen(E.MEGAPHONE, S.POST_PROJECT_TITLE.format(total=_TOTAL_STEPS))
            .blank()
            .line(S.POST_PROJECT_CREATE_HINT)
            .build()
        )
        await safe_edit_text(
            msg,
            text,
            reply_markup=pipeline_no_projects_kb(pipeline_type="social"),
        )
    else:
        text = (
            Screen(E.MEGAPHONE, S.POST_PROJECT_TITLE.format(total=_TOTAL_STEPS))
            .blank()
            .line(S.POST_PROJECT_QUESTION)
            .build()
        )
        await safe_edit_text(
            msg,
            text,
            reply_markup=pipeline_projects_kb(projects, pipeline_type="social"),
        )

    await state.set_state(SocialPipelineFSM.select_project)
    await save_checkpoint(redis, user.id, current_step="select_project", pipeline_type="social")
    await callback.answer()


# ---------------------------------------------------------------------------
# Handler: Select connection from list
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_connection,
    F.data.regexp(r"^pipeline:social:\d+:conn:\d+$"),
)
async def pipeline_select_connection(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Handle connection selection from list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return
    parts = callback.data.split(":")
    project_id = int(parts[2])
    conn_id = int(parts[4])

    # Verify ownership
    data = await state.get_data()
    fsm_project_id = data.get("project_id")
    if fsm_project_id and fsm_project_id != project_id:
        await callback.answer(S.PIPELINE_SESSION_EXPIRED, show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if conn is None or conn.project_id != project_id:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
        return

    project_name = data.get("project_name", "")
    await state.update_data(
        connection_id=conn.id, platform_type=conn.platform_type,
        connection_identifier=conn.identifier,
    )
    await save_checkpoint(
        redis,
        user.id,
        current_step="select_connection",
        pipeline_type="social",
        project_id=project_id,
        project_name=project_name,
        connection_id=conn.id,
    )

    from routers.publishing.pipeline.social.social import _show_category_step

    await _show_category_step(
        callback,
        state,
        user,
        db=db,
        redis=redis,
        project_id=project_id,
        project_name=project_name,
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Handler: "Add connection" from connections list
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_connection,
    F.data == "pipeline:social:add_connection",
)
async def pipeline_add_connection(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Show platform picker, hiding already connected types (P1-3 fix)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await callback.answer(S.PIPELINE_SESSION_EXPIRED, show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    connected_types = set(await conn_svc.get_platform_types_by_project(project_id))
    social_types = {"telegram", "vk", "pinterest"}
    already_connected = connected_types & social_types

    if already_connected == social_types:
        await callback.answer(S.POST_CONNECTION_ALL_CONNECTED, show_alert=True)
        return

    text = (
        Screen(E.LINK, S.POST_CONNECTION_TITLE.format(total=_TOTAL_STEPS))
        .blank()
        .line(S.POST_CONNECTION_PLATFORM_PICK)
        .build()
    )
    await safe_edit_text(msg,
        text,
        reply_markup=social_no_connections_kb(exclude_types=already_connected),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Inline Telegram Connect (3 states: channel -> token -> verify)
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_connection,
    F.data == "pipeline:social:connect:telegram",
)
async def pipeline_start_connect_tg(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Start inline TG connection — ask for channel ID."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.set_state(SocialPipelineFSM.connect_tg_channel)
    text = (
        Screen(E.LINK, S.POST_CONNECTION_TG_TITLE.format(total=_TOTAL_STEPS))
        .blank()
        .line(S.POST_CONNECTION_TG_PROMPT)
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=cancel_kb("pipeline:social:cancel"))
    await callback.answer()


@router.message(SocialPipelineFSM.connect_tg_channel, F.text)
async def pipeline_connect_tg_channel(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """TG inline step 1: validate channel ID, check uniqueness."""
    text = (message.text or "").strip()

    if not TG_CHANNEL_RE.match(text):
        await message.answer(
            S.POST_CONNECTION_TG_FORMAT_ERROR,
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    # Normalize to @channel format
    normalized = _normalize_tg_channel(text)

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await message.answer(S.PIPELINE_SESSION_EXPIRED, reply_markup=menu_kb())
        return

    conn_svc = ConnectionService(db, http_client)

    # Check 1 TG per project limit
    existing = await conn_svc.get_by_project_and_platform(project_id, "telegram")
    if existing:
        await message.answer(
            S.POST_CONNECTION_TG_DUPLICATE,
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    # E41: global uniqueness
    global_dup = await conn_svc.get_by_identifier_global(normalized, "telegram")
    if global_dup:
        await message.answer(
            S.POST_CONNECTION_TG_GLOBAL_DUP.format(channel=html.escape(normalized)),
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    await state.update_data(tg_channel=normalized)
    await state.set_state(SocialPipelineFSM.connect_tg_token)
    await message.answer(
        f"Канал: {html.escape(normalized)}\n\n{S.POST_CONNECTION_TG_TOKEN_PROMPT}",
        reply_markup=cancel_kb("pipeline:social:cancel"),
    )


@router.message(SocialPipelineFSM.connect_tg_token, F.text)
async def pipeline_connect_tg_token(
    message: Message,
    state: FSMContext,
) -> None:
    """TG inline step 2: validate token format, delete message for security."""
    text = (message.text or "").strip()

    # Delete message containing token (security)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("pipeline.failed_to_delete_token_message", reason=str(exc))

    if ":" not in text or len(text) < 30:
        await message.answer(
            S.POST_CONNECTION_TG_TOKEN_FORMAT,
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    data = await state.get_data()
    channel = data.get("tg_channel", "")

    await state.update_data(tg_token=text)
    await state.set_state(SocialPipelineFSM.connect_tg_verify)
    await message.answer(
        f"{S.POST_CONNECTION_TG_TOKEN_OK}\n\n"
        + S.POST_CONNECTION_TG_VERIFY_HINT.format(channel=html.escape(channel)),
        reply_markup=_tg_verify_kb(),
    )


@router.callback_query(
    SocialPipelineFSM.connect_tg_verify,
    F.data == "pipeline:social:tg_verify",
)
async def pipeline_connect_tg_verify(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """TG inline step 3: verify bot is admin in channel, create connection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    token = data.get("tg_token", "")
    channel = data.get("tg_channel", "")
    project_id = data.get("project_id")

    if not token or not channel or not project_id:
        await callback.answer(S.PIPELINE_SESSION_EXPIRED, show_alert=True)
        return

    # Validate bot token and check admin status (in handler — Bot is Aiogram dep)
    temp_bot: Bot | None = None
    try:
        temp_bot = Bot(token=token)
        bot_info = await temp_bot.get_me()

        try:
            admins = await temp_bot.get_chat_administrators(channel)
        except Exception:
            await safe_edit_text(msg,
                S.POST_CONNECTION_TG_ADMIN_ERROR,
                reply_markup=_tg_verify_retry_kb(),
            )
            await callback.answer()
            return

        # can_post_messages is None for supergroups/forums (only set for channels)
        is_admin = any(
            admin.user.id == bot_info.id
            and getattr(admin, "can_post_messages", None) is not False
            for admin in admins
        )

        if not is_admin:
            await safe_edit_text(msg,
                S.POST_CONNECTION_TG_NOT_ADMIN,
                reply_markup=_tg_verify_retry_kb(),
            )
            await callback.answer()
            return

        # Detect forum (supergroup with topics enabled)
        try:
            chat_obj = await temp_bot.get_chat(channel)
            is_forum = getattr(chat_obj, "is_forum", False) or False
        except Exception:
            log.warning("pipeline.tg_forum_detect_failed", channel=channel)
            is_forum = False

    except Exception as exc:
        log.warning("pipeline.tg_bot_validation_failed", error=str(exc))
        await safe_edit_text(msg,
            S.POST_CONNECTION_TG_BOT_ERROR,
            reply_markup=_tg_verify_retry_kb(),
        )
        await callback.answer()
        return
    finally:
        if temp_bot:
            await temp_bot.session.close()

    # Save bot info for later (topic step or direct creation)
    await state.update_data(
        tg_bot_username=bot_info.username or "",
        tg_is_forum=is_forum,
    )

    if is_forum:
        # Forum detected — fetch topic list via MTProto
        from bot.config import get_settings
        from services.external.mtproto import get_forum_topics
        settings = get_settings()
        topics = await get_forum_topics(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash.get_secret_value(),
            bot_token=token,
            chat_id=channel,
        )
        await state.update_data(
            tg_bot_username=bot_info.username or "",
            tg_topics=[{"id": t.thread_id, "name": t.name} for t in topics],
        )
        await state.set_state(SocialPipelineFSM.connect_tg_topic)
        await safe_edit_text(
            msg,
            _build_topic_text(),
            reply_markup=_pipeline_topic_selector_kb(topics),
        )
        await callback.answer()
        return

    # Regular channel — create connection immediately
    await _pipeline_finalize_tg(msg, state, user, db, redis, http_client)
    await callback.answer()


# ---------------------------------------------------------------------------
# Inline TG topic helpers (forum support)
# ---------------------------------------------------------------------------


def _build_topic_text() -> str:
    """Build topic selection prompt for pipeline."""
    from bot.texts.connections import TG_STEP3_TOPIC
    return TG_STEP3_TOPIC


def _pipeline_topic_selector_kb(
    topics: Sequence[object] | None = None,
) -> InlineKeyboardMarkup:
    """Keyboard: list of real topics + General + Cancel."""
    from services.external.mtproto import TopicInfo

    rows: list[list[InlineKeyboardButton]] = []
    if topics:
        for t in topics:
            if isinstance(t, TopicInfo):
                rows.append([InlineKeyboardButton(
                    text=f"\U0001f4cc {t.name}",
                    callback_data=f"pipeline:social:tg_topic:{t.thread_id}",
                )])
    rows.append([InlineKeyboardButton(
        text="\U0001f4ec \u0412 \u043e\u0441\u043d\u043e\u0432\u043d\u043e\u0439 \u0447\u0430\u0442",
        callback_data="pipeline:social:tg_topic:0",
    )])
    rows.append([InlineKeyboardButton(
        text="\u274c \u041e\u0442\u043c\u0435\u043d\u0430",
        callback_data="pipeline:social:cancel",
    )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _pipeline_finalize_tg(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    *,
    topic_name: str | None = None,
    thread_id: int | None = None,
) -> None:
    """Create Telegram connection and proceed to category step."""
    data = await state.get_data()
    token: str = data.get("tg_token", "")
    channel: str = data.get("tg_channel", "")
    project_id: int = int(data.get("project_id", 0))
    project_name: str = data.get("project_name", "")
    bot_username: str = data.get("tg_bot_username", "")

    raw_creds: dict[str, str | int] = {"bot_token": token, "channel_id": channel}
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
            identifier=channel,
            metadata=metadata,
        ),
        raw_credentials=raw_creds,
    )

    log.info(
        "pipeline.social.tg_connected",
        connection_id=conn.id,
        channel=channel,
        user_id=user.id,
        thread_id=thread_id,
    )

    await state.update_data(
        connection_id=conn.id, platform_type="telegram",
        connection_identifier=channel,
    )

    if topic_name:
        connected_text = S.POST_CONNECTION_TG_CONNECTED_TOPIC.format(
            channel=html.escape(channel), topic=html.escape(topic_name),
        )
    else:
        connected_text = S.POST_CONNECTION_TG_CONNECTED.format(channel=html.escape(channel))

    await safe_edit_text(msg, connected_text)

    from routers.publishing.pipeline.social.social import _show_category_step_msg

    await _show_category_step_msg(
        msg, state, user,
        db=db, redis=redis,
        project_id=project_id,
        project_name=project_name,
    )


@router.callback_query(
    SocialPipelineFSM.connect_tg_topic,
    F.data.regexp(r"^pipeline:social:tg_topic:\d+$"),
)
async def pipeline_tg_topic_choice(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Handle forum topic selection in pipeline — real topic ID or 0 for General."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    thread_id = int(cb_data.split(":")[-1])

    if thread_id == 0:
        # General / no topic
        await _pipeline_finalize_tg(msg, state, user, db, redis, http_client)
        await callback.answer()
        return

    # Find topic name from stored list
    data = await state.get_data()
    topics_data: list[dict[str, object]] = data.get("tg_topics", [])
    topic_name = next(
        (str(t["name"]) for t in topics_data if t.get("id") == thread_id),
        f"Topic #{thread_id}",
    )

    await _pipeline_finalize_tg(
        msg, state, user, db, redis, http_client,
        topic_name=topic_name, thread_id=thread_id,
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Inline VK Connect (2 states: token -> group)
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_connection,
    F.data == "pipeline:social:connect:vk",
)
async def pipeline_start_connect_vk(
    callback: CallbackQuery,
    state: FSMContext,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Start VK connection — show type selector (group / personal)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await callback.answer(S.PIPELINE_SESSION_EXPIRED, show_alert=True)
        return

    # Check existing VK connections
    conn_svc = ConnectionService(db, http_client)
    existing_vk = await conn_svc.get_by_project_and_platform(project_id, "vk")
    has_group = any(
        (getattr(c, "credentials", None) or {}).get("target") != "personal"
        for c in existing_vk
    )
    has_personal = any(
        (getattr(c, "credentials", None) or {}).get("target") == "personal"
        for c in existing_vk
    )

    if has_group and has_personal:
        await callback.answer(S.VK_BOTH_CONNECTED, show_alert=True)
        return

    await state.set_state(SocialPipelineFSM.connect_vk_type)
    from bot.texts.connections import VK_TYPE_SELECT

    await safe_edit_text(
        msg,
        VK_TYPE_SELECT,
        reply_markup=_pipeline_vk_type_kb(exclude_group=has_group, exclude_personal=has_personal),
    )
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.connect_vk_type,
    F.data.regexp(r"^pipeline:social:vk:(group|personal)$"),
)
async def pipeline_vk_type_selected(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Handle VK type selection in pipeline."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return
    vk_type = callback.data.split(":")[-1]
    await state.update_data(vk_type=vk_type)

    if vk_type == "group":
        await state.set_state(SocialPipelineFSM.connect_vk_group_url)
        text = (
            Screen(E.LINK, S.POST_CONNECTION_VK_TITLE.format(total=_TOTAL_STEPS))
            .blank()
            .line(S.POST_CONNECTION_VK_PROMPT)
            .build()
        )
        await safe_edit_text(msg, text, reply_markup=cancel_kb("pipeline:social:cancel"))
    else:
        # Personal page: show OAuth link + token input
        from bot.texts.connections import _VK_AUTH_URL, VK_PERSONAL_AUTH

        await state.set_state(SocialPipelineFSM.connect_vk_personal_token)
        await safe_edit_text(
            msg,
            VK_PERSONAL_AUTH,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Авторизоваться", url=_VK_AUTH_URL)],
                    [InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")],
                ]
            ),
        )
    await callback.answer()


@router.message(SocialPipelineFSM.connect_vk_group_url, F.text)
async def pipeline_connect_vk_group_url(
    message: Message,
    state: FSMContext,
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """VK inline: parse group URL → resolve → Kate OAuth (blank.html) for token."""
    text = (message.text or "").strip()

    group_id, screen_name = parse_vk_group_input(text)
    if group_id is None and screen_name is None:
        await message.answer(
            S.POST_CONNECTION_VK_PARSE_ERROR,
            reply_markup=cancel_kb("pipeline:social:cancel"),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await message.answer(S.PIPELINE_SESSION_EXPIRED, reply_markup=menu_kb())
        return

    from bot.config import get_settings

    settings = get_settings()

    # Only resolve_group() is used (scraping + vk_service_key fallback).
    # OAuth params are placeholders — Kate OAuth is client-side (blank.html).
    vk_svc = VKOAuthService(
        http_client=http_client,
        redis=redis,
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=0,
        vk_app_secret="",
        redirect_uri="",
        vk_service_key=settings.vk_service_key.get_secret_value(),
    )

    # Resolve group
    resolve_input = str(group_id) if group_id else screen_name
    try:
        resolved_id, group_name = await vk_svc.resolve_group(resolve_input or "")
    except VKOAuthError as exc:
        await message.answer(
            exc.user_message,
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    safe_name = html.escape(group_name or f"Группа {resolved_id}")

    # Same flow as toolbox: Kate OAuth + user pastes blank.html URL
    from bot.texts.connections import _VK_AUTH_URL, VK_STEP2_AUTH

    await state.set_state(SocialPipelineFSM.connect_vk_oauth)
    await state.update_data(
        vk_group_id=resolved_id,
        vk_group_name=group_name or f"Группа {resolved_id}",
    )
    await message.answer(
        VK_STEP2_AUTH.format(group_name=safe_name),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Авторизоваться", url=_VK_AUTH_URL)],
                [InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ---------------------------------------------------------------------------
# VK Group: user pastes blank.html URL with community token (Kate OAuth flow)
# ---------------------------------------------------------------------------


@router.message(SocialPipelineFSM.connect_vk_oauth, F.text)
async def pipeline_connect_vk_group_token(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """VK group: parse blank.html URL with community token, validate, create connection."""
    text = (message.text or "").strip()

    token = _extract_vk_token(text)
    if not token:
        await message.answer(
            "Не удалось извлечь токен.\n\n"
            "Скопируйте <b>всю ссылку</b> из адресной строки\n"
            "после нажатия \u00abРазрешить\u00bb.\n\n"
            "<i>Она начинается с:\n"
            "https://oauth.vk.com/blank.html#access_token=...</i>",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    # Delete message with token for security
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("pipeline.failed_to_delete_vk_token", reason=str(exc))

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await message.answer(S.PIPELINE_SESSION_EXPIRED, reply_markup=menu_kb())
        return

    group_id = data.get("vk_group_id")
    group_name = data.get("vk_group_name", f"Группа {group_id}")

    # Validate token via wall.get (check wall access)
    try:
        resp = await http_client.post(
            "https://api.vk.ru/method/groups.getById",
            data={"access_token": token, "group_id": str(group_id), "v": "5.199"},
            timeout=10,
        )
        result = resp.json()
        if "error" in result:
            err = html.escape(result["error"].get("error_msg", ""))
            await message.answer(
                f"Ошибка проверки токена: {err}\n\n"
                "Попробуйте авторизоваться заново.",
                reply_markup=cancel_kb("pipeline:social:cancel"),
            )
            return
    except httpx.HTTPError:
        await message.answer(
            "Не удалось связаться с VK.\nПопробуйте позже.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    conn_svc = ConnectionService(db, http_client)
    identifier = f"club{group_id}"

    # Check duplicate before DB constraint error
    existing = await conn_svc.get_by_project_and_platform(project_id, "vk")
    if any(getattr(c, "identifier", None) == identifier for c in existing):
        await message.answer(
            f"VK-группа {html.escape(group_name)} уже подключена к этому проекту.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="vk",
            identifier=identifier,
            metadata={"group_name": group_name},
        ),
        raw_credentials={
            "access_token": token,
            "group_id": str(group_id),
        },
    )

    log.info(
        "pipeline.social.vk_group_connected",
        connection_id=conn.id,
        group_id=group_id,
        user_id=user.id,
    )

    await state.update_data(
        connection_id=conn.id, platform_type="vk",
        connection_identifier=identifier,
    )

    project_name = data.get("project_name", "")
    safe_name = html.escape(group_name)
    await message.answer(f"\u2705 VK-группа подключена: {safe_name}")

    from routers.publishing.pipeline.social.social import _show_category_step_msg

    await _show_category_step_msg(
        message,
        state,
        user,
        db,
        redis,
        project_id,
        project_name,
    )


# ---------------------------------------------------------------------------
# VK Personal Page inline token handler
# ---------------------------------------------------------------------------


def _extract_vk_token(text: str) -> str | None:
    """Extract access_token from VK OAuth redirect URL or raw token string."""
    import re

    match = re.search(r"access_token=([a-zA-Z0-9._-]+)", text)
    if match:
        return match.group(1)
    cleaned = text.strip()
    if len(cleaned) >= 20 and re.fullmatch(r"[a-zA-Z0-9._-]+", cleaned):
        return cleaned
    return None


@router.message(SocialPipelineFSM.connect_vk_personal_token, F.text)
async def pipeline_connect_vk_personal_token(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """VK personal page: parse OAuth token URL, validate via users.get, create connection."""
    text = (message.text or "").strip()

    token = _extract_vk_token(text)
    if not token:
        await message.answer(
            "Не удалось извлечь токен.\n\n"
            "Скопируйте <b>всю ссылку</b> из адресной строки\n"
            "после нажатия \u00abРазрешить\u00bb.\n\n"
            "<i>Она начинается с:\n"
            "https://oauth.vk.com/blank.html#access_token=...</i>",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    # Delete message with token for security
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("pipeline.failed_to_delete_vk_token", reason=str(exc))

    data = await state.get_data()
    project_id = data.get("project_id")
    project_name = data.get("project_name", "")
    if not project_id:
        await message.answer(S.PIPELINE_SESSION_EXPIRED, reply_markup=menu_kb())
        return

    # Validate via users.get
    try:
        resp = await http_client.post(
            "https://api.vk.ru/method/users.get",
            data={"access_token": token, "v": "5.199"},
            timeout=10,
        )
        result = resp.json()
        if "error" in result:
            err = html.escape(result["error"].get("error_msg", ""))
            await message.answer(
                f"Ошибка проверки токена: {err}\n\n"
                "Попробуйте авторизоваться заново.",
                reply_markup=cancel_kb("pipeline:social:cancel"),
            )
            return
        vk_user = result["response"][0]
        user_vk_id = str(vk_user["id"])
        user_name = f"{vk_user.get('first_name', '')} {vk_user.get('last_name', '')}".strip()
    except httpx.HTTPError:
        await message.answer(
            "Не удалось связаться с VK.\nПопробуйте позже.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    conn_svc = ConnectionService(db, http_client)
    identifier = f"id{user_vk_id}"

    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="vk",
            identifier=identifier,
            metadata={"group_name": user_name},
        ),
        raw_credentials={
            "access_token": token,
            "target": "personal",
            "user_vk_id": user_vk_id,
            "expires_at": "",
        },
    )

    log.info(
        "pipeline.social.vk_personal_connected",
        connection_id=conn.id,
        user_vk_id=user_vk_id,
        user_id=user.id,
    )

    await state.update_data(
        connection_id=conn.id, platform_type="vk",
        connection_identifier=identifier,
    )

    safe_user = html.escape(user_name)
    await message.answer(
        f"\u2705 {S.VK_PERSONAL_CONNECTED}\n{safe_user} ({identifier})",
    )

    from routers.publishing.pipeline.social.social import _show_category_step_msg

    await _show_category_step_msg(
        message,
        state,
        user,
        db=db,
        redis=redis,
        project_id=project_id,
        project_name=project_name,
    )


# ---------------------------------------------------------------------------
# Pinterest OAuth entry (1 state) + board stub (1 state)
# ---------------------------------------------------------------------------


@router.callback_query(
    SocialPipelineFSM.select_connection,
    F.data == "pipeline:social:connect:pinterest",
)
async def pipeline_start_connect_pinterest(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    redis: RedisClient,
) -> None:
    """Start Pinterest OAuth — generate nonce, show URL button."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await callback.answer(S.PIPELINE_SESSION_EXPIRED, show_alert=True)
        return

    nonce = secrets.token_urlsafe(16)
    nonce_data = {
        "project_id": project_id,
        "user_id": user.id,
        "from_pipeline": True,
    }
    import json

    await redis.set(
        CacheKeys.pinterest_oauth(nonce),
        json.dumps(nonce_data),
        ex=PINTEREST_AUTH_TTL,
    )

    from bot.config import get_settings

    settings = get_settings()
    base_url = settings.railway_public_url.rstrip("/")
    oauth_url = f"{base_url}/api/auth/pinterest?user_id={user.id}&nonce={nonce}"

    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Авторизоваться в Pinterest", url=oauth_url)],
            [InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")],
        ]
    )

    await state.set_state(SocialPipelineFSM.connect_pinterest_oauth)
    text = (
        Screen(E.LINK, S.POST_CONNECTION_PINTEREST_TITLE.format(total=_TOTAL_STEPS))
        .blank()
        .line(S.POST_CONNECTION_PINTEREST_HINT.format(minutes=PINTEREST_AUTH_TTL // 60))
        .build()
    )
    await safe_edit_text(msg, text, reply_markup=kb)
    await callback.answer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_tg_channel(raw: str) -> str:
    """Normalize TG channel input to @channel format."""
    text = raw.strip()
    if text.startswith("-100"):
        return text  # Numeric ID — keep as-is
    # Extract channel name from t.me/channel or https://t.me/channel
    if "t.me/" in text:
        parts = text.split("t.me/")
        channel_name = parts[-1].strip("/")
        return f"@{channel_name}"
    if text.startswith("@"):
        return text
    return f"@{text}"


def _tg_verify_kb() -> InlineKeyboardMarkup:
    """Keyboard for TG verify step."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Проверить", callback_data="pipeline:social:tg_verify")],
            [InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")],
        ]
    )


def _tg_verify_retry_kb() -> InlineKeyboardMarkup:
    """Keyboard for TG verify retry."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Проверить снова", callback_data="pipeline:social:tg_verify")],
            [InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")],
        ]
    )


def _pipeline_vk_type_kb(
    *,
    exclude_group: bool = False,
    exclude_personal: bool = False,
) -> InlineKeyboardMarkup:
    """Build VK type selector keyboard for pipeline."""
    rows: list[list[InlineKeyboardButton]] = []
    if not exclude_group:
        rows.append([InlineKeyboardButton(text="Группа", callback_data="pipeline:social:vk:group")])
    if not exclude_personal:
        rows.append([InlineKeyboardButton(
            text="Личная страница",
            callback_data="pipeline:social:vk:personal",
        )])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
