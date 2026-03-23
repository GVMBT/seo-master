"""OAuth deep-link handlers for Pinterest and VK.

Extracted from start.py — handles /start deep-links for OAuth flows
and VK group selection callback.
"""

import html
import json
from typing import Any

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.config import get_settings
from bot.helpers import safe_message
from bot.texts import strings as S
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnectionCreate, Project, User
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import connection_list_kb, connection_manage_kb, menu_kb
from services.connections import ConnectionService
from services.oauth.vk import VKDeepLinkResult, VKOAuthService

log = structlog.get_logger()
oauth_router = Router(name="oauth_deeplinks")


# ---------------------------------------------------------------------------
# Pinterest OAuth deep-link handler
# ---------------------------------------------------------------------------


async def _handle_pinterest_deep_link(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    nonce: str,
) -> None:
    """Handle Pinterest OAuth deep-link -- read tokens, create connection.

    Called when user returns from Pinterest OAuth via deep-link
    /start pinterest_auth_{nonce}.  Tokens are in pinterest_auth:{nonce}
    (written by auth_service), metadata in pinterest_oauth:{nonce}
    (written by toolbox or pipeline connection wizard).
    """
    tokens_raw = await redis.get(CacheKeys.pinterest_auth(nonce))
    if not tokens_raw:
        log.warning("pinterest_deep_link_no_tokens", nonce=nonce, user_id=user.id)
        await message.answer(S.OAUTH_EXPIRED, reply_markup=menu_kb())
        return

    meta_raw = await redis.get(CacheKeys.pinterest_oauth(nonce))
    if not meta_raw:
        log.warning("pinterest_deep_link_no_meta", nonce=nonce, user_id=user.id)
        await message.answer(S.OAUTH_SESSION_MISSING, reply_markup=menu_kb())
        return

    try:
        tokens = json.loads(tokens_raw)
    except (json.JSONDecodeError, TypeError):  # fmt: skip
        log.warning("pinterest_deep_link_invalid_tokens", nonce=nonce)
        return

    # Parse metadata -- toolbox stores plain project_id, pipeline stores JSON dict
    project_id: int | None = None
    from_pipeline = False
    try:
        meta = json.loads(meta_raw)
        project_id = int(meta["project_id"]) if isinstance(meta, dict) else int(meta)
        from_pipeline = isinstance(meta, dict) and meta.get("from_pipeline") is True
    except (json.JSONDecodeError, ValueError, TypeError, KeyError):  # fmt: skip
        try:
            project_id = int(meta_raw)
        except (ValueError, TypeError):  # fmt: skip
            log.warning("pinterest_deep_link_invalid_meta", nonce=nonce)
            await message.answer(S.OAUTH_DATA_ERROR, reply_markup=menu_kb())
            return

    if not project_id:
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(project_id)
    if not project or project.user_id != user.id:
        log.warning("pinterest_deep_link_wrong_owner", project_id=project_id, user_id=user.id)
        await message.answer("Проект не найден.", reply_markup=menu_kb())
        return

    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn_repo = ConnectionsRepository(db, cm)

    try:
        conn = await conn_repo.create(
            PlatformConnectionCreate(
                project_id=project_id,
                platform_type="pinterest",
                identifier=f"pinterest_{user.id}_{project_id}",
                metadata={},
            ),
            raw_credentials={
                "access_token": tokens.get("access_token", ""),
                "refresh_token": tokens.get("refresh_token", ""),
                "expires_at": tokens.get("expires_at", ""),
            },
        )
    except Exception:
        log.exception("pinterest_create_connection_failed", project_id=project_id, user_id=user.id)
        await message.answer(S.OAUTH_CONN_EXISTS, reply_markup=menu_kb())
        return

    # Cleanup Redis keys
    await redis.delete(CacheKeys.pinterest_auth(nonce))
    await redis.delete(CacheKeys.pinterest_oauth(nonce))

    safe_name = html.escape(project.name)
    await message.answer(
        S.PINTEREST_CONNECTED.format(project_name=safe_name),
        reply_markup=connection_manage_kb(conn.id, project_id),
    )
    log.info(
        "pinterest_connected_via_deeplink",
        connection_id=conn.id,
        project_id=project_id,
        user_id=user.id,
    )

    if from_pipeline:
        await _return_to_pipeline(message, state, user, db, redis, http_client, project)


