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
"""

from __future__ import annotations

import html
import secrets

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.helpers import safe_edit_text, safe_message
from bot.validators import TG_CHANNEL_RE
from cache.client import RedisClient
from cache.keys import PINTEREST_AUTH_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from keyboards.inline import cancel_kb, menu_kb
from keyboards.pipeline import (
    social_connections_kb,
    social_no_connections_kb,
)
from routers.publishing.pipeline._common import (
    SocialPipelineFSM,
    save_checkpoint,
)
from services.connections import ConnectionService

log = structlog.get_logger()
router = Router()

_TOTAL_STEPS = 5


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
) -> None:
    """Show connection selection (step 2).

    UX_PIPELINE.md section 5.2:
    - 0 connections -> show platform picker
    - 1 connection -> auto-select, skip to step 3
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
        await safe_edit_text(
            msg,
            f"Пост (2/{_TOTAL_STEPS}) — Подключение\n\nПодключите соцсеть для публикации.",
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

    await safe_edit_text(
        msg,
        f"Пост (2/{_TOTAL_STEPS}) — Подключение\n\nКуда публикуем?",
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
        await message.answer(
            f"Пост (2/{_TOTAL_STEPS}) — Подключение\n\nПодключите соцсеть для публикации.",
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

    await message.answer(
        f"Пост (2/{_TOTAL_STEPS}) — Подключение\n\nКуда публикуем?",
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
        await callback.answer("Проект не совпадает.", show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if conn is None or conn.project_id != project_id:
        await callback.answer("Подключение не найдено.", show_alert=True)
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
        await callback.answer("Проект не выбран.", show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    connected_types = set(await conn_svc.get_platform_types_by_project(project_id))
    social_types = {"telegram", "vk", "pinterest"}
    already_connected = connected_types & social_types

    if already_connected == social_types:
        await callback.answer("Все платформы уже подключены.", show_alert=True)
        return

    await safe_edit_text(msg, 
        f"Пост (2/{_TOTAL_STEPS}) — Подключение\n\nВыберите платформу:",
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
    await safe_edit_text(msg, 
        f"Пост (2/{_TOTAL_STEPS}) — Подключение Телеграм\n\n"
        "Введите ID или ссылку на канал.\n"
        "<i>Примеры: @mychannel, t.me/mychannel, -1001234567890</i>",
        reply_markup=cancel_kb("pipeline:social:cancel"),
    )
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
            "Неверный формат. Используйте @channel, t.me/channel или -100XXXXX.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    # Normalize to @channel format
    normalized = _normalize_tg_channel(text)

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await message.answer("Проект не выбран. Начните заново.", reply_markup=menu_kb())
        return

    conn_svc = ConnectionService(db, http_client)

    # Check 1 TG per project limit
    existing = await conn_svc.get_by_project_and_platform(project_id, "telegram")
    if existing:
        await message.answer(
            "У этого проекта уже есть Телеграм-канал. Удалите текущий, чтобы подключить другой.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    # E41: global uniqueness
    global_dup = await conn_svc.get_by_identifier_global(normalized, "telegram")
    if global_dup:
        await message.answer(
            f"Канал {html.escape(normalized)} уже подключён другим пользователем.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    await state.update_data(tg_channel=normalized)
    await state.set_state(SocialPipelineFSM.connect_tg_token)
    await message.answer(
        f"Канал: {html.escape(normalized)}\n\n"
        "Теперь создайте бота через @BotFather и пришлите токен.\n"
        "<i>Формат: 123456789:AAABBB...</i>",
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
            "Неверный формат токена. Токен содержит «:» и длиннее 30 символов.\nПришлите корректный токен.",
            reply_markup=cancel_kb("pipeline:social:cancel"),
        )
        return

    data = await state.get_data()
    channel = data.get("tg_channel", "")

    await state.update_data(tg_token=text)
    await state.set_state(SocialPipelineFSM.connect_tg_verify)
    await message.answer(
        f"Токен принят.\n\n"
        f"Теперь добавьте бота админом в канал {html.escape(channel)} "
        "с правом «Публикация сообщений» и нажмите «Проверить».",
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
    project_name = data.get("project_name", "")

    if not token or not channel or not project_id:
        await callback.answer("Данные сессии устарели.", show_alert=True)
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
                "Не удалось получить список админов канала.\nПроверьте, что бот добавлен в канал.",
                reply_markup=_tg_verify_retry_kb(),
            )
            await callback.answer()
            return

        is_admin = any(admin.user.id == bot_info.id and getattr(admin, "can_post_messages", False) for admin in admins)

        if not is_admin:
            await safe_edit_text(msg, 
                "Бот не является администратором канала "
                "или не имеет права «Публикация сообщений».\n"
                "Добавьте бота и нажмите «Проверить снова».",
                reply_markup=_tg_verify_retry_kb(),
            )
            await callback.answer()
            return

    except Exception as exc:
        log.warning("pipeline.tg_bot_validation_failed", error=str(exc))
        await safe_edit_text(msg, 
            "Не удалось подключиться к боту. Проверьте токен.",
            reply_markup=_tg_verify_retry_kb(),
        )
        await callback.answer()
        return
    finally:
        if temp_bot:
            await temp_bot.session.close()

    # Create connection
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="telegram",
            identifier=channel,
            metadata={"bot_username": bot_info.username or ""},
        ),
        raw_credentials={"bot_token": token, "channel_id": channel},
    )

    log.info(
        "pipeline.social.tg_connected",
        connection_id=conn.id,
        channel=channel,
        user_id=user.id,
    )

    await state.update_data(
        connection_id=conn.id, platform_type="telegram",
        connection_identifier=channel,
    )
    await safe_edit_text(msg, 
        f"Телеграм-канал {html.escape(channel)} подключён!",
    )

    from routers.publishing.pipeline.social.social import _show_category_step_msg

    # Use message context (we just edited, next screen sends new message)
    await _show_category_step_msg(
        msg,
        state,
        user,
        db=db,
        redis=redis,
        project_id=project_id,
        project_name=project_name,
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
    user: User,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Start VK OAuth connection — delegates nonce/meta/URL to VKOAuthService."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    if not project_id:
        await callback.answer("Проект не выбран.", show_alert=True)
        return

    from bot.config import get_settings
    from services.oauth.vk import VKOAuthService

    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    if not base_url:
        log.error("vk_oauth_base_url_missing")
        await safe_edit_text(msg, "Ошибка конфигурации сервера. Попробуйте позже.")
        return

    vk_svc = VKOAuthService(
        http_client=http_client,
        redis=redis,
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=settings.vk_app_id,
        redirect_uri=f"{base_url}/api/auth/vk/callback",
    )
    nonce = vk_svc.generate_nonce()
    await vk_svc.store_meta(nonce, project_id, extra={"user_id": user.id, "from_pipeline": True})
    oauth_url = vk_svc.build_oauth_url(user.id, nonce)

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Авторизоваться в VK", url=oauth_url)],
            [InlineKeyboardButton(text="Отмена", callback_data="pipeline:social:cancel")],
        ]
    )

    await state.set_state(SocialPipelineFSM.connect_vk_oauth)
    await safe_edit_text(
        msg,
        f"Пост (2/{_TOTAL_STEPS}) — Подключение ВКонтакте\n\n"
        "Нажмите кнопку ниже для авторизации через VK ID.\n"
        "Ссылка действительна 30 минут.",
        reply_markup=kb,
    )
    await callback.answer()

    # NOTE: After OAuth, user returns via deep-link /start vk_auth_{nonce},
    # which is handled in routers/start.py. The pipeline flow continues
    # after the connection is created via the deep-link handler.


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
        await callback.answer("Проект не выбран.", show_alert=True)
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
    await safe_edit_text(msg, 
        f"Пост (2/{_TOTAL_STEPS}) — Подключение Pinterest\n\n"
        "Нажмите кнопку ниже для авторизации.\n"
        f"Ссылка действительна {PINTEREST_AUTH_TTL // 60} минут.",
        reply_markup=kb,
    )
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
