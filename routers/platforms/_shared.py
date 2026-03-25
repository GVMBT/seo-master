"""Shared constants, helpers, and CRUD handlers for platform connections."""

import asyncio
import html
from collections.abc import Sequence

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.assets import edit_screen
from bot.helpers import safe_callback_data, safe_edit_text, safe_message
from bot.service_factory import ProjectServiceFactory
from bot.texts import strings as S
from bot.texts.emoji import E
from bot.texts.screens import Screen
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.models import User
from db.repositories.publications import PublicationsRepository
from keyboards.inline import (
    connection_delete_confirm_kb,
    connection_list_kb,
    connection_manage_kb,
    menu_kb,
)
from services.analysis import SiteAnalysisService
from services.connections import ConnectionService
from services.external.firecrawl import FirecrawlClient
from services.external.pagespeed import PageSpeedClient
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


def _build_platform_url(platform_type: str, identifier: str) -> str | None:
    """Build clickable URL for a platform connection."""
    ident = identifier.strip()
    if platform_type == "wordpress":
        proto = "" if ident.startswith(("http://", "https://")) else "https://"
        return f"{proto}{ident}"
    if platform_type == "vk":
        # identifier is like "club141149920", "id12345", or numeric group ID
        slug = ident if ident.startswith(("club", "id", "public")) else f"club{ident}"
        return f"https://vk.com/{slug}"
    if platform_type == "telegram":
        # identifier is like "@channel" or "-100..." or "t.me/channel"
        clean = ident.lstrip("@")
        if clean.startswith("-100"):
            return None  # private channel ID -- no public URL
        return f"https://t.me/{clean}"
    if platform_type == "pinterest":
        return f"https://pinterest.com/{ident}"
    return None


def _build_connections_text(
    project_name: str,
    connections: Sequence[object],
) -> str:
    """Build unified connections screen text grouped by platform."""
    safe_name = html.escape(project_name)

    s = Screen(E.GEAR, S.CONNECTIONS_TITLE)
    s.blank()
    s.line(f"Проект: {safe_name}")
    s.blank()

    if not connections:
        s.line(S.CONNECTIONS_EMPTY)
        s.hint(S.CONNECTIONS_HINT)
        return s.build()

    # Group connections by platform_type: list of (identifier, group_name|None)
    grouped: dict[str, list[tuple[str, str | None]]] = {}
    for conn in connections:
        pt = getattr(conn, "platform_type", "unknown")
        identifier = html.escape(getattr(conn, "identifier", ""))
        meta = getattr(conn, "metadata", None) or {}
        gn = meta.get("group_name") if isinstance(meta, dict) else None
        grouped.setdefault(pt, []).append((identifier, gn))

    platform_order = ["wordpress", "telegram", "vk", "pinterest"]
    for pt in platform_order:
        items = grouped.pop(pt, None)
        if not items:
            continue
        icon = _PLAT_EMOJI.get(pt, "")
        label = _PLAT_LABEL.get(pt, pt.capitalize())
        s.line(f"{icon} {label} ({len(items)}):")
        for i, (ident, gn) in enumerate(items, 1):
            url = _build_platform_url(pt, ident)
            linked = f'<a href="{url}">{ident}</a>' if url else ident
            display = f"{html.escape(gn)} ({linked})" if gn else linked
            s.line(f"  {i}. {display}")
        s.blank()

    # Remaining unknown platforms (if any)
    for pt, items in grouped.items():
        s.line(f"{pt.capitalize()} ({len(items)}):")
        for i, (ident, _gn) in enumerate(items, 1):
            s.line(f"  {i}. {ident}")
        s.blank()

    s.hint(S.CONNECTIONS_HINT)
    return s.build()


