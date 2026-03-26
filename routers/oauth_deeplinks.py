"""OAuth deep-link handlers for Pinterest and VK.

Extracted from start.py — handles /start deep-links for OAuth flows
and VK group selection callback.
"""

import html
import json

import httpx
import structlog
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.config import get_settings
from bot.texts import strings as S
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnectionCreate, Project, User
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import connection_manage_kb, menu_kb

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
