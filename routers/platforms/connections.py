"""Router: platform connections CRUD + 4 Connect FSM flows.

FSM definitions from docs/FSM_SPEC.md section 1.
Edge cases: E08 (VK token revoked), E20 (Pinterest OAuth timeout),
E21 (Pinterest OAuth error), E30 (CSRF protection via HMAC state).
"""

import html
import re
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
import structlog
from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.config import get_settings
from bot.exceptions import AppError
from bot.fsm_utils import ensure_no_active_fsm
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnection, PlatformConnectionCreate, PlatformScheduleUpdate, User
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.reply import cancel_kb, main_menu
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="platforms_connections")

# ---------------------------------------------------------------------------
# FSM definitions (per FSM_SPEC.md section 1)
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
# Validation patterns
# ---------------------------------------------------------------------------

_URL_RE = re.compile(r"^https?://\S+$")
_TG_CHANNEL_RE = re.compile(r"^(@[\w]{5,32}|https?://t\.me/[\w]+|-100\d{10,13})$")
_BOT_TOKEN_RE = re.compile(r"^\d{8,10}:[A-Za-z0-9_-]{35,}$")
_VK_TOKEN_RE = re.compile(r"^vk1\.a\..+$")
_WP_APP_PASSWORD_RE = re.compile(r"^[A-Za-z0-9]{4}(\s[A-Za-z0-9]{4}){5}$")

# Platform display names
_PLATFORM_NAMES: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Telegram",
    "vk": "VK",
    "pinterest": "Pinterest",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_connections_repo(db: SupabaseClient) -> ConnectionsRepository:
    """Create ConnectionsRepository with CredentialManager."""
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    return ConnectionsRepository(db, cm)


async def _get_project_or_alert(
    project_id: int, user_id: int, db: SupabaseClient, callback: CallbackQuery
) -> bool:
    """Verify project exists and user owns it. Sends alert on failure."""
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user_id:
        await callback.answer("Проект не найден.", show_alert=True)
        return False
    return True


def _connection_list_kb(
    connections: list[PlatformConnection], project_id: int
) -> InlineKeyboardBuilder:
    """Build keyboard: connections grouped by platform + add buttons + back."""
    builder = InlineKeyboardBuilder()

    for conn in connections:
        platform_name = _PLATFORM_NAMES.get(conn.platform_type, conn.platform_type)
        status_icon = "" if conn.status == "active" else " [!]"
        text = f"{platform_name}: {conn.identifier}{status_icon}"
        if len(text) > 60:
            text = text[:57] + "..."
        builder.button(text=text, callback_data=f"conn:{conn.id}:card")

    builder.button(text="Добавить WordPress-сайт", callback_data=f"project:{project_id}:add:wordpress")
    builder.button(text="Добавить Telegram", callback_data=f"project:{project_id}:add:telegram")
    builder.button(text="Добавить VK", callback_data=f"project:{project_id}:add:vk")
    builder.button(text="Добавить Pinterest", callback_data=f"project:{project_id}:add:pinterest")
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder


def _connection_card_kb(conn: PlatformConnection, project_id: int) -> InlineKeyboardBuilder:
    """Build keyboard for a single connection card."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Удалить", callback_data=f"conn:{conn.id}:delete")
    builder.button(text="К подключениям", callback_data=f"project:{project_id}:connections")
    builder.adjust(1)
    return builder


def _connection_delete_confirm_kb(conn_id: int, project_id: int) -> InlineKeyboardBuilder:
    """Delete confirmation: [Да, удалить] + [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Да, удалить", callback_data=f"conn:{conn_id}:delete:confirm")
    builder.button(text="Отмена", callback_data=f"project:{project_id}:connections")
    builder.adjust(2)
    return builder


def _format_connection_card(conn: PlatformConnection) -> str:
    """Format connection info for card display."""
    platform_name = _PLATFORM_NAMES.get(conn.platform_type, conn.platform_type)
    status_map = {"active": "Активно", "error": "Ошибка", "disconnected": "Отключено"}
    status_text = status_map.get(conn.status, conn.status)
    return (
        f"<b>{platform_name}</b>\n"
        f"Идентификатор: {html.escape(conn.identifier)}\n"
        f"Статус: {status_text}"
    )


# ---------------------------------------------------------------------------
# Connection list
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^project:(\d+):connections$"))
async def cb_connection_list(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show connections list for a project."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _get_project_or_alert(project_id, user.id, db, callback):
        return

    repo = _get_connections_repo(db)
    connections = await repo.get_by_project(project_id)

    if connections:
        text = f"Подключения платформ ({len(connections)}):"
    else:
        text = "Нет подключенных платформ. Добавьте первое подключение."

    await msg.edit_text(
        text,
        reply_markup=_connection_list_kb(connections, project_id).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Connection card
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:(\d+):card$"))
async def cb_connection_card(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show a single connection card."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = _get_connections_repo(db)
    conn = await repo.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    # Ownership: verify project belongs to user
    project = await ProjectsRepository(db).get_by_id(conn.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    await msg.edit_text(
        _format_connection_card(conn),
        reply_markup=_connection_card_kb(conn, conn.project_id).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Delete connection (2-step)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^conn:(\d+):delete$"))
async def cb_connection_delete(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Show delete confirmation for a connection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = _get_connections_repo(db)
    conn = await repo.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project = await ProjectsRepository(db).get_by_id(conn.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    platform_name = _PLATFORM_NAMES.get(conn.platform_type, conn.platform_type)
    await msg.edit_text(
        f"Удалить подключение {platform_name} ({html.escape(conn.identifier)})?\n"
        "Все связанные расписания будут отменены.",
        reply_markup=_connection_delete_confirm_kb(conn.id, conn.project_id).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^conn:(\d+):delete:confirm$"))
async def cb_connection_delete_confirm(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Confirm and delete a connection."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    conn_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    repo = _get_connections_repo(db)
    conn = await repo.get_by_id(conn_id)
    if not conn:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    project = await ProjectsRepository(db).get_by_id(conn.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Подключение не найдено.", show_alert=True)
        return

    # E24: cancel QStash schedules referencing this connection before delete
    from db.repositories.schedules import SchedulesRepository

    sched_repo = SchedulesRepository(db)
    schedules = await sched_repo.get_by_connection(conn.id)
    for s in schedules:
        if s.qstash_schedule_ids:
            # Phase 9: add actual QStash API call here
            log.warning(
                "orphan_qstash_schedules_on_delete",
                schedule_id=s.id,
                qstash_ids=s.qstash_schedule_ids,
            )
            await sched_repo.update(
                s.id,
                PlatformScheduleUpdate(qstash_schedule_ids=[], enabled=False),
            )

    await repo.delete(conn.id)

    # Refresh connection list
    connections = await repo.get_by_project(conn.project_id)
    text = (
        f"Подключение удалено. Подключения ({len(connections)}):"
        if connections
        else "Подключение удалено. Нет подключенных платформ."
    )
    await msg.edit_text(
        text,
        reply_markup=_connection_list_kb(connections, conn.project_id).as_markup(),
    )
    await callback.answer("Подключение удалено.")


# ===========================================================================
# ConnectWordPressFSM (3 steps)
# ===========================================================================


@router.callback_query(F.data.regexp(r"^project:(\d+):add:wordpress$"))
async def cb_wordpress_add(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Entry point: start ConnectWordPressFSM."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _get_project_or_alert(project_id, user.id, db, callback):
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectWordPressFSM.url)
    await state.update_data(project_id=project_id)
    await msg.answer(
        "Шаг 1/3. Введите URL сайта WordPress:\n"
        "Пример: https://comfort-mebel.ru",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ConnectWordPressFSM.url, F.text)
async def fsm_wp_url(message: Message, state: FSMContext) -> None:
    """FSM step 1: WordPress URL."""
    url = message.text.strip()  # type: ignore[union-attr]
    # Auto-prepend https:// if missing
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"
    if not _URL_RE.match(url):
        await message.answer("Введите корректный URL сайта (https://...).")
        return
    await state.update_data(wp_url=url)
    await state.set_state(ConnectWordPressFSM.login)
    await message.answer("Шаг 2/3. Введите логин WordPress:")


@router.message(ConnectWordPressFSM.login, F.text)
async def fsm_wp_login(message: Message, state: FSMContext) -> None:
    """FSM step 2: WordPress login."""
    login = message.text.strip()  # type: ignore[union-attr]
    if len(login) < 1 or len(login) > 100:
        await message.answer("Введите логин WordPress (1-100 символов).")
        return
    await state.update_data(wp_login=login)
    await state.set_state(ConnectWordPressFSM.password)
    await message.answer(
        "Шаг 3/3. Введите Application Password:\n"
        "Формат: xxxx xxxx xxxx xxxx xxxx xxxx\n"
        "(Создайте в WP-админке: Пользователи -> Профиль -> Пароли приложений)"
    )


@router.message(ConnectWordPressFSM.password, F.text)
async def fsm_wp_password(
    message: Message, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """FSM step 3: WordPress Application Password. Auto-delete sensitive message."""
    password = message.text.strip()  # type: ignore[union-attr]
    if not _WP_APP_PASSWORD_RE.match(password):
        await message.answer(
            "Введите Application Password в формате: xxxx xxxx xxxx xxxx xxxx xxxx"
        )
        return

    # Auto-delete message containing password
    try:
        await message.delete()
    except Exception:
        log.warning("failed_to_delete_password_message", user_id=user.id)

    data = await state.get_data()
    await state.clear()

    wp_url = data["wp_url"]
    wp_login = data["wp_login"]
    project_id = data["project_id"]

    # Extract hostname for identifier
    parsed = urlparse(wp_url)
    identifier = parsed.hostname or wp_url

    credentials = {
        "url": wp_url,
        "login": wp_login,
        "app_password": password,
    }

    repo = _get_connections_repo(db)
    try:
        conn = await repo.create(
            PlatformConnectionCreate(
                project_id=project_id,
                platform_type="wordpress",
                identifier=identifier,
            ),
            raw_credentials=credentials,
        )
    except AppError:
        log.exception("wordpress_connection_create_failed", project_id=project_id)
        await message.answer(
            "Не удалось сохранить подключение. Попробуйте ещё раз.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return
    except Exception:
        log.exception("wordpress_connection_create_error", project_id=project_id)
        await message.answer(
            "Не удалось сохранить подключение. Попробуйте ещё раз.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    await message.answer(
        f"Сайт подключен!\n\n{_format_connection_card(conn)}",
        reply_markup=_connection_card_kb(conn, project_id).as_markup(),
    )
    # Restore reply keyboard (I3 pattern)
    await message.answer("Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin"))


# ===========================================================================
# ConnectTelegramFSM (2 steps)
# ===========================================================================


@router.callback_query(F.data.regexp(r"^project:(\d+):add:telegram$"))
async def cb_telegram_add(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Entry point: start ConnectTelegramFSM."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _get_project_or_alert(project_id, user.id, db, callback):
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectTelegramFSM.channel)
    await state.update_data(project_id=project_id)
    await msg.answer(
        "Для публикации в канал нужен отдельный бот:\n"
        "1. Создайте бота через @BotFather\n"
        "2. Добавьте его АДМИНИСТРАТОРОМ канала\n"
        "   (права: публикация + редактирование сообщений)\n"
        "3. Введите данные ниже\n\n"
        "Шаг 1/2. Введите ссылку на канал:\n"
        "Формат: @channel, t.me/channel или -100XXXXXXXXXX",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ConnectTelegramFSM.channel, F.text)
async def fsm_telegram_channel(message: Message, state: FSMContext) -> None:
    """FSM step 1: Telegram channel link/ID."""
    channel = message.text.strip()  # type: ignore[union-attr]
    if not _TG_CHANNEL_RE.match(channel):
        await message.answer(
            "Введите @channel, t.me/channel или числовой ID (-100XXXXXXXXXX)."
        )
        return
    await state.update_data(channel_raw=channel)
    await state.set_state(ConnectTelegramFSM.token)
    await message.answer(
        "Шаг 2/2. Введите токен бота от @BotFather:\n"
        "Формат: 1234567890:ABCdefGHI..."
    )


@router.message(ConnectTelegramFSM.token, F.text)
async def fsm_telegram_token(
    message: Message, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """FSM step 2: Bot token. Validate via getMe + check admin rights."""
    token = message.text.strip()  # type: ignore[union-attr]
    if not _BOT_TOKEN_RE.match(token):
        await message.answer(
            "Токен невалиден. Получите токен у @BotFather."
        )
        return

    # Auto-delete message containing token
    try:
        await message.delete()
    except Exception:
        log.warning("failed_to_delete_token_message", user_id=user.id)

    data = await state.get_data()
    channel_raw = data["channel_raw"]
    project_id = data["project_id"]

    # Resolve channel identifier
    channel_id: str
    if channel_raw.startswith("-100"):
        channel_id = channel_raw
    elif channel_raw.startswith("https://t.me/") or channel_raw.startswith("http://t.me/"):
        # Extract username from URL
        username = channel_raw.split("/")[-1]
        channel_id = f"@{username}"
    else:
        channel_id = channel_raw  # Already @channel format

    # Validate bot token via getMe and check admin rights
    try:
        pub_bot = Bot(token=token)
        try:
            bot_info = await pub_bot.get_me()
            # Check if bot is admin in the channel
            admins = await pub_bot.get_chat_administrators(channel_id)
            is_admin = any(
                admin.user.id == bot_info.id for admin in admins
            )
            if not is_admin:
                await state.clear()
                await message.answer(
                    "Бот не является администратором канала. "
                    "Добавьте бота как администратора с правом публикации.",
                    reply_markup=main_menu(is_admin=user.role == "admin"),
                )
                return

            # Get channel info for identifier
            chat = await pub_bot.get_chat(channel_id)
            identifier = chat.username or str(chat.id)
            resolved_channel_id = str(chat.id)
        finally:
            await pub_bot.session.close()
    except Exception as exc:
        log.warning("telegram_connect_failed", error=str(exc), user_id=user.id)
        await state.clear()
        await message.answer(
            "Не удалось подключить канал. Проверьте токен и права бота.",
            reply_markup=cancel_kb(),
        )
        return

    await state.clear()

    credentials = {
        "bot_token": token,
        "channel_id": resolved_channel_id,
        "channel_username": f"@{chat.username}" if chat.username else "",
    }

    repo = _get_connections_repo(db)
    try:
        conn = await repo.create(
            PlatformConnectionCreate(
                project_id=project_id,
                platform_type="telegram",
                identifier=identifier,
            ),
            raw_credentials=credentials,
        )
    except Exception:
        log.exception("telegram_connection_create_error", project_id=project_id)
        await message.answer(
            "Не удалось сохранить подключение. Возможно, канал уже подключен.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    await message.answer(
        f"Канал подключен!\n\n{_format_connection_card(conn)}",
        reply_markup=_connection_card_kb(conn, project_id).as_markup(),
    )
    await message.answer("Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin"))


# ===========================================================================
# ConnectVKFSM (2 steps)
# ===========================================================================


@router.callback_query(F.data.regexp(r"^project:(\d+):add:vk$"))
async def cb_vk_add(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Entry point: start ConnectVKFSM."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _get_project_or_alert(project_id, user.id, db, callback):
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    await state.set_state(ConnectVKFSM.token)
    await state.update_data(project_id=project_id)
    await msg.answer(
        "Шаг 1/2. Вставьте VK-токен доступа:\n"
        "Формат: vk1.a.XXXXXXX\n"
        "(Получите на vkhost.github.io с правами: wall, photos, groups)",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(ConnectVKFSM.token, F.text)
async def fsm_vk_token(
    message: Message, state: FSMContext, user: User, db: SupabaseClient, http_client: httpx.AsyncClient
) -> None:
    """FSM step 1: VK token. Validate and fetch groups."""
    token = message.text.strip()  # type: ignore[union-attr]
    if not _VK_TOKEN_RE.match(token):
        await message.answer(
            "Токен должен начинаться с vk1.a. Проверьте токен."
        )
        return

    # Auto-delete message containing token
    try:
        await message.delete()
    except Exception:
        log.warning("failed_to_delete_vk_token_message", user_id=user.id)

    vk_api = "https://api.vk.com/method"
    vk_version = "5.199"

    try:
        resp = await http_client.post(
            f"{vk_api}/groups.get",
            data={
                "access_token": token,
                "filter": "admin,editor",
                "extended": "1",
                "v": vk_version,
            },
        )
        data = resp.json()
        if "error" in data:
            error_msg = data["error"].get("error_msg", "Unknown error")
            log.warning("vk_groups_fetch_error", error=error_msg, user_id=user.id)
            await state.clear()
            await message.answer(
                f"Ошибка VK API: {error_msg}\n"
                "Проверьте токен и попробуйте снова.",
                reply_markup=main_menu(is_admin=user.role == "admin"),
            )
            return

        groups = data.get("response", {}).get("items", [])
    except Exception as exc:
        log.warning("vk_api_request_failed", error=str(exc), user_id=user.id)
        await state.clear()
        await message.answer(
            "Не удалось связаться с VK API. Попробуйте позже.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    if not groups:
        await state.clear()
        await message.answer(
            "У вас нет групп с правами администратора/редактора.\n"
            "Создайте группу в VK или получите права администратора.",
            reply_markup=main_menu(is_admin=user.role == "admin"),
        )
        return

    # Save token and groups in state, show group selection
    await state.update_data(
        vk_token=token,
        vk_groups=[
            {"id": str(g["id"]), "name": g.get("name", f"Group {g['id']}")}
            for g in groups
        ],
    )
    await state.set_state(ConnectVKFSM.select_group)

    builder = InlineKeyboardBuilder()
    for g in groups:
        members = g.get("members_count", 0)
        name = g.get("name", f"Group {g['id']}")
        text = f"{name} ({members} участн.)"
        if len(text) > 60:
            text = text[:57] + "..."
        builder.button(text=text, callback_data=f"vk_group:{g['id']}")
    builder.adjust(1)

    await message.answer(
        "Шаг 2/2. Выберите группу для публикации:",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(ConnectVKFSM.select_group, F.data.startswith("vk_group:"))
async def cb_vk_select_group(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """FSM step 2: select VK group from list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    group_id = callback.data.split(":")[1]  # type: ignore[union-attr]
    data = await state.get_data()
    vk_token = data["vk_token"]
    vk_groups = data["vk_groups"]
    project_id = data["project_id"]

    # Find selected group
    group = next((g for g in vk_groups if g["id"] == group_id), None)
    if not group:
        await callback.answer("Группа не найдена.", show_alert=True)
        return

    await state.clear()

    # Use "access_token" per CLAUDE.md decision (#2: VK credentials field)
    credentials = {
        "access_token": vk_token,
        "group_id": group_id,
        "group_name": group["name"],
    }

    repo = _get_connections_repo(db)
    try:
        conn = await repo.create(
            PlatformConnectionCreate(
                project_id=project_id,
                platform_type="vk",
                identifier=str(group_id),
            ),
            raw_credentials=credentials,
        )
    except Exception:
        log.exception("vk_connection_create_error", project_id=project_id)
        await msg.edit_text(
            "Не удалось сохранить подключение. Возможно, группа уже подключена.",
        )
        await msg.answer(
            "Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin")
        )
        await callback.answer()
        return

    await msg.edit_text(
        f"VK подключен!\n\n{_format_connection_card(conn)}",
        reply_markup=_connection_card_kb(conn, project_id).as_markup(),
    )
    await msg.answer("Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin"))
    await callback.answer()


# ===========================================================================
# ConnectPinterestFSM (OAuth flow)
# ===========================================================================


@router.callback_query(F.data.regexp(r"^project:(\d+):add:pinterest$"))
async def cb_pinterest_add(callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient) -> None:
    """Entry point: start ConnectPinterestFSM. Send OAuth link."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    if not await _get_project_or_alert(project_id, user.id, db, callback):
        return

    settings = get_settings()
    if not settings.pinterest_app_id or not settings.railway_public_url:
        await callback.answer("Pinterest OAuth не настроен.", show_alert=True)
        return

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(f"Предыдущий процесс ({interrupted}) прерван.")

    # Generate nonce and build HMAC state (E30)
    from api.auth_service import build_state

    nonce = secrets.token_hex(16)
    oauth_state = build_state(user.id, nonce, settings.encryption_key.get_secret_value())
    redirect_uri = f"{settings.railway_public_url}/api/auth/pinterest/callback"

    # Build Pinterest OAuth authorization URL
    auth_url = (
        "https://www.pinterest.com/oauth/?"
        f"client_id={settings.pinterest_app_id}"
        f"&redirect_uri={redirect_uri}"
        "&response_type=code"
        "&scope=boards:read,pins:read,pins:write"
        f"&state={oauth_state}"
    )

    await state.set_state(ConnectPinterestFSM.oauth_callback)
    await state.update_data(project_id=project_id, nonce=nonce)

    # Send inline button with OAuth URL
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Авторизоваться в Pinterest", url=auth_url)],
    ])
    await msg.answer(
        "Шаг 1/2. Нажмите кнопку ниже для авторизации в Pinterest.\n"
        "После авторизации вы будете перенаправлены обратно в бота.",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(ConnectPinterestFSM.select_board, F.data.startswith("pin_board:"))
async def cb_pinterest_select_board(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient
) -> None:
    """FSM step 2: select Pinterest board from list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    board_id = callback.data.split(":")[1]  # type: ignore[union-attr]
    data = await state.get_data()
    project_id = data["project_id"]
    pinterest_tokens = data.get("pinterest_tokens", {})
    boards = data.get("pinterest_boards", [])

    board = next((b for b in boards if b["id"] == board_id), None)
    if not board:
        await callback.answer("Доска не найдена.", show_alert=True)
        return

    await state.clear()

    # Calculate token expiration
    expires_in = pinterest_tokens.get("expires_in", 2592000)
    expires_at = (datetime.now(tz=UTC) + timedelta(seconds=expires_in)).isoformat()

    credentials = {
        "access_token": pinterest_tokens["access_token"],
        "refresh_token": pinterest_tokens.get("refresh_token", ""),
        "expires_at": expires_at,
        "board_id": board_id,
        "board_name": board["name"],
    }

    repo = _get_connections_repo(db)
    try:
        conn = await repo.create(
            PlatformConnectionCreate(
                project_id=project_id,
                platform_type="pinterest",
                identifier=board["name"],
            ),
            raw_credentials=credentials,
        )
    except Exception:
        log.exception("pinterest_connection_create_error", project_id=project_id)
        await msg.edit_text("Не удалось сохранить подключение Pinterest.")
        await msg.answer(
            "Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin")
        )
        await callback.answer()
        return

    await msg.edit_text(
        f"Pinterest подключен!\n\n{_format_connection_card(conn)}",
        reply_markup=_connection_card_kb(conn, project_id).as_markup(),
    )
    await msg.answer("Выберите действие:", reply_markup=main_menu(is_admin=user.role == "admin"))
    await callback.answer()