async def _run_site_analysis(
    db: SupabaseClient,
    firecrawl: FirecrawlClient,
    pagespeed: PageSpeedClient,
    project_id: int,
    site_url: str,
    connection_id: int,
    encryption_key: str,
) -> None:
    """Fire-and-forget site analysis wrapper (PRD 7.1).

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
    cb_data = safe_callback_data(callback)
    parts = cb_data.split(":")
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

    await safe_edit_text(msg, S.CONNECTIONS_CANCELLED, reply_markup=menu_kb())
    await callback.answer()


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

    cb_data = safe_callback_data(callback)
    project_id = int(cb_data.split(":")[1])
    project = await project_service_factory(db).get_owned_project(project_id, user.id)

    if not project:
        await callback.answer(S.PROJECT_NOT_FOUND, show_alert=True)
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

    cb_data = safe_callback_data(callback)
    project_id = int(cb_data.split(":")[1])
    project = await project_service_factory(db).get_owned_project(project_id, user.id)

    if not project:
        await callback.answer(S.PROJECT_NOT_FOUND, show_alert=True)
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

    cb_data = safe_callback_data(callback)
    conn_id = int(cb_data.split(":")[1])
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if not conn:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
        return

    project = await project_service_factory(db).get_owned_project(conn.project_id, user.id)
    if not project:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
        return

    icon = _PLAT_EMOJI.get(conn.platform_type, "")
    plat_name = S.PLATFORM_DISPLAY.get(conn.platform_type, conn.platform_type).upper()
    status_icon = E.CHECK if conn.status == "active" else E.WARNING
    status_text = S.CONNECTIONS_STATUS_ACTIVE if conn.status == "active" else S.CONNECTIONS_STATUS_ERROR
    safe_id = html.escape(conn.identifier)
    created_str = conn.created_at.strftime("%d.%m.%Y") if conn.created_at else "---"
    metadata = conn.metadata or {}
    group_name = metadata.get("group_name") if isinstance(metadata, dict) else None

    pub_repo = PublicationsRepository(db)
    pub_count = await pub_repo.get_count_by_connection(conn_id)

    # Build clickable URL for the connection
    url = _build_platform_url(conn.platform_type, conn.identifier)
    id_line = f'<a href="{url}">{safe_id}</a>' if url else safe_id

    s = Screen(icon, plat_name)
    s.blank()
    if group_name:
        s.line(f"<b>{html.escape(group_name)}</b>")
    s.line(id_line)
    s.blank()
    s.line(f"{status_icon} {status_text} \u00b7 {created_str}")
    s.field(E.ANALYTICS, "Публикаций", pub_count)
    s.hint(S.CONNECTIONS_MANAGE_HINT)
    text = s.build()
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

    cb_data = safe_callback_data(callback)
    conn_id = int(cb_data.split(":")[1])
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if not conn:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
        return

    project = await project_service_factory(db).get_owned_project(conn.project_id, user.id)
    if not project:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
        return

    safe_id = html.escape(conn.identifier)
    icon = _PLAT_EMOJI.get(conn.platform_type, "")
    plat_name = S.PLATFORM_DISPLAY.get(conn.platform_type, conn.platform_type)
    metadata = conn.metadata or {}
    group_name = metadata.get("group_name") if isinstance(metadata, dict) else None
    conn_label = f"{html.escape(group_name)} ({safe_id})" if group_name else safe_id

    text = (
        Screen(E.WARNING, S.CONNECTIONS_DELETE_TITLE)
        .blank()
        .line(f"{icon} {plat_name} \u2014 {conn_label}")
        .blank()
        .line(f"{S.CONNECTIONS_DELETE_LIST_HEADER}")
        .line(f"\u2022 {S.CONNECTIONS_DELETE_ITEMS[0]}")
        .line(f"\u2022 {S.CONNECTIONS_DELETE_ITEMS[1]}")
        .hint(S.CONNECTIONS_DELETE_WARNING)
        .build()
    )
    await safe_edit_text(
        msg,
        text,
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

    cb_data = safe_callback_data(callback)
    conn_id = int(cb_data.split(":")[1])
    conn_svc = ConnectionService(db, http_client)
    conn = await conn_svc.get_by_id(conn_id)
    if not conn:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
        return

    project = await project_service_factory(db).get_owned_project(conn.project_id, user.id)
    if not project:
        await callback.answer(S.CONNECTIONS_NOT_FOUND, show_alert=True)
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
        del_msg = S.CONN_DELETE_SUCCESS.format(
            platform=_PLAT_LABEL.get(conn.platform_type, conn.platform_type.capitalize()),
            identifier=safe_id,
        )
        await safe_edit_text(msg,
            f"{E.CHECK} {del_msg}\n\n{text}",
            reply_markup=connection_list_kb(connections, project_id),
        )
        log.info("connection_deleted", conn_id=conn_id, user_id=user.id)
    else:
        await safe_edit_text(msg, f"{E.WARNING} {S.CONN_DELETE_ERROR}", reply_markup=menu_kb())

    await callback.answer()
