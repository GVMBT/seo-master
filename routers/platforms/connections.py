"""Connection list, manage, delete + 4 connection wizard FSMs."""

import html
import secrets
import time

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
    Message,
)

from bot.assets import edit_screen
from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.validators import TG_CHANNEL_RE, URL_RE
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from keyboards.inline import (
    cancel_kb,
    connection_delete_confirm_kb,
    connection_list_kb,
    connection_manage_kb,
    menu_kb,
)
from services.connections import ConnectionService
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()


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
    oauth_callback = State()
    select_group = State()


class ConnectPinterestFSM(StatesGroup):
    oauth_callback = State()
    select_board = State()


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

    safe_name = html.escape(project.name)
    text = f"<b>{safe_name}</b> — Подключения"
    if not connections:
        text += "\n\nПодключений пока нет. Добавьте платформу для публикации."

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

    safe_name = html.escape(project.name)
    text = f"<b>{safe_name}</b> — Подключения"
    if not connections:
        text += "\n\nПодключений пока нет. Добавьте платформу для публикации."

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

    status_text = "Активно" if conn.status == "active" else "Ошибка"
    safe_id = html.escape(conn.identifier)
    text = f"<b>{conn.platform_type.capitalize()}</b>\n\nИдентификатор: {safe_id}\nСтатус: {status_text}\n"
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
    await safe_edit_text(
        msg,
        f"Удалить подключение {conn.platform_type.capitalize()} ({safe_id})?\n\n"
        "Связанные расписания будут отменены.\n"
        "Это действие нельзя отменить.",
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
        safe_name = html.escape(project.name)
        await safe_edit_text(msg, 
            f"Подключение {conn.platform_type.capitalize()} ({safe_id}) удалено.\n\n<b>{safe_name}</b> — Подключения",
            reply_markup=connection_list_kb(connections, project_id),
        )
        log.info("connection_deleted", conn_id=conn_id, user_id=user.id)
    else:
        await safe_edit_text(msg, "Ошибка удаления подключения.", reply_markup=menu_kb())

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
        "Подключение WordPress\n\nШаг 1/3 \u2014 Введите URL сайта WordPress:\n\n<i>Пример: example.com</i>",
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
        "Шаг 2/3 \u2014 Введите логин WordPress:",
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
        "Шаг 3/3 \u2014 Введите Application Password:\n\n"
        "Создайте его в WordPress: Пользователи \u2192 Профиль \u2192 Application Passwords.\n"
        "Формат: xxxx xxxx xxxx xxxx xxxx xxxx",
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
        "Подключение Telegram-канала\n\n"
        "Шаг 1/2 \u2014 Введите ссылку на канал:\n\n"
        "<i>Формат: @channel, t.me/channel или ID (-100...)</i>",
        reply_markup=cancel_kb(f"conn:{project_id}:tg_cancel"),
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
        await message.answer("Некорректный формат. Введите @channel, t.me/channel или -100XXXX.")
        return

    # Normalize to consistent format
    channel_id = text
    if text.startswith("https://t.me/") or text.startswith("http://t.me/") or text.startswith("t.me/"):
        channel_id = "@" + text.split("/")[-1]

    data = await state.update_data(tg_channel=channel_id)
    pid = data.get("connect_project_id", 0)
    await state.set_state(ConnectTelegramFSM.token)
    await message.answer(
        "Шаг 2/2 \u2014 Создайте бота через @BotFather и отправьте его токен.\n\n"
        "После этого добавьте бота в канал как администратора с правом публикации.",
        reply_markup=cancel_kb(f"conn:{pid}:tg_cancel"),
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
    """Start VK OAuth connection wizard (VK ID OAuth 2.1 + PKCE)."""
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

    # Delegate nonce + meta + URL to VKOAuthService (CR-118: thin router)
    from api.vk_oauth import VKOAuthService

    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    if not base_url:
        await msg.answer("Ошибка конфигурации сервера. Попробуйте позже.")
        return

    vk_svc = VKOAuthService(
        http_client=http_client,
        redis=redis,
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=settings.vk_app_id,
        redirect_uri=f"{base_url}/api/auth/vk/callback",
    )
    nonce = vk_svc.generate_nonce()
    await vk_svc.store_meta(nonce, project_id)
    oauth_url = vk_svc.build_oauth_url(user.id, nonce)

    await state.set_state(ConnectVKFSM.oauth_callback)
    await state.update_data(
        last_update_time=time.time(),
        connect_project_id=project_id,
        vk_nonce=nonce,
    )

    await msg.answer(
        "Подключение VK\n\n"
        "Нажмите кнопку ниже, чтобы авторизоваться через VK ID.\n"
        "После авторизации вы будете перенаправлены обратно в бот.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Авторизоваться в VK", url=oauth_url)],
                [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:vk_cancel")],
            ]
        ),
    )
    await callback.answer()

    # NOTE: VK group selection after deep-link is handled in routers/start.py
    # (vk_group_select_deeplink callback). ConnectVKFSM.select_group is kept
    # for FSM state tracking but the handler is via deep-link flow.


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

    # Store nonce → project_id mapping in Redis (10 min TTL)
    await redis.set(f"pinterest_oauth:{nonce}", str(project_id), ex=600)

    await state.set_state(ConnectPinterestFSM.oauth_callback)
    await state.update_data(
        last_update_time=time.time(),
        connect_project_id=project_id,
        pinterest_nonce=nonce,
    )

    await msg.answer(
        "Подключение Pinterest\n\n"
        "Нажмите кнопку ниже, чтобы авторизоваться в Pinterest.\n"
        "После авторизации вы будете перенаправлены обратно в бот.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Авторизоваться в Pinterest", url=oauth_url)],
                [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:list")],
            ]
        ),
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
    if not project_id:
        data = await state.get_data()
        pid = data.get("connect_project_id")
        project_id = int(pid) if pid else None
    await state.clear()

    if project_id:
        project = await project_service_factory(db).get_owned_project(project_id, user.id)
        if project:
            conn_svc = ConnectionService(db, http_client)
            connections = await conn_svc.get_by_project(project_id)
            safe_name = html.escape(project.name)
            await edit_screen(
                msg,
                "empty_connections.png",
                f"<b>{safe_name}</b> — Подключения",
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
) -> None:
    """Cancel VK connection via inline button."""
    await _cancel_connection_wizard(callback, state, user, db, http_client, project_service_factory)