# ---------------------------------------------------------------------------
# VK OAuth deep-link handler (thin -- delegates to VKOAuthService + ConnectionService)
# ---------------------------------------------------------------------------


def _build_vk_oauth_service(
    http_client: httpx.AsyncClient,
    redis: RedisClient,
) -> VKOAuthService:
    """Build VKOAuthService from settings."""
    settings = get_settings()
    base_url = (settings.railway_public_url or "").rstrip("/")
    redirect_uri = f"{base_url}/api/auth/vk/callback"
    return VKOAuthService(
        http_client=http_client,
        redis=redis,
        encryption_key=settings.encryption_key.get_secret_value(),
        vk_app_id=settings.vk_app_id,
        vk_app_secret=settings.vk_secure_key.get_secret_value(),
        redirect_uri=redirect_uri,
        vk_service_key=settings.vk_service_key.get_secret_value(),
    )


async def _handle_vk_deep_link(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    nonce: str,
) -> None:
    """Handle VK OAuth deep-link -- community token flow.

    Primary flow: dl.step="community" -> create connection with community token.
    Legacy flow: dl.step="groups" -> show group picker (kept for backward compat).
    """
    vk_svc = _build_vk_oauth_service(http_client, redis)
    dl: VKDeepLinkResult | None = await vk_svc.process_deep_link(nonce)

    if not dl:
        log.warning("vk_deep_link_no_result", nonce=nonce, user_id=user.id)
        await message.answer(S.OAUTH_EXPIRED, reply_markup=menu_kb())
        return

    if not dl.project_id:
        await message.answer(S.OAUTH_SESSION_MISSING, reply_markup=menu_kb())
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(dl.project_id)
    if not project or project.user_id != user.id:
        log.warning("vk_deep_link_wrong_owner", project_id=dl.project_id, user_id=user.id)
        await vk_svc.cleanup_meta(nonce)
        await message.answer("Проект не найден.", reply_markup=menu_kb())
        return

    if dl.step == "community":
        # Community token ready -- create connection
        await _create_vk_connection_from_community(
            message,
            user,
            db,
            http_client,
            project,
            dl,
        )
        await vk_svc.cleanup(nonce)
        if dl.from_pipeline:
            await _return_to_pipeline(message, state, user, db, redis, http_client, project)
        return

    # Legacy: step 1 group picker (VK ID OAuth -- kept for backward compat)
    if not dl.groups:
        await vk_svc.cleanup_meta(nonce)
        await message.answer(S.VK_NO_GROUPS, reply_markup=menu_kb())
        return

    await vk_svc.restore_result_for_group_select(nonce, dl.raw_result)
    await _show_vk_group_picker(message, project, dl.groups, nonce)


