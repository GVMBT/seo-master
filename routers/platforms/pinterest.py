"""Pinterest connection wizard (ConnectPinterestFSM)."""

import secrets
import time

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
)

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.emoji import E
from cache.client import RedisClient
from cache.keys import PINTEREST_AUTH_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import User
from services.connections import ConnectionService

log = structlog.get_logger()
router = Router()


class ConnectPinterestFSM(StatesGroup):
    oauth_callback = State()
    select_board = State()  # Board selection deferred -- uses _get_default_board() fallback


@router.callback_query(F.data.regexp(r"^conn:\d+:add:pinterest$"))
async def start_pinterest_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
    redis: RedisClient,
) -> None:
    """Start Pinterest OAuth connection wizard."""
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

    # Rule: 1 project = max 1 Pinterest connection
    conn_svc = ConnectionService(db, http_client)
    existing_pinterest = await conn_svc.get_by_project_and_platform(project_id, "pinterest")
    if existing_pinterest:
        await callback.answer(
            S.CONNECTIONS_PINTEREST_ALREADY,
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(S.FSM_INTERRUPTED.format(name=interrupted))

    # Generate nonce for OAuth
    nonce = secrets.token_urlsafe(16)
    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    if not base_url:
        await msg.answer(S.ERROR_SERVER_CONFIG)
        return
    oauth_url = f"{base_url}/api/auth/pinterest?user_id={user.id}&nonce={nonce}"

    # Store nonce -> project_id mapping in Redis (30 min TTL, matches pinterest_auth TTL)
    await redis.set(CacheKeys.pinterest_oauth(nonce), str(project_id), ex=PINTEREST_AUTH_TTL)

    await state.set_state(ConnectPinterestFSM.oauth_callback)
    await state.update_data(
        last_update_time=time.time(),
        connect_project_id=project_id,
        pinterest_nonce=nonce,
    )

    await msg.answer(
        f"{E.PINTEREST} <b>Подключение Pinterest</b>\n\n"
        "Нажмите кнопку ниже, чтобы авторизоваться\n"
        "в Pinterest и предоставить доступ.\n\n"
        f"{E.LOCK} Токен хранится в зашифрованном виде",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Авторизоваться в Pinterest", url=oauth_url)],
                [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:list")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()
