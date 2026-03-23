"""VK connection wizard (ConnectVKFSM)."""

import contextlib
import html
import re
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
    Message,
)

from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_callback_data, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.connections import (
    _VK_AUTH_URL,
    VK_PERSONAL_AUTH,
    VK_STEP1_GROUP_URL,
    VK_STEP2_AUTH,
    VK_TYPE_SELECT,
)
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import PlatformConnectionCreate, User
from keyboards.inline import connection_list_kb, menu_kb
from routers.platforms._shared import _cancel_connection_wizard
from services.connections import ConnectionService
from services.oauth.vk import VKOAuthError, VKOAuthService, parse_vk_group_input

log = structlog.get_logger()
router = Router()


class ConnectVKFSM(StatesGroup):
    select_type = State()  # group or personal page
    enter_group_url = State()  # User enters VK group URL/ID
    enter_token = State()  # User pastes community API token or personal OAuth URL


def _vk_type_selector_kb(
    project_id: int,
    *,
    exclude_group: bool = False,
    exclude_personal: bool = False,
) -> InlineKeyboardMarkup:
    """Build VK type selector keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    if not exclude_group:
        rows.append([InlineKeyboardButton(text="Группа", callback_data=f"conn:{project_id}:vk:group")])
    if not exclude_personal:
        rows.append([InlineKeyboardButton(
            text="Личная страница",
            callback_data=f"conn:{project_id}:vk:personal",
        )])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:vk_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
    """Start VK connection -- show type selector (group / personal)."""
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

    # Check existing VK connections -- allow group + personal
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

    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await msg.answer(S.FSM_INTERRUPTED.format(name=interrupted))

    await state.set_state(ConnectVKFSM.select_type)
    await state.update_data(
        last_update_time=time.time(),
        connect_project_id=project_id,
        project_name=project.name,
    )

    await msg.answer(
        VK_TYPE_SELECT,
        reply_markup=_vk_type_selector_kb(
            project_id,
            exclude_group=has_group,
            exclude_personal=has_personal,
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    await callback.answer()


@router.callback_query(ConnectVKFSM.select_type, F.data.regexp(r"^conn:\d+:vk:(group|personal)$"))
async def vk_type_selected(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project_service_factory: ProjectServiceFactory,
) -> None:
    """Handle VK type selection: group or personal."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
    pid, vk_type = int(parts[1]), parts[3]

    project = await project_service_factory(db).get_owned_project(pid, user.id)
    if not project:
        await callback.answer(S.PROJECT_NOT_FOUND, show_alert=True)
        return

    await state.update_data(vk_type=vk_type, connect_project_id=pid)

    if vk_type == "group":
        await state.set_state(ConnectVKFSM.enter_group_url)
        await msg.answer(
            VK_STEP1_GROUP_URL,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{pid}:vk_cancel")],
                ]
            ),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    else:
        # Personal page: skip group URL, go straight to OAuth
        await state.set_state(ConnectVKFSM.enter_token)
        await msg.answer(
            VK_PERSONAL_AUTH,
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Авторизоваться", url=_VK_AUTH_URL)],
                    [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{pid}:vk_cancel")],
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
    if text == "\u041e\u0442\u043c\u0435\u043d\u0430":
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    group_id, screen_name = parse_vk_group_input(text)
    if group_id is None and screen_name is None:
        await message.answer(
            S.POST_CONNECTION_VK_PARSE_ERROR,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
        return

    data = await state.get_data()
    project_id = int(data["connect_project_id"])

    # Re-validate project ownership
    project = await project_service_factory(db).get_owned_project(project_id, user.id)
    if not project:
        await state.clear()
        await message.answer(S.PROJECT_NOT_FOUND, reply_markup=menu_kb())
        return

    from bot.config import get_settings

    settings = get_settings()

    vk_svc = VKOAuthService(
        http_client=http_client,
        redis=redis,
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=settings.vk_app_id,
        vk_app_secret=settings.vk_secure_key.get_secret_value(),
        redirect_uri="",
        vk_service_key=settings.vk_service_key.get_secret_value(),
    )

    # Resolve group: either by numeric ID or screen_name
    resolve_input = str(group_id) if group_id else screen_name
    try:
        resolved_id, group_name = await vk_svc.resolve_group(resolve_input or "")
    except VKOAuthError as exc:
        await message.answer(exc.user_message)
        return

    await state.set_state(ConnectVKFSM.enter_token)
    await state.update_data(
        vk_group_id=resolved_id,
        vk_group_name=group_name or f"Группа {resolved_id}",
    )

    safe_name = html.escape(group_name or f"Группа {resolved_id}")
    await message.answer(
        VK_STEP2_AUTH.format(group_name=safe_name),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Авторизоваться", url=_VK_AUTH_URL)],
                [InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:vk_cancel")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ---------------------------------------------------------------------------
# VK: extract token from OAuth redirect URL
# ---------------------------------------------------------------------------


def _extract_vk_token(text: str) -> str | None:
    """Extract access_token from VK OAuth redirect URL or raw token string.

    Accepts:
    - Full URL: https://oauth.vk.com/blank.html#access_token=abc123&expires_in=0&user_id=456
    - Raw token: abc123def456...
    """
    # Try to extract from URL fragment
    match = re.search(r"access_token=([a-zA-Z0-9._-]+)", text)
    if match:
        return match.group(1)

    # Fallback: raw token (long alphanumeric string)
    cleaned = text.strip()
    if len(cleaned) >= 20 and re.fullmatch(r"[a-zA-Z0-9._-]+", cleaned):
        return cleaned

    return None


@router.message(ConnectVKFSM.enter_token, F.text)
async def vk_process_token(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """VK: parse OAuth redirect URL or raw token and create connection."""
    text = (message.text or "").strip()
    if text in ("\u041e\u0442\u043c\u0435\u043d\u0430", "/cancel"):
        await state.clear()
        await message.answer(S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
        return

    # Extract access_token from OAuth redirect URL or raw token
    token = _extract_vk_token(text)
    if not token:
        await message.answer(
            "Не удалось извлечь токен.\n\n"
            "Скопируйте <b>всю ссылку</b> из адресной строки\n"
            "после нажатия \u00abРазрешить\u00bb.\n\n"
            "<i>Она начинается с:\n"
            "https://oauth.vk.com/blank.html#access_token=...</i>",
        )
        return

    data = await state.get_data()
    project_id = int(data["connect_project_id"])
    vk_type = data.get("vk_type", "group")

    if vk_type == "personal":
        # Personal page: validate via users.get
        try:
            resp = await http_client.post(
                "https://api.vk.ru/method/users.get",
                data={"access_token": token, "v": "5.199"},
                timeout=10,
            )
            result = resp.json()
            if "error" in result:
                err = result["error"].get("error_msg", "")
                await message.answer(
                    f"Ошибка проверки токена: {err}\n\n"
                    "Попробуйте авторизоваться заново\n"
                    "и скопировать ссылку целиком.",
                )
                return
            vk_user = result["response"][0]
            user_vk_id = str(vk_user["id"])
            user_name = f"{vk_user.get('first_name', '')} {vk_user.get('last_name', '')}".strip()
        except httpx.HTTPError:
            await message.answer("Не удалось связаться с VK.\nПопробуйте позже.")
            return

        # Delete message with token for security
        with contextlib.suppress(Exception):
            await message.delete()

        conn_svc = ConnectionService(db, http_client)
        identifier = f"id{user_vk_id}"

        # Check personal page not already connected
        existing_vk = await conn_svc.get_by_project_and_platform(project_id, "vk")
        if any((getattr(c, "credentials", None) or {}).get("target") == "personal" for c in existing_vk):
            await message.answer(S.VK_PERSONAL_ALREADY)
            return

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

        await state.clear()
        log.info("vk_personal_connected", conn_id=conn.id, project_id=project_id, user_vk_id=user_vk_id)

        connections = await conn_svc.get_by_project(project_id)
        safe_user = html.escape(user_name)
        proj_name = html.escape(data.get("project_name", ""))
        await message.answer(
            f"\u2705 {S.VK_PERSONAL_CONNECTED}\n"
            f"{safe_user} ({identifier})\n\n"
            f"<b>{proj_name}</b> \u2014 Подключения",
            reply_markup=connection_list_kb(connections, project_id),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    else:
        # Group flow (existing behavior)
        group_id = data.get("vk_group_id")
        group_name = data.get("vk_group_name", "")

        # Validate token by calling groups.getById
        try:
            resp = await http_client.post(
                "https://api.vk.ru/method/groups.getById",
                data={
                    "access_token": token,
                    "group_id": str(group_id),
                    "v": "5.199",
                },
                timeout=10,
            )
            result = resp.json()
            if "error" in result:
                err = result["error"].get("error_msg", "")
                await message.answer(
                    f"Ошибка проверки токена: {err}\n\n"
                    "Попробуйте авторизоваться заново\n"
                    "и скопировать ссылку целиком.",
                )
                return
        except httpx.HTTPError:
            await message.answer("Не удалось связаться с VK.\nПопробуйте позже.")
            return

        # Delete message with token for security
        with contextlib.suppress(Exception):
            await message.delete()

        # Create connection
        conn_svc = ConnectionService(db, http_client)
        identifier = f"club{group_id}"
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
                "expires_at": "",
            },
        )

        await state.clear()
        log.info("vk_connected_via_token", conn_id=conn.id, project_id=project_id, group_id=group_id)

        connections = await conn_svc.get_by_project(project_id)
        safe_name = html.escape(group_name)
        proj_name = html.escape(data.get("project_name", ""))
        await message.answer(
            f"\u2705 VK-группа \u00ab{safe_name}\u00bb подключена!\n\n"
            f"<b>{proj_name}</b> \u2014 Подключения",
            reply_markup=connection_list_kb(connections, project_id),
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )


# ---------------------------------------------------------------------------
# Cancel handler
# ---------------------------------------------------------------------------


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
    """Cancel VK connection via inline button -- also cleans up VK OAuth Redis keys."""
    await _cancel_connection_wizard(callback, state, user, db, http_client, project_service_factory, redis)