async def _show_vk_group_picker(
    message: Message,
    project: Project,
    groups: list[dict[str, Any]],
    nonce: str,
) -> None:
    """Show group selection keyboard for multi-group VK OAuth flow."""
    buttons = [
        [
            InlineKeyboardButton(
                text=html.escape(g.get("name", f"Группа {g['id']}"))[:40],
                callback_data=f"vk_auth:{nonce}:{g['id']}",
            )
        ]
        for g in groups[:10]
    ]
    buttons.append([InlineKeyboardButton(text="Отмена", callback_data="nav:dashboard")])

    await message.answer(
        f"{S.VK_GROUP_PICK}\n\nПроект: \u00ab{html.escape(project.name)}\u00bb",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


async def _create_vk_connection_from_community(
    message: Message,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    project: Project,
    dl: VKDeepLinkResult,
) -> None:
    """Create VK connection from community token (step 2 result)."""
    if not dl.group_id:
        log.error("vk_community_missing_group_id", project_id=project.id)
        await message.answer(S.VK_GROUP_NO_ID, reply_markup=menu_kb())
        return
    group_id = str(dl.group_id)
    group_name = dl.group_name or f"Группа {group_id}"
    conn_svc = ConnectionService(db, http_client)

    try:
        conn = await conn_svc.create_vk_from_oauth(
            project_id=project.id,
            group_id=group_id,
            group_name=group_name,
            access_token=dl.access_token,
            expires_at=dl.expires_at,
        )
    except Exception:
        log.exception("vk_create_connection_failed", project_id=project.id, user_id=user.id)
        await message.answer(S.OAUTH_CONN_EXISTS, reply_markup=menu_kb())
        return

    # Show connections list (same as WP/TG success)
    connections = await conn_svc.get_by_project(project.id)
    safe_name = html.escape(project.name)
    await message.answer(
        f"{S.VK_GROUP_CONNECTED.format(group_name=html.escape(group_name))}\n\n<b>{safe_name}</b> \u2014 Подключения",
        reply_markup=connection_list_kb(connections, project.id),
    )
    log.info(
        "vk_connected_via_deeplink",
        connection_id=conn.id,
        project_id=project.id,
        group_id=group_id,
        user_id=user.id,
    )


# ---------------------------------------------------------------------------
# VK group selection callback (from deep-link multi-group flow)
# ---------------------------------------------------------------------------


@oauth_router.callback_query(F.data.regexp(r"^vk_auth:[^:]+:\d+$"))
async def vk_group_select_deeplink(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Handle VK group selection -- trigger step 2 OAuth with group_ids.

    After user picks a group from step 1, we send them to VK again
    with group_ids=ID to get a community token (not user token).
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return
    parts = callback.data.split(":")
    nonce = parts[1]
    group_id = int(parts[2])

    vk_svc = _build_vk_oauth_service(http_client, redis)

    # Read stored step-1 result (groups list)
    result = await vk_svc.get_stored_result(nonce)
    if not result:
        await callback.answer("Сессия авторизации истекла.", show_alert=True)
        return

    groups: list[dict[str, Any]] = result.get("groups") or []
    group = next((g for g in groups if g["id"] == group_id), None)
    if not group:
        await callback.answer("Группа не найдена.", show_alert=True)
        return

    group_name = group.get("name", f"Группа {group_id}")

    # Generate new nonce for step 2 OAuth
    new_nonce = vk_svc.generate_nonce()

    # Copy meta from old nonce to new nonce (project_id, from_pipeline)
    meta = await vk_svc.get_meta(nonce)
    if meta:
        await vk_svc.store_meta(new_nonce, int(meta["project_id"]), extra=meta)

    # Store step-2 auth session with group info
    await vk_svc.store_auth(
        new_nonce,
        user.id,
        step="community",
        group_id=group_id,
        group_name=group_name,
    )

    # Build step-2 OAuth URL with group_ids (goes through /api/auth/vk redirect)
    oauth_url = vk_svc.build_oauth_url(user.id, new_nonce, group_ids=group_id)

    # Cleanup old nonce data
    await vk_svc.cleanup(nonce)

    await msg.answer(
        S.VK_GROUP_ACCESS_PROMPT.format(group_name=html.escape(group_name)),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="Подтвердить доступ к группе", url=oauth_url)],
                [InlineKeyboardButton(text="Отмена", callback_data="nav:dashboard")],
            ]
        ),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Return to social pipeline after OAuth (P0: pipeline return)
# ---------------------------------------------------------------------------


async def _return_to_pipeline(
    message: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    project: Project,
) -> None:
    """Return user to social pipeline connection step after OAuth.

    After VK/Pinterest OAuth completes, the user should land back at the
    social pipeline connection screen instead of Dashboard (FSM_SPEC.md:419-423,
    UX_PIPELINE.md:416).  Re-uses _show_connection_step_msg which handles
    0/1/N connections and auto-transitions to category step.
    """
    from routers.publishing.pipeline.social.connection import _show_connection_step_msg

    await state.update_data(project_id=project.id, project_name=project.name)
    await _show_connection_step_msg(
        message,
        state,
        user,
        db,
        redis,
        project.id,
        project.name,
        http_client=http_client,
    )
