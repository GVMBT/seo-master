"""Connection list, manage, delete + 4 connection wizard FSMs."""

import html
import re
import secrets
import time
from typing import Any

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from cache.client import RedisClient
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnectionCreate, User
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    connection_delete_confirm_kb,
    connection_list_kb,
    connection_manage_kb,
    vk_group_select_kb,
)
from services.scheduler import SchedulerService

log = structlog.get_logger()
router = Router()

_URL_RE = re.compile(
    r"^(?:https?://)?[\w][\w.-]*\.[a-z]{2,}(?:[/\w.\-?#=&%]*)?$",
    re.IGNORECASE,
)

# Telegram channel formats: @channel, t.me/channel, -100XXXX
_TG_CHANNEL_RE = re.compile(r"^(?:@[\w]{5,}|(?:https?://)?t\.me/[\w]{5,}|-100\d{10,13})$")


def _make_conn_repo(db: SupabaseClient) -> ConnectionsRepository:
    """Create ConnectionsRepository with CredentialManager."""
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    return ConnectionsRepository(db, cm)


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
    token = State()
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
) -> None:
    """Show connection list for a project (UX_TOOLBOX.md section 5.1)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)

    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    conn_repo = _make_conn_repo(db)
    connections = await conn_repo.get_by_project(project_id)

    safe_name = html.escape(project.name)
    text = f"<b>{safe_name}</b> — Подключения"
    if not connections:
        text += "\n\nПодключений пока нет. Добавьте платформу для публикации."

    await callback.message.edit_text(
        text,
        reply_markup=connection_list_kb(connections, project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^conn:\d+:list$"))
async def connections_list_back(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Back navigation to connection list."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)

    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    conn_repo = _make_conn_repo(db)
    connections = await conn_repo.get_by_project(project_id)

    safe_name = html.escape(project.name)
    text = f"<b>{safe_name}</b> — Подключения"
    if not connections:
        text += "\n\nПодключений пока нет. Добавьте платформу для публикации."

    await callback.message.edit_text(
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
) -> None:
    """Show connection detail (UX_TOOLBOX.md section 5.2)."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    conn_repo = _make_conn_repo(db)
    conn = await conn_repo.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(conn.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    status_text = "Активно" if conn.status == "active" else "Ошибка"
    safe_id = html.escape(conn.identifier)
    text = f"<b>{conn.platform_type.capitalize()}</b>\n\nИдентификатор: {safe_id}\nСтатус: {status_text}\n"
    await callback.message.edit_text(
        text,
        reply_markup=connection_manage_kb(conn_id, conn.project_id),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^conn:\d+:delete$"))
async def confirm_connection_delete(
    callback: CallbackQuery,
    user: User,
    db: SupabaseClient,
) -> None:
    """Show connection delete confirmation."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    conn_repo = _make_conn_repo(db)
    conn = await conn_repo.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(conn.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    safe_id = html.escape(conn.identifier)
    await callback.message.edit_text(
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
    scheduler_service: SchedulerService,
) -> None:
    """Delete connection with E24 cleanup: cancel QStash schedules."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    conn_repo = _make_conn_repo(db)
    conn = await conn_repo.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(conn.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project_id = conn.project_id

    # E24: Cancel QStash schedules for this connection
    await scheduler_service.cancel_schedules_for_connection(conn_id)

    deleted = await conn_repo.delete(conn_id)
    if deleted:
        safe_id = html.escape(conn.identifier)
        # Reload connection list
        connections = await conn_repo.get_by_project(project_id)
        safe_name = html.escape(project.name)
        await callback.message.edit_text(
            f"Подключение {conn.platform_type.capitalize()} ({safe_id}) удалено.\n\n<b>{safe_name}</b> — Подключения",
            reply_markup=connection_list_kb(connections, project_id),
        )
        log.info("connection_deleted", conn_id=conn_id, user_id=user.id)
    else:
        await callback.message.edit_text("Ошибка удаления подключения.")

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
) -> None:
    """Start WordPress connection wizard."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectWordPressFSM.url)
    await state.update_data(last_update_time=time.time(), connect_project_id=project_id)

    await callback.message.answer(
        "Подключение WordPress\n\nВведите адрес вашего сайта.\n\n<i>Пример: example.com</i>",
    )
    await callback.answer()


@router.message(ConnectWordPressFSM.url, F.text)
async def wp_process_url(message: Message, state: FSMContext) -> None:
    """WP step 1: site URL."""
    text = (message.text or "").strip()
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.")
        return

    if not _URL_RE.match(text):
        await message.answer("Некорректный URL. Попробуйте ещё раз.")
        return

    url = text if text.startswith("http") else f"https://{text}"
    await state.update_data(wp_url=url)
    await state.set_state(ConnectWordPressFSM.login)
    await message.answer("Введите логин WordPress (имя пользователя).")


@router.message(ConnectWordPressFSM.login, F.text)
async def wp_process_login(message: Message, state: FSMContext) -> None:
    """WP step 2: login."""
    text = (message.text or "").strip()
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.")
        return

    if len(text) < 1 or len(text) > 100:
        await message.answer("Логин: от 1 до 100 символов.")
        return

    await state.update_data(wp_login=text)
    await state.set_state(ConnectWordPressFSM.password)
    await message.answer(
        "Введите Application Password.\n\n"
        "Создайте его в WordPress: Пользователи → Профиль → Application Passwords.\n"
        "Формат: xxxx xxxx xxxx xxxx xxxx xxxx"
    )


@router.message(ConnectWordPressFSM.password, F.text)
async def wp_process_password(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """WP step 3: Application Password — validate and create connection."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.")
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

    # Validate WP REST API
    api_url = f"{wp_url}/wp-json/wp/v2/posts"
    try:
        resp = await http_client.head(
            api_url,
            auth=httpx.BasicAuth(wp_login, text),
            timeout=10.0,
        )
        if resp.status_code == 401:
            await message.answer("Неверный логин или пароль. Попробуйте ещё раз.")
            return
        if resp.status_code >= 400:
            await message.answer(f"Сайт вернул ошибку ({resp.status_code}). Проверьте URL и данные.")
            return
    except httpx.TimeoutException:
        await message.answer("Сайт не отвечает. Проверьте URL.")
        return
    except httpx.RequestError:
        await message.answer("Не удалось подключиться к сайту. Проверьте URL.")
        return

    # E41: Check duplicate — warn but allow (same site in multiple projects is valid)
    conn_repo = _make_conn_repo(db)
    # Extract domain as identifier
    identifier = wp_url.replace("https://", "").replace("http://", "").rstrip("/")
    existing = await conn_repo.get_by_identifier_for_user(identifier, "wordpress", user.id)
    if existing and existing.project_id == project_id:
        await message.answer(f"Сайт {html.escape(identifier)} уже подключён к этому проекту.")
        return
    if existing:
        # E41: same site in different project — warn user but allow
        await message.answer(
            f"Сайт {html.escape(identifier)} уже подключён к другому проекту.\n"
            "Публикации в оба проекта будут идти на один сайт.",
        )
        log.info("wp_cross_project_connection", identifier=identifier, existing_project=existing.project_id)

    # Re-validate ownership before creating connection (I7)
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await state.clear()
        await message.answer("Проект не найден.")
        return

    await state.clear()

    # Create connection
    conn = await conn_repo.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="wordpress",
            identifier=identifier,
        ),
        raw_credentials={"url": wp_url, "login": wp_login, "app_password": text},
    )

    log.info("wordpress_connected", conn_id=conn.id, project_id=project_id, identifier=identifier)

    # Reload list
    connections = await conn_repo.get_by_project(project_id)
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    safe_name = html.escape(project.name) if project else ""
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
) -> None:
    """Start Telegram connection wizard."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectTelegramFSM.channel)
    await state.update_data(last_update_time=time.time(), connect_project_id=project_id)

    await callback.message.answer(
        "Подключение Telegram-канала\n\n"
        "Введите ссылку на канал.\n\n"
        "<i>Формат: @channel, t.me/channel или ID (-100...)</i>",
    )
    await callback.answer()


@router.message(ConnectTelegramFSM.channel, F.text)
async def tg_process_channel(message: Message, state: FSMContext) -> None:
    """TG step 1: channel identifier."""
    text = (message.text or "").strip()
    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.")
        return

    if not _TG_CHANNEL_RE.match(text):
        await message.answer("Некорректный формат. Введите @channel, t.me/channel или -100XXXX.")
        return

    # Normalize to consistent format
    channel_id = text
    if text.startswith("https://t.me/") or text.startswith("http://t.me/") or text.startswith("t.me/"):
        channel_id = "@" + text.split("/")[-1]

    await state.update_data(tg_channel=channel_id)
    await state.set_state(ConnectTelegramFSM.token)
    await message.answer(
        "Теперь создайте бота через @BotFather и отправьте его токен.\n\n"
        "После этого добавьте бота в канал как администратора с правом публикации."
    )


@router.message(ConnectTelegramFSM.token, F.text)
async def tg_process_token(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """TG step 2: bot token — validate and create connection."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.")
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

    # Validate via getMe
    temp_bot = Bot(token=text)
    try:
        bot_info = await temp_bot.get_me()
    except Exception:
        await temp_bot.session.close()
        await message.answer("Недействительный токен. Проверьте и попробуйте ещё раз.")
        return

    # Check bot is admin of the channel
    try:
        admins = await temp_bot.get_chat_administrators(channel_id)
        bot_is_admin = any(a.user.id == bot_info.id for a in admins)
        if not bot_is_admin:
            await temp_bot.session.close()
            await message.answer(
                f"Бот @{bot_info.username} не является администратором канала {channel_id}.\n"
                "Добавьте бота в канал и назначьте администратором."
            )
            return
    except Exception:
        await temp_bot.session.close()
        await message.answer(
            f"Не удалось проверить канал {channel_id}.\n"
            "Убедитесь, что канал существует и бот добавлен как администратор."
        )
        return
    finally:
        await temp_bot.session.close()

    # E41: Telegram requires GLOBAL uniqueness — channel must not be connected by ANY user
    conn_repo = _make_conn_repo(db)
    existing = await conn_repo.get_by_identifier_global(channel_id, "telegram")
    if existing and existing.project_id == project_id:
        await message.answer(f"Канал {channel_id} уже подключён к этому проекту.")
        return
    if existing:
        # Global block: another user (or another project of same user) already owns this channel
        await message.answer(
            f"Канал {channel_id} уже подключён другим пользователем.\n"
            "Один канал может быть привязан только к одному проекту.",
        )
        log.warning("tg_global_duplicate_blocked", channel=channel_id, existing_conn=existing.id)
        return

    await state.clear()

    conn = await conn_repo.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="telegram",
            identifier=channel_id,
            metadata={"bot_username": bot_info.username or ""},
        ),
        raw_credentials={"bot_token": text, "channel_id": channel_id},
    )

    log.info("telegram_connected", conn_id=conn.id, project_id=project_id, channel=channel_id)

    connections = await conn_repo.get_by_project(project_id)
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
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
) -> None:
    """Start VK connection wizard."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectVKFSM.token)
    await state.update_data(last_update_time=time.time(), connect_project_id=project_id)

    await callback.message.answer(
        "Подключение VK\n\n"
        "Получите токен доступа:\n"
        "1. Откройте vkhost.github.io/vk-token\n"
        "2. Разрешите доступ\n"
        "3. Скопируйте токен из URL\n\n"
        "Отправьте токен сюда.",
    )
    await callback.answer()


@router.message(ConnectVKFSM.token, F.text)
async def vk_process_token(
    message: Message,
    state: FSMContext,
    http_client: httpx.AsyncClient,
) -> None:
    """VK step 1: validate token and show group selection."""
    text = (message.text or "").strip()

    if text == "Отмена":
        await state.clear()
        await message.answer("Подключение отменено.")
        return

    # Delete message with token for security (after cancel check)
    try:
        await message.delete()
    except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
        log.warning("failed_to_delete_vk_token_message", reason=str(exc))

    if len(text) < 20:
        await message.answer("Токен слишком короткий. Попробуйте ещё раз.")
        return

    # Validate via users.get
    try:
        resp = await http_client.get(
            "https://api.vk.com/method/users.get",
            params={"access_token": text, "v": "5.199"},
            timeout=10.0,
        )
        data = resp.json()
        if "error" in data:
            await message.answer("Недействительный токен. Попробуйте ещё раз.")
            return
    except Exception:
        await message.answer("Ошибка проверки токена. Попробуйте позже.")
        return

    # Get user's groups
    try:
        resp = await http_client.get(
            "https://api.vk.com/method/groups.get",
            params={
                "access_token": text,
                "v": "5.199",
                "filter": "admin,editor",
                "extended": "1",
                "count": "50",
            },
            timeout=10.0,
        )
        groups_data = resp.json()
        groups: list[dict[str, Any]] = groups_data.get("response", {}).get("items", [])
    except Exception:
        await message.answer("Ошибка получения списка групп.")
        return

    if not groups:
        await state.clear()
        await message.answer("У вас нет групп VK, в которых вы администратор или редактор.")
        return

    fsm_data = await state.get_data()
    project_id = int(fsm_data["connect_project_id"])
    # Store only id+name to minimize Redis FSM data size (I6)
    compact_groups = [{"id": g["id"], "name": g.get("name", "")} for g in groups]
    await state.update_data(vk_token=text, vk_groups=compact_groups)
    await state.set_state(ConnectVKFSM.select_group)
    await message.answer(
        "Выберите группу для публикации:",
        reply_markup=vk_group_select_kb(groups, project_id),
    )


@router.callback_query(ConnectVKFSM.select_group, F.data.regexp(r"^vk:group:\d+:select$"))
async def vk_select_group(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """VK step 2: group selected — create connection."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    group_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    data = await state.get_data()
    vk_token = data["vk_token"]
    groups: list[dict[str, Any]] = data.get("vk_groups", [])
    project_id = int(data["connect_project_id"])

    # Find selected group name
    group_name = str(group_id)
    for g in groups:
        if g.get("id") == group_id:
            group_name = g.get("name", str(group_id))
            break

    await state.clear()

    conn_repo = _make_conn_repo(db)
    identifier = f"club{group_id}"

    # E41: Check duplicate — same-project block, cross-project allow
    existing = await conn_repo.get_by_identifier_for_user(identifier, "vk", user.id)
    if existing and existing.project_id == project_id:
        await callback.message.edit_text(f"Группа {html.escape(group_name)} уже подключена к этому проекту.")
        await callback.answer()
        return
    if existing:
        # E41: same group in different project — warn user but allow
        await callback.message.edit_text(
            f"Группа {html.escape(group_name)} уже подключена к другому проекту.\n"
            "Публикации в оба проекта будут идти в одну группу.",
        )
        log.info("vk_cross_project_connection", group=identifier, existing_project=existing.project_id)

    conn = await conn_repo.create(
        PlatformConnectionCreate(
            project_id=project_id,
            platform_type="vk",
            identifier=identifier,
            metadata={"group_name": group_name},
        ),
        raw_credentials={"access_token": vk_token, "group_id": str(group_id)},
    )

    log.info("vk_connected", conn_id=conn.id, project_id=project_id, group_id=group_id)

    connections = await conn_repo.get_by_project(project_id)
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    safe_name = html.escape(project.name) if project else ""
    await callback.message.edit_text(
        f"VK-группа «{html.escape(group_name)}» подключена!\n\n<b>{safe_name}</b> — Подключения",
        reply_markup=connection_list_kb(connections, project_id),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# ConnectPinterestFSM (2 states) — OAuth flow
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:\d+:add:pinterest$"))
async def start_pinterest_connect(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
) -> None:
    """Start Pinterest OAuth connection wizard."""
    if not callback.message or isinstance(callback.message, InaccessibleMessage):
        await callback.answer()
        return

    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await callback.message.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Generate nonce for OAuth
    nonce = secrets.token_urlsafe(16)
    settings = get_settings()
    base_url = settings.railway_public_url.rstrip("/")
    oauth_url = f"{base_url}/api/auth/pinterest?user_id={user.id}&nonce={nonce}"

    # Store nonce → project_id mapping in Redis (10 min TTL)
    await redis.set(f"pinterest_oauth:{nonce}", str(project_id), ex=600)

    await state.set_state(ConnectPinterestFSM.oauth_callback)
    await state.update_data(
        last_update_time=time.time(),
        connect_project_id=project_id,
        pinterest_nonce=nonce,
    )

    await callback.message.answer(
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
