"""WordPress connection wizard (ConnectWordPressFSM)."""

import asyncio
import html
import time

import httpx
import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.connections import WP_STEP1_URL, WP_STEP2_LOGIN, WP_STEP3_CREDENTIALS
from bot.texts.emoji import E
from bot.texts.screens import Screen
from bot.validators import URL_RE
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from keyboards.inline import cancel_kb, connection_list_kb, menu_kb
from routers.platforms._shared import _background_tasks, _cancel_connection_wizard, _run_site_analysis
from services.connections import ConnectionService
from services.external.firecrawl import FirecrawlClient
from services.external.pagespeed import PageSpeedClient

log = structlog.get_logger()
router = Router()


class ConnectWordPressFSM(StatesGroup):
    url = State()
    login = State()
    password = State()


@router.callback_query(F.data.regexp(r"^conn:\d+:add:wordpress$"))
async def start_wp_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Start WordPress connection wizard."""
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

    # Rule: 1 project = max 1 WordPress connection
    conn_svc = ConnectionService(db, http_client)
    existing_wp = await conn_svc.get_by_project_and_platform(project_id, "wordpress")
    if existing_wp:
        await callback.answer(
            S.CONNECTIONS_WP_ALREADY,
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(S.FSM_INTERRUPTED.format(name=interrupted))

    await state.set_state(ConnectWordPressFSM.url)
    await state.update_data(last_update_time=time.time(), connect_project_id=project_id)

    await msg.answer(
        WP_STEP1_URL,
        reply_markup=cancel_kb(f"conn:{project_id}:wp_cancel"),
    )
    await callback.answer()


@router.message(ConnectWordPressFSM.url, F.text)
async def wp_process_url(message: Message, state: FSMContext) -> None:
    """WP step 1: site URL."""
    text = (message.text or "").strip()
    if text == "\u041e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    if not URL_RE.match(text):
        await message.answer(S.VALIDATION_URL_INVALID)
        return

    url = text if text.startswith("http") else f"https://{text}"
    data = await state.update_data(wp_url=url)
    pid = data.get("connect_project_id", 0)
    await state.set_state(ConnectWordPressFSM.login)
    await message.answer(
        WP_STEP2_LOGIN,
        reply_markup=cancel_kb(f"conn:{pid}:wp_cancel"),
    )


@router.message(ConnectWordPressFSM.login, F.text)
async def wp_process_login(message: Message, state: FSMContext) -> None:
    """WP step 2: login."""
    text = (message.text or "").strip()
    if text == "\u041e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    if len(text) < 1 or len(text) > 100:
        await message.answer(S.VALIDATION_LOGIN_LENGTH)
        return

    data = await state.update_data(wp_login=text)
    pid = data.get("connect_project_id", 0)
    await state.set_state(ConnectWordPressFSM.password)
    await message.answer(
        WP_STEP3_CREDENTIALS,
        reply_markup=cancel_kb(f"conn:{pid}:wp_cancel"),
    )


@router.message(ConnectWordPressFSM.password, F.text)
async def wp_process_password(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
    firecrawl_client: FirecrawlClient,
    pagespeed_client: PageSpeedClient,
) -> None:
    """WP step 3: Application Password -- validate and create connection."""
    text = (message.text or "").strip()

    if text == "\u041e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    # Delete message with password for security (after cancel check)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("failed_to_delete_password_message", reason=str(exc))

    if len(text) < 10:
        await message.answer(S.VALIDATION_PASSWORD_SHORT)
        return

    data = await state.get_data()
    wp_url = data["wp_url"]
    wp_login = data["wp_login"]
    project_id = int(data["connect_project_id"])

    conn_svc = ConnectionService(db, http_client)

    # Validate WP REST API via service
    error = await conn_svc.validate_wordpress(wp_url, wp_login, text)
    if error:
        await message.answer(error)
        return

    # Extract domain as identifier
    identifier = wp_url.replace("https://", "").replace("http://", "").rstrip("/")

    # Rule: 1 project = max 1 WordPress connection
    existing_wp = await conn_svc.get_by_project_and_platform(project_id, "wordpress")
    if existing_wp:
        await message.answer(S.CONN_WP_ALREADY_SHORT)
        return

    # Re-validate ownership before creating connection (I7)
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await state.clear()
        await message.answer(S.PROJECT_NOT_FOUND, reply_markup=menu_kb())
        return

    await state.clear()

    # Create connection
    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="wordpress",
            identifier=identifier,
        ),
        raw_credentials={"url": wp_url, "login": wp_login, "app_password": text},
    )

    log.info("wordpress_connected", conn_id=conn.id, project_id=project_id, identifier=identifier)

    # Fire-and-forget site analysis (PRD 7.1: branding + map + PSI)
    _enc_key = get_settings().encryption_key.get_secret_value()
    task = asyncio.create_task(
        _run_site_analysis(db, firecrawl_client, pagespeed_client, project_id, wp_url, conn.id, _enc_key),
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Reload list (project already validated above)
    connections = await conn_svc.get_by_project(project_id)
    conn_text = (
        Screen(E.CHECK, S.CONN_CONNECTED_TITLE)
        .blank()
        .line(S.CONN_WP_SUCCESS.format(identifier=html.escape(identifier)))
        .hint(S.CONN_WP_HINT)
        .build()
    )
    await message.answer(
        conn_text,
        reply_markup=connection_list_kb(connections, project_id),
    )


# ---------------------------------------------------------------------------
# Cancel handler
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:\d+:wp_cancel$"))
async def cancel_wp_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Cancel WordPress connection via inline button."""
    await _cancel_connection_wizard(callback, state, user, db, http_client, project_service_factory)
