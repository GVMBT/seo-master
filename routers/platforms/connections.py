"""Connection list, manage, delete + 4 connection wizard FSMs."""

import asyncio
import html
import secrets
import time
from collections.abc import Sequence

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    Message,
)

from bot.assets import edit_screen
from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts.connections import (
    TG_STEP1_CHANNEL,
    TG_STEP2_BOT_SETUP,
    VK_STEP1_GROUP_URL,
    VK_STEP2_OAUTH,
    WP_STEP1_URL,
    WP_STEP2_LOGIN,
    WP_STEP3_CREDENTIALS,
)
from bot.texts.emoji import E
from bot.validators import TG_CHANNEL_RE, URL_RE
from cache.client import RedisClient
from cache.keys import PINTEREST_AUTH_TTL, CacheKeys
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from db.repositories.publications import PublicationsRepository
from keyboards.inline import (
    cancel_kb,
    connection_delete_confirm_kb,
    connection_list_kb,
    connection_manage_kb,
    menu_kb,
)
from services.analysis import SiteAnalysisService
from services.connections import ConnectionService
from services.external.firecrawl import FirecrawlClient
from services.external.pagespeed import PageSpeedClient
from services.oauth.vk import VKOAuthError, VKOAuthService, parse_vk_group_input
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()

# Strong reference set for fire-and-forget background tasks (prevents GC mid-execution)
_background_tasks: set[asyncio.Task[None]] = set()

# Platform icon map (E.* for message text only)
_PLAT_EMOJI: dict[str, str] = {
    "wordpress": E.WORDPRESS,
    "telegram": E.TELEGRAM,
    "vk": E.VK,
    "pinterest": E.PINTEREST,
}

# Platform display names
_PLAT_LABEL: dict[str, str] = {
    "wordpress": "Сайты",
    "telegram": "Telegram",
    "vk": "ВКонтакте",
    "pinterest": "Pinterest",
}


def _build_connections_text(
    project_name: str,
    connections: Sequence[object],
) -> str:
    """Build unified connections screen text grouped by platform."""
    safe_name = html.escape(project_name)

    if not connections:
        return (
            f"{E.GEAR} <b>МОИ ПОДКЛЮЧЕНИЯ</b>\n\n"
            f"Проект: {safe_name}\n\n"
            "Подключений пока нет.\n"
            "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
            f"{E.LIGHTBULB} <i>Подключите площадки для автопостинга контента</i>"
        )

    # Group connections by platform_type
    grouped: dict[str, list[str]] = {}
    for conn in connections:
        pt = getattr(conn, "platform_type", "unknown")
        identifier = html.escape(getattr(conn, "identifier", ""))
        grouped.setdefault(pt, []).append(identifier)

    lines: list[str] = [
        f"{E.GEAR} <b>МОИ ПОДКЛЮЧЕНИЯ</b>\n",
        f"Проект: {safe_name}\n",
    ]

    platform_order = ["wordpress", "telegram", "vk", "pinterest"]
    for pt in platform_order:
        items = grouped.pop(pt, None)
        if not items:
            continue
        icon = _PLAT_EMOJI.get(pt, "")
        label = _PLAT_LABEL.get(pt, pt.capitalize())
        lines.append(f"{icon} {label} ({len(items)}):")
        for i, ident in enumerate(items, 1):
            lines.append(f"  {i}. {ident}")
        lines.append("")

    # Remaining unknown platforms (if any)
    for pt, items in grouped.items():
        lines.append(f"{pt.capitalize()} ({len(items)}):")
        for i, ident in enumerate(items, 1):
            lines.append(f"  {i}. {ident}")
        lines.append("")

    lines.append("\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append(f"{E.LIGHTBULB} <i>Подключите площадки для автопостинга контента</i>")
    return "\n".join(lines)

async def _run_site_analysis(
    db: SupabaseClient,
    firecrawl: FirecrawlClient,
    pagespeed: PageSpeedClient,
    project_id: int,
    site_url: str,
    connection_id: int,
    encryption_key: str,
) -> None:
    """Fire-and-forget site analysis wrapper (PRD §7.1).

    Catches all exceptions so a background task crash doesn't propagate.
    """
    try:
        svc = SiteAnalysisService(db, firecrawl, pagespeed, encryption_key=encryption_key)
        report = await svc.run_full_analysis(project_id, site_url, connection_id)
        if report.errors:
            log.warning("site_analysis.partial", project_id=project_id, errors=report.errors)
        else:
            log.info("site_analysis.complete", project_id=project_id)
    except Exception:
        log.exception("site_analysis.failed", project_id=project_id)


# ---------------------------------------------------------------------------
# FSM definitions (FSM_SPEC.md section 1)
# ---------------------------------------------------------------------------


class ConnectWordPressFSM(StatesGroup):
    url = State()
    login = State()
    password = State()


class ConnectTelegramFSM(StatesGroup):
    channel = State()
    token = State()


class ConnectVKFSM(StatesGroup):
    enter_group_url = State()  # User enters VK group URL/ID
    oauth_callback = State()
    select_group = State()  # Handled by deep-link callback in routers/start.py


class ConnectPinterestFSM(StatesGroup):
    oauth_callback = State()
    select_board = State()  # Board selection deferred — uses _get_default_board() fallback


# ---------------------------------------------------------------------------
# Connection list
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:\d+:connections$"))
async def show_connections(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show connection list for a project (UX_TOOLBOX.md section 5.1)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await project_service_factory(db).get_owned_project(project_id, user.id)

    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    connections = await conn_svc.get_by_project(project_id)

    text = _build_connections_text(project.name, connections)

    await edit_screen(
        msg,
        "empty_connections.png",
        text,
        reply_markup=connection_list_kb(connections, project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^conn:\d+:list$"))
async def connections_list_back(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Back navigation to connection list."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await project_service_factory(db).get_owned_project(project_id, user.id)

    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    connections = await conn_svc.get_by_project(project_id)

    text = _build_connections_text(project.name, connections)

    await edit_screen(
        msg,
        "empty_connections.png",
        text,
        reply_markup=connection_list_kb(connections, project_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Connection manage + delete
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:\d+:manage$"))
async def manage_connection(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show connection detail (UX_TOOLBOX.md section 5.2)."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project = await project_service_factory(db).get_owned_project(conn.project_id, user.id)
    if not project:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    icon = _PLAT_EMOJI.get(conn.platform_type, "")
    plat_label = _PLAT_LABEL.get(conn.platform_type, conn.platform_type.capitalize())
    status_icon = E.CHECK if conn.status == "active" else E.WARNING
    status_text = "Активно" if conn.status == "active" else "Ошибка"
    safe_id = html.escape(conn.identifier)
    created_str = conn.created_at.strftime("%d.%m.%Y") if conn.created_at else "---"

    pub_repo = PublicationsRepository(db)
    pub_count = await pub_repo.get_count_by_connection(conn_id)

    text = (
        f"{icon} <b>ПОДКЛЮЧЕНИЕ</b>\n\n"
        f"Платформа: {plat_label}\n"
        f"Идентификатор: {safe_id}\n\n"
        f"Статус: {status_icon} {status_text}\n"
        f"Подключено: {created_str}\n"
        f"{E.ANALYTICS} Публикаций: {pub_count}\n\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"{E.LIGHTBULB} <i>Управляйте подключением</i>"
    )
    await safe_edit_text(
        msg,
        text,
        reply_markup=connection_manage_kb(conn_id, conn.project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^conn:\d+:delete$"))
async def confirm_connection_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Show connection delete confirmation."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project = await project_service_factory(db).get_owned_project(conn.project_id, user.id)
    if not project:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    safe_id = html.escape(conn.identifier)
    icon = _PLAT_EMOJI.get(conn.platform_type, "")
    await safe_edit_text(
        msg,
        f"{E.WARNING} <b>УДАЛЕНИЕ ПОДКЛЮЧЕНИЯ</b>\n\n"
        f"{icon} {conn.platform_type.capitalize()} ({safe_id})\n\n"
        "Будут удалены:\n"
        "\u2022 Связанные расписания\n"
        "\u2022 Настройки кросс-постинга\n"
        "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n"
        f"{E.LIGHTBULB} <i>Это действие нельзя отменить</i>",
        reply_markup=connection_delete_confirm_kb(conn_id, conn.project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^conn:\d+:delete:confirm$"))
async def execute_connection_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
    scheduler_service: SchedulerService,
) -> None:
    """Delete connection with E24 cleanup: cancel QStash schedules."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project = await project_service_factory(db).get_owned_project(conn.project_id, user.id)
    if not project:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project_id = conn.project_id

    # E24: Cancel QStash schedules for this connection
    await scheduler_service.cancel_schedules_for_connection(conn_id)

    # Clean up cross_post_connection_ids references
    await conn_svc.cleanup_cross_post_refs(conn_id)

    deleted = await conn_svc.delete(conn_id)
    if deleted:
        safe_id = html.escape(conn.identifier)
        # Reload connection list
        connections = await conn_svc.get_by_project(project_id)
        text = _build_connections_text(project.name, connections)
        await safe_edit_text(msg,
            f"{E.CHECK} Подключение {conn.platform_type.capitalize()} ({safe_id}) удалено.\n\n{text}",
            reply_markup=connection_list_kb(connections, project_id),
        )
        log.info("connection_deleted", conn_id=conn_id, user_id=user.id)
    else:
        await safe_edit_text(msg, f"{E.WARNING} Ошибка удаления подключения.", reply_markup=menu_kb())

    await callback.answer()


# ---------------------------------------------------------------------------
# ConnectWordPressFSM (3 states)
# ---------------------------------------------------------------------------


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

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    # Rule: 1 project = max 1 WordPress connection
    conn_svc = ConnectionService(db, http_client)
    existing_wp = await conn_svc.get_by_project_and_platform(project_id, "wordpress")
    if existing_wp:
        await callback.answer(
            "К проекту уже подключён WordPress-сайт. Для другого сайта создайте новый проект.",
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

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
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.", reply_markup=menu_kb())
        return

    if not URL_RE.match(text):
        await message.answer("Некорректный URL. Попробуйте ещё раз.")
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
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.", reply_markup=menu_kb())
        return

    if len(text) < 1 or len(text) > 100:
        await message.answer("Логин: от 1 до 100 символов.")
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
    """WP step 3: Application Password — validate and create connection."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.", reply_markup=menu_kb())
        return

    # Delete message with password for security (after cancel check)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("failed_to_delete_password_message", reason=str(exc))

    if len(text) < 10:
        await message.answer("Application Password слишком короткий. Попробуйте ещё раз.")
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
        await message.answer(
            "К проекту уже подключён WordPress-сайт.\nДля другого сайта создайте новый проект.",
        )
        return

    # Re-validate ownership before creating connection (I7)
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await state.clear()
        await message.answer("Проект не найден.", reply_markup=menu_kb())
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

    # Fire-and-forget site analysis (PRD §7.1: branding + map + PSI)
    _enc_key = get_settings().encryption_key.get_secret_value()
    task = asyncio.create_task(
        _run_site_analysis(db, firecrawl_client, pagespeed_client, project_id, wp_url, conn.id, _enc_key),
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    # Reload list (project already validated above)
    connections = await conn_svc.get_by_project(project_id)
    safe_name = html.escape(project.name)
    await message.answer(
        f"WordPress ({html.escape(identifier)}) подключён!\n\n<b>{safe_name}</b> — Подключения",
        reply_markup=connection_list_kb(connections, project_id),
    )


# ---------------------------------------------------------------------------
# ConnectTelegramFSM (2 states)
# ---------------------------------------------------------------------------


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

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    # Rule: 1 project = max 1 Telegram connection
    conn_svc = ConnectionService(db, http_client)
    existing_tg = await conn_svc.get_by_project_and_platform(project_id, "telegram")
    if existing_tg:
        await callback.answer(
            "К проекту уже подключён Telegram-канал. Для другого канала создайте новый проект.",
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

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
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.", reply_markup=menu_kb())
        return

    if not TG_CHANNEL_RE.match(text):
        await message.answer("Некорректный формат. Введите @channel или t.me/channel.")
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
    """TG step 2: bot token — validate and create connection."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.", reply_markup=menu_kb())
        return

    # Delete message with token for security (after cancel check)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("failed_to_delete_token_message", reason=str(exc))

    # Validate bot token format (roughly: digits:alphanumeric)
    if ":" not in text or len(text) < 30:
        await message.answer("Некорректный формат токена. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    channel_id = data["tg_channel"]
    project_id = int(data["connect_project_id"])

    # Validate via getMe + check admin status (single try/finally for session cleanup)
    temp_bot = Bot(token=text)
    try:
        try:
            bot_info = await temp_bot.get_me()
        except Exception as exc:
            log.warning("tg_connect_invalid_token", error=str(exc))
            await message.answer("Недействительный токен. Проверьте и попробуйте ещё раз.")
            return

        # Check bot is admin of the channel
        try:
            admins = await temp_bot.get_chat_administrators(channel_id)
        except TelegramBadRequest as exc:
            log.warning("tg_connect_channel_error", channel=channel_id, error=str(exc))
            await message.answer(
                f"Не удалось проверить канал {channel_id}.\n"
                "Убедитесь, что канал существует и бот добавлен как администратор."
            )
            return
        except Exception as exc:
            log.warning("tg_connect_admin_check_failed", channel=channel_id, error=str(exc))
            await message.answer(
                f"Не удалось проверить канал {channel_id}.\n"
                "Убедитесь, что канал существует и бот добавлен как администратор."
            )
            return

        bot_is_admin = any(a.user.id == bot_info.id for a in admins)
        if not bot_is_admin:
            await message.answer(
                f"Бот @{bot_info.username} не является администратором канала {channel_id}.\n"
                "Добавьте бота в канал и назначьте администратором."
            )
            return
    finally:
        await temp_bot.session.close()

    conn_svc = ConnectionService(db, http_client)

    # Rule: 1 project = max 1 Telegram connection
    existing_tg = await conn_svc.get_by_project_and_platform(project_id, "telegram")
    if existing_tg:
        await message.answer(
            "К проекту уже подключён Telegram-канал.\nДля другого канала создайте новый проект.",
        )
        return

    # E41: Telegram requires GLOBAL uniqueness — channel must not be connected by ANY user
    existing = await conn_svc.get_by_identifier_global(channel_id, "telegram")
    if existing:
        await message.answer(
            f"Канал {channel_id} уже подключён другим пользователем.\n"
            "Один канал может быть привязан только к одному проекту.",
        )
        log.warning("tg_global_duplicate_blocked", channel=channel_id, existing_conn=existing.id)
        return

    await state.clear()

    conn = await conn_svc.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="telegram",
            identifier=channel_id,
            metadata={"bot_username": bot_info.username or ""},
        ),
        raw_credentials={"bot_token": text, "channel_id": channel_id},
    )

    log.info("telegram_connected", conn_id=conn.id, project_id=project_id, channel=channel_id)

    connections = await conn_svc.get_by_project(project_id)
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    safe_name = html.escape(project.name) if project else ""
    await message.answer(
        f"Telegram-канал {channel_id} подключён!\n\n<b>{safe_name}</b> — Подключения",
        reply_markup=connection_list_kb(connections, project_id),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ---------------------------------------------------------------------------
# ConnectVKFSM (2 states)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:\d+:add:vk$"))
async def start_vk_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
    redis: RedisClient,
) -> None:
    """Start VK connection — ask user for group URL/ID."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    # Rule: 1 project = max 1 VK connection
    conn_svc = ConnectionService(db, http_client)
    existing_vk = await conn_svc.get_by_project_and_platform(project_id, "vk")
    if existing_vk:
        await callback.answer(
            "К проекту уже подключена VK-группа. Для другой группы создайте новый проект.",
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectVKFSM.enter_group_url)
    await state.update_data(
        last_update_time=time.time(),
        connect_project_id=project_id,
    )

    await msg.answer(
        VK_STEP1_GROUP_URL,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:vk_cancel")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()


@router.message(ConnectVKFSM.enter_group_url, F.text)
async def vk_process_group_url(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """VK: parse group URL/ID, resolve name, redirect to OAuth with group_ids."""
    text = (message.text or "").strip()
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.", reply_markup=menu_kb())
        return

    group_id, screen_name = parse_vk_group_input(text)
    if group_id is None and screen_name is None:
        await message.answer(
            "Не удалось распознать группу.\n\n"
            "Примеры:\n"
            "• https://vk.com/club123456\n"
            "• https://vk.com/mygroup\n"
            "• 123456",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return

    data = await state.get_data()
    project_id = int(data["connect_project_id"])

    # Re-validate project ownership
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await state.clear()
        await message.answer("Проект не найден.", reply_markup=menu_kb())
        return

    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    if not base_url:
        await message.answer("Ошибка конфигурации сервера. Попробуйте позже.")
        return

    vk_svc = VKOAuthService(
        http_client=http_client,
        redis=redis,
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=settings.vk_app_id,
        vk_app_secret=settings.vk_secure_key.get_secret_value(),
        redirect_uri=f"{base_url}/api/auth/vk/callback",
        vk_service_key=settings.vk_service_key.get_secret_value(),
    )

    # Resolve group: either by numeric ID or screen_name
    resolve_input = str(group_id) if group_id else screen_name
    try:
        resolved_id, group_name = await vk_svc.resolve_group(resolve_input or "")
    except VKOAuthError as exc:
        await message.answer(exc.user_message)
        return

    # Generate nonce, store auth session for step 2
    nonce = vk_svc.generate_nonce()
    await vk_svc.store_meta(nonce, project_id, extra={"user_id": user.id})
    await vk_svc.store_auth(
        nonce, user.id, step="community", group_id=resolved_id, group_name=group_name,
    )

    # Build OAuth URL with group_ids
    oauth_url = vk_svc.build_oauth_url(user.id, nonce, group_ids=resolved_id)

    await state.set_state(ConnectVKFSM.oauth_callback)
    await state.update_data(vk_nonce=nonce)

    safe_name = html.escape(group_name or f"Группа {resolved_id}")
    await message.answer(
        VK_STEP2_OAUTH.format(group_name=safe_name),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить доступ к группе", url=oauth_url)],
                [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:vk_cancel")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ---------------------------------------------------------------------------
# ConnectPinterestFSM (2 states) — OAuth flow
# ---------------------------------------------------------------------------


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

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    # Rule: 1 project = max 1 Pinterest connection
    conn_svc = ConnectionService(db, http_client)
    existing_pinterest = await conn_svc.get_by_project_and_platform(project_id, "pinterest")
    if existing_pinterest:
        await callback.answer(
            "К проекту уже подключён Pinterest. Для другой доски создайте новый проект.",
            show_alert=True,
        )
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Generate nonce for OAuth
    nonce = secrets.token_urlsafe(16)
    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    if not base_url:
        await msg.answer("Ошибка конфигурации сервера. Попробуйте позже.")
        return
    oauth_url = f"{base_url}/api/auth/pinterest?user_id={user.id}&nonce={nonce}"

    # Store nonce → project_id mapping in Redis (30 min TTL, matches pinterest_auth TTL)
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


# ---------------------------------------------------------------------------
# Cancel handlers (inline button)
# ---------------------------------------------------------------------------


async def _cancel_connection_wizard(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
    redis: RedisClient | None = None,
) -> None:
    """Common cancel logic for connection wizards."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    # Get project_id from callback_data (conn:{pid}:*_cancel) or FSM state
    project_id: int | None = None
    parts = (callback.data or "").split(":")
    if len(parts) >= 2 and parts[1].isdigit():
        project_id = int(parts[1])

    data = await state.get_data()
    if not project_id:
        pid = data.get("connect_project_id")
        project_id = int(pid) if pid else None

    # Clean up VK OAuth Redis keys if cancel during VK flow
    vk_nonce = data.get("vk_nonce")
    if vk_nonce and redis:
        await redis.delete(CacheKeys.vk_auth(vk_nonce))
        await redis.delete(CacheKeys.vk_oauth(vk_nonce))
        await redis.delete(CacheKeys.vk_oauth_meta(vk_nonce))

    await state.clear()

    if project_id:
        project = await project_service_factory(db).get_owned_project(project_id, user.id)
        if project:
            conn_svc = ConnectionService(db, http_client)
            connections = await conn_svc.get_by_project(project_id)
            text = _build_connections_text(project.name, connections)
            await edit_screen(
                msg,
                "empty_connections.png",
                text,
                reply_markup=connection_list_kb(connections, project_id),
            )
            await callback.answer()
            return

    await safe_edit_text(msg, "Подключение отменено.", reply_markup=menu_kb())
    await callback.answer()


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


@router.callback_query(F.data.regexp(r"^conn:\d+:vk_cancel$"))
async def cancel_vk_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
    redis: RedisClient,
) -> None:
    """Cancel VK connection via inline button — also cleans up VK OAuth Redis keys."""
    await _cancel_connection_wizard(callback, state, user, db, http_client, project_service_factory, redis)
