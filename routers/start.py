"""Dashboard, /start, /cancel, navigation callbacks, reply text dispatch."""

import contextlib
import html
import json
from typing import Any

import httpx
import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove

from bot.assets import asset_photo, cache_file_id, edit_screen
from bot.config import get_settings
from bot.fsm_utils import ensure_no_active_fsm
from bot.helpers import safe_edit_text, safe_message
from bot.service_factory import DashboardServiceFactory
from bot.texts.legal import LEGAL_NOTICE
from cache.client import RedisClient
from cache.keys import CacheKeys
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnectionCreate, Project, User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.previews import PreviewsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.inline import (
    cancel_kb,
    connection_list_kb,
    connection_manage_kb,
    consent_kb,
    dashboard_kb,
    dashboard_resume_kb,
    menu_kb,
)
from keyboards.pipeline import (
    pipeline_categories_kb,
    pipeline_no_projects_kb,
    pipeline_no_wp_kb,
    pipeline_preview_kb,
    pipeline_projects_kb,
)
from routers.publishing.pipeline._common import ArticlePipelineFSM
from services.connections import ConnectionService
from services.dashboard import DashboardService
from services.oauth.vk import VKDeepLinkResult, VKOAuthService
from services.users import UsersService

log = structlog.get_logger()
router = Router()


def _parse_referrer_id(arg: str) -> int | None:
    """Extract numeric referrer_id from deep link arg like 'referrer_12345'."""
    raw = arg.removeprefix("referrer_")
    try:
        return int(raw)
    except (ValueError, TypeError):
        log.warning("referral_invalid_arg", arg=arg)
        return None


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
    """Handle Pinterest OAuth deep-link — read tokens, create connection.

    Called when user returns from Pinterest OAuth via deep-link
    /start pinterest_auth_{nonce}.  Tokens are in pinterest_auth:{nonce}
    (written by auth_service), metadata in pinterest_oauth:{nonce}
    (written by toolbox or pipeline connection wizard).
    """
    tokens_raw = await redis.get(CacheKeys.pinterest_auth(nonce))
    if not tokens_raw:
        log.warning("pinterest_deep_link_no_tokens", nonce=nonce, user_id=user.id)
        await message.answer(
            "Авторизация Pinterest не найдена или истекла. Попробуйте ещё раз.", reply_markup=menu_kb()
        )
        return

    meta_raw = await redis.get(CacheKeys.pinterest_oauth(nonce))
    if not meta_raw:
        log.warning("pinterest_deep_link_no_meta", nonce=nonce, user_id=user.id)
        await message.answer("Данные сессии Pinterest не найдены. Попробуйте ещё раз.", reply_markup=menu_kb())
        return

    try:
        tokens = json.loads(tokens_raw)
    except (json.JSONDecodeError, TypeError):  # fmt: skip
        log.warning("pinterest_deep_link_invalid_tokens", nonce=nonce)
        return

    # Parse metadata — toolbox stores plain project_id, pipeline stores JSON dict
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
            await message.answer("Ошибка данных Pinterest. Попробуйте ещё раз.", reply_markup=menu_kb())
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
        await message.answer(
            "Не удалось создать подключение Pinterest. Возможно, оно уже существует.", reply_markup=menu_kb()
        )
        return

    # Cleanup Redis keys
    await redis.delete(CacheKeys.pinterest_auth(nonce))
    await redis.delete(CacheKeys.pinterest_oauth(nonce))

    safe_name = html.escape(project.name)
    await message.answer(
        f"Pinterest подключён к проекту «{safe_name}»!",
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
# VK OAuth deep-link handler (thin — delegates to VKOAuthService + ConnectionService)
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
    """Handle VK OAuth deep-link — community token flow.

    Primary flow: dl.step="community" → create connection with community token.
    Legacy flow: dl.step="groups" → show group picker (kept for backward compat).
    """
    vk_svc = _build_vk_oauth_service(http_client, redis)
    dl: VKDeepLinkResult | None = await vk_svc.process_deep_link(nonce)

    if not dl:
        log.warning("vk_deep_link_no_result", nonce=nonce, user_id=user.id)
        await message.answer(
            "Авторизация VK не найдена или истекла. Попробуйте ещё раз.",
            reply_markup=menu_kb(),
        )
        return

    if not dl.project_id:
        await message.answer(
            "Данные сессии VK не найдены. Попробуйте подключить VK заново.",
            reply_markup=menu_kb(),
        )
        return

    projects_repo = ProjectsRepository(db)
    project = await projects_repo.get_by_id(dl.project_id)
    if not project or project.user_id != user.id:
        log.warning("vk_deep_link_wrong_owner", project_id=dl.project_id, user_id=user.id)
        await vk_svc.cleanup_meta(nonce)
        await message.answer("Проект не найден.", reply_markup=menu_kb())
        return

    if dl.step == "community":
        # Community token ready — create connection
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

    # Legacy: step 1 group picker (VK ID OAuth — kept for backward compat)
    if not dl.groups:
        await vk_svc.cleanup_meta(nonce)
        await message.answer(
            "У вас нет групп VK, в которых вы администратор или редактор.",
            reply_markup=menu_kb(),
        )
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
        f"VK-авторизация успешна!\n\nВыберите группу для подключения к проекту «{html.escape(project.name)}»:",
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
        await message.answer(
            "Ошибка: не указан ID группы. Попробуйте подключить VK заново.",
            reply_markup=menu_kb(),
        )
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
        await message.answer(
            "Не удалось создать подключение VK. Возможно, оно уже существует.",
            reply_markup=menu_kb(),
        )
        return

    # Show connections list (same as WP/TG success)
    connections = await conn_svc.get_by_project(project.id)
    safe_name = html.escape(project.name)
    await message.answer(
        f"VK-группа «{html.escape(group_name)}» подключена!\n\n<b>{safe_name}</b> — Подключения",
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


@router.callback_query(F.data.regexp(r"^vk_auth:[^:]+:\d+$"))
async def vk_group_select_deeplink(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Handle VK group selection — trigger step 2 OAuth with group_ids.

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
        f"Отлично! Теперь нужно дать доступ к группе «{html.escape(group_name)}».\n\n"
        "Нажмите кнопку ниже — VK попросит подтвердить права на публикацию.",
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


# ---------------------------------------------------------------------------
# Dashboard builder
# ---------------------------------------------------------------------------


async def _build_dashboard(
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build Dashboard text + keyboard based on user state."""
    dash_svc = dashboard_service_factory(db)
    data = await dash_svc.get_dashboard_data(user.id)

    text = DashboardService.build_text(user.first_name or "", user.balance, is_new_user, data)

    # Check pipeline checkpoint (section 2.6)
    checkpoint_text = await _get_checkpoint_text(redis, user.id)

    kb = dashboard_kb(is_admin=user.role == "admin")

    if checkpoint_text:
        text += checkpoint_text
        return text, dashboard_resume_kb()

    return text, kb


async def _get_checkpoint_text(redis: RedisClient, user_id: int) -> str:
    """Get pipeline checkpoint resume text, or empty string."""
    checkpoint_raw = await redis.get(CacheKeys.pipeline_state(user_id))
    if not checkpoint_raw:
        return ""
    try:
        checkpoint = json.loads(checkpoint_raw)
        project_name = html.escape(checkpoint.get("project_name") or "")
        step = checkpoint.get("step_label", "подготовка")
        pipeline_type = checkpoint.get("pipeline_type", "article")
        label = "статья" if pipeline_type == "article" else "пост"
        return (
            f"\n\n\u23f3 У вас есть незавершённый {label}:\n\U0001f4c1 Проект: {project_name}\nОстановились на: {step}"
        )
    except (json.JSONDecodeError, TypeError):  # fmt: skip
        return ""


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Handle /start command — show Dashboard."""
    # Parse deep link args BEFORE clearing FSM — OAuth deep-links need
    # the active pipeline FSM state to survive (P0: pipeline return).
    args = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""

    # OAuth deep-links: handle without clearing FSM and return early
    if args == "pinterest_error":
        await message.answer(
            "Не удалось подключить Pinterest.\nАвторизация была отклонена или произошла ошибка.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="Попробовать снова", callback_data="nav:projects")],
                    [InlineKeyboardButton(text="На главную", callback_data="nav:dashboard")],
                ]
            ),
        )
        return
    if args.startswith("pinterest_auth_"):
        nonce = args.removeprefix("pinterest_auth_")
        await _handle_pinterest_deep_link(message, state, user, db, redis, http_client, nonce)
        return
    if args.startswith("vk_auth_"):
        nonce = args.removeprefix("vk_auth_")
        await _handle_vk_deep_link(message, state, user, db, redis, http_client, nonce)
        return

    # For all other cases: clear FSM as before
    await ensure_no_active_fsm(state)

    if args.startswith("referrer_"):
        referrer_id = _parse_referrer_id(args)
        if is_new_user and referrer_id:
            users_svc = UsersService(db)
            await users_svc.link_referrer(user.id, referrer_id, redis)
        else:
            log.info("deep_link_referral_ignored", referrer_arg=args, is_new_user=is_new_user)

    # Consent gate: must accept terms before accessing dashboard (C7/H30)
    if user.accepted_terms_at is None:
        await message.answer(LEGAL_NOTICE, reply_markup=consent_kb())
        return

    # Remove any lingering reply keyboard (from old bot versions or other bots)
    with contextlib.suppress(Exception):
        remove_msg = await message.answer(".", reply_markup=ReplyKeyboardRemove())
        await remove_msg.delete()

    text, kb = await _build_dashboard(user, is_new_user, db, redis, dashboard_service_factory)
    full_text = text + "\n\nВыберите действие:"
    result = await message.answer_photo(
        asset_photo("welcome.png"),
        caption=full_text,
        reply_markup=kb,
    )
    if result.photo:
        cache_file_id("welcome.png", result.photo[-1].file_id)


# ---------------------------------------------------------------------------
# Consent flow (C7/H30)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "legal:consent:accept")
async def consent_accept(
    callback: CallbackQuery,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Accept terms -> save timestamp -> show dashboard."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    try:
        # Save consent + invalidate cache via service layer (CR-109)
        users_svc = UsersService(db)
        await users_svc.accept_terms(user.id, redis)

        # Show dashboard (admin button included in inline kb via user.role check)
        text, kb = await _build_dashboard(user, is_new_user, db, redis, dashboard_service_factory)
        await msg.answer(
            "Условия приняты!\n\n" + text + "\n\nВыберите действие:",
            reply_markup=kb,
        )
    except Exception:
        log.exception("consent_accept_failed", user_id=user.id)
        await callback.answer(
            "Не удалось сохранить. Нажмите \u00abПринимаю\u00bb ещё раз.",
            show_alert=True,
        )
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# /cancel command
# ---------------------------------------------------------------------------


@router.message(Command("cancel"))
async def cmd_cancel(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Handle /cancel — clear FSM + show Dashboard."""
    interrupted = await ensure_no_active_fsm(state)
    if interrupted:
        await message.answer(f"{interrupted} \u2014 отменено.")

    text, kb = await _build_dashboard(user, is_new_user, db, redis, dashboard_service_factory)
    await message.answer(text, reply_markup=kb)


# ---------------------------------------------------------------------------
# Navigation callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "nav:dashboard")
async def nav_dashboard(
    callback: CallbackQuery,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Navigate to Dashboard via edit_screen (photo menu)."""
    text, kb = await _build_dashboard(user, is_new_user, db, redis, dashboard_service_factory)
    msg = safe_message(callback)
    if msg:
        await edit_screen(msg, "welcome.png", text, reply_markup=kb)
    await callback.answer()


## nav:projects is handled by routers/projects/list.py
## nav:profile is handled by routers/profile.py
## nav:tokens is handled by routers/tariffs.py


# ---------------------------------------------------------------------------
# Pipeline resume routing (E49)
# ---------------------------------------------------------------------------


async def _route_to_step(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
    *,
    step: str,
    project_id: int | None,
    project_name: str,
    category_id: int | None,
    connection_id: int | None,
    preview_id: int | None,
) -> None:
    """Route user to the correct pipeline screen based on checkpoint step."""
    msg = safe_message(callback)
    if not msg:
        return

    # Steps 1-3: re-run from selection screen
    if step in ("select_project", ""):
        projects_repo = ProjectsRepository(db)
        projects = await projects_repo.get_by_user(user.id)
        if not projects:
            await safe_edit_text(
                msg,
                "Статья (1/5) — Проект\n\nДля начала создадим проект — это 30 секунд.",
                reply_markup=pipeline_no_projects_kb(),
            )
        else:
            await safe_edit_text(
                msg,
                "Статья (1/5) — Проект\n\nДля какого проекта?",
                reply_markup=pipeline_projects_kb(projects),
            )
        await state.set_state(ArticlePipelineFSM.select_project)
        return

    if step == "select_wp":
        await safe_edit_text(
            msg,
            "Статья (2/5) — Сайт\n\nДля публикации нужен WordPress-сайт. Подключим?",
            reply_markup=pipeline_no_wp_kb(),
        )
        await state.set_state(ArticlePipelineFSM.select_wp)
        return

    if step == "select_category":
        if not project_id:
            await safe_edit_text(
                msg,
                "\u26a0\ufe0f Сессия устарела. Нажмите /start чтобы начать заново.",
                reply_markup=menu_kb(),
            )
            await redis.delete(CacheKeys.pipeline_state(user.id))
            await state.clear()
            return
        cats_repo = CategoriesRepository(db)
        categories = await cats_repo.get_by_project(project_id)
        if not categories:
            await safe_edit_text(
                msg,
                "Статья (3/5) — Тема\n\nО чём будет статья? Назовите тему.",
                reply_markup=cancel_kb("pipeline:article:cancel"),
            )
            await state.set_state(ArticlePipelineFSM.create_category_name)
        elif len(categories) == 1:
            cat = categories[0]
            await state.update_data(category_id=cat.id, category_name=cat.name)
            from routers.publishing.pipeline.readiness import show_readiness_check

            await show_readiness_check(callback, state, user, db, redis)
        else:
            await safe_edit_text(
                msg,
                "Статья (3/5) — Тема\n\nКакая тема?",
                reply_markup=pipeline_categories_kb(categories, project_id),
            )
            await state.set_state(ArticlePipelineFSM.select_category)
        return

    # Steps 4-5: readiness check or confirm
    if step in ("readiness_check", "confirm_cost"):
        from routers.publishing.pipeline.readiness import show_readiness_check

        await show_readiness_check(callback, state, user, db, redis)
        return

    # Steps 6-7: preview resume — load from DB
    if step == "preview" and preview_id:
        previews_repo = PreviewsRepository(db)
        preview = await previews_repo.get_by_id(preview_id)
        if preview and preview.user_id == user.id and preview.status == "draft":
            can_publish = bool(connection_id)
            kb = pipeline_preview_kb(
                preview.telegraph_url,
                can_publish=can_publish,
                regen_count=preview.regeneration_count,
                regen_cost=preview.tokens_charged or 0,
            )
            lines = [
                "Статья готова!\n",
                f"<b>{html.escape(preview.title or '')}</b>\n",
                f"Ключевая фраза: {html.escape(preview.keyword or '')}",
                f"Объём: ~{preview.word_count or 0} слов | Изображения: {preview.images_count or 0}",
                f"Списано: {preview.tokens_charged or 0} ток.",
            ]
            await safe_edit_text(msg, "\n".join(lines), reply_markup=kb)
            await state.set_state(ArticlePipelineFSM.preview)
            return

        # Preview expired or already published
        await safe_edit_text(
            msg,
            "\u26a0\ufe0f Превью устарело. Нажмите /start чтобы начать заново.",
            reply_markup=menu_kb(),
        )
        await redis.delete(CacheKeys.pipeline_state(user.id))
        return

    # Fallback: show dashboard
    log.warning("pipeline.resume_unknown_step", step=step, user_id=user.id)
    text, kb = await _build_dashboard(
        user,
        is_new_user=False,
        db=db,
        redis=redis,
        dashboard_service_factory=dashboard_service_factory,
    )
    await edit_screen(msg, "welcome.png", text, reply_markup=kb)


# ---------------------------------------------------------------------------
# Pipeline resume (article:start in pipeline/article.py, social:start in pipeline/social/social.py)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "pipeline:resume")
async def pipeline_resume(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Resume pipeline from checkpoint (E49, UX_PIPELINE §2.6).

    Reads checkpoint from Redis, restores FSM state.data, and routes
    the user to the appropriate step screen.
    """
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    checkpoint_raw = await redis.get(CacheKeys.pipeline_state(user.id))
    if not checkpoint_raw:
        await callback.answer("Нет активного процесса.", show_alert=True)
        return

    try:
        checkpoint = json.loads(checkpoint_raw)
    except (json.JSONDecodeError, TypeError):  # fmt: skip
        await callback.answer("Нет активного процесса.", show_alert=True)
        return

    pipeline_type = checkpoint.get("pipeline_type", "article")
    step = checkpoint.get("current_step", "")
    project_id = checkpoint.get("project_id")
    project_name = checkpoint.get("project_name", "")
    connection_id = checkpoint.get("connection_id")
    category_id = checkpoint.get("category_id")
    preview_id = checkpoint.get("preview_id")

    # Restore FSM data from checkpoint (M1: load category_name from DB)
    category_name = ""
    if category_id:
        cats_repo = CategoriesRepository(db)
        cat = await cats_repo.get_by_id(category_id)
        category_name = cat.name if cat else ""

    # Social pipeline needs platform_type + connection_identifier for readiness/confirm screens
    platform_type = ""
    connection_identifier = ""
    if pipeline_type == "social" and connection_id:
        settings = get_settings()
        cm = CredentialManager(settings.encryption_key.get_secret_value())
        conn_repo = ConnectionsRepository(db, cm)
        conn = await conn_repo.get_by_id(connection_id)
        if conn:
            platform_type = conn.platform_type
            connection_identifier = conn.identifier

    await state.update_data(
        project_id=project_id,
        project_name=project_name,
        connection_id=connection_id,
        category_id=category_id,
        category_name=category_name,
        preview_id=preview_id,
        platform_type=platform_type,
        connection_identifier=connection_identifier,
    )

    if pipeline_type == "social":
        await callback.answer()
        await _route_social_to_step(
            callback,
            state,
            user,
            db,
            redis,
            dashboard_service_factory,
            step=step,
            project_id=project_id,
            project_name=project_name,
            category_id=category_id,
            connection_id=connection_id,
        )
    else:
        await callback.answer()
        await _route_to_step(
            callback,
            state,
            user,
            db,
            redis,
            dashboard_service_factory,
            step=step,
            project_id=project_id,
            project_name=project_name,
            category_id=category_id,
            connection_id=connection_id,
            preview_id=preview_id,
        )


async def _route_social_to_step(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
    *,
    step: str,
    project_id: int | None,
    project_name: str,
    category_id: int | None,
    connection_id: int | None,
) -> None:
    """Route user to the correct social pipeline screen based on checkpoint step."""
    from routers.publishing.pipeline._common import SocialPipelineFSM

    msg = safe_message(callback)
    if not msg:
        return

    # Steps 1-2: project/connection selection — restart from project list
    if step in ("select_project", "", "select_connection"):
        projects_repo = ProjectsRepository(db)
        projects = await projects_repo.get_by_user(user.id)
        if not projects:
            await safe_edit_text(
                msg,
                "Пост (1/5) — Проект\n\nДля начала создадим проект — это 30 секунд.",
                reply_markup=pipeline_no_projects_kb(pipeline_type="social"),
            )
        else:
            await safe_edit_text(
                msg,
                "Пост (1/5) — Проект\n\nДля какого проекта?",
                reply_markup=pipeline_projects_kb(projects, pipeline_type="social"),
            )
        await state.set_state(SocialPipelineFSM.select_project)
        return

    # Step 3: category selection
    if step == "select_category":
        if not project_id:
            await _expire_social_checkpoint(msg, redis, state, user)
            return
        cats_repo = CategoriesRepository(db)
        categories = await cats_repo.get_by_project(project_id)
        if not categories:
            await safe_edit_text(
                msg,
                "Пост (3/5) — Тема\n\nО чём будет пост? Назовите тему.",
                reply_markup=cancel_kb("pipeline:social:cancel"),
            )
            await state.set_state(SocialPipelineFSM.create_category_name)
        elif len(categories) == 1:
            cat = categories[0]
            await state.update_data(category_id=cat.id, category_name=cat.name)
            from routers.publishing.pipeline.social.readiness import show_social_readiness_check

            await show_social_readiness_check(callback, state, user, db, redis)
        else:
            await safe_edit_text(
                msg,
                "Пост (3/5) — Тема\n\nКакая тема?",
                reply_markup=pipeline_categories_kb(categories, project_id, pipeline_type="social"),
            )
            await state.set_state(SocialPipelineFSM.select_category)
        return

    # Steps 4-5: readiness or confirm cost — re-run readiness check
    if step in ("readiness_check", "confirm_cost"):
        from routers.publishing.pipeline.social.readiness import show_social_readiness_check

        await show_social_readiness_check(callback, state, user, db, redis)
        return

    # Step 6-7 (review/publishing): FSM data (generated text) was cleared by /start.
    # Can't restore the generated post — redirect to readiness so user re-confirms + regenerates.
    if step in ("review", "generating", "publishing"):
        log.info("pipeline.social.resume_review_expired", step=step, user_id=user.id)
        from routers.publishing.pipeline.social.readiness import show_social_readiness_check

        await show_social_readiness_check(callback, state, user, db, redis)
        return

    # Fallback: unknown step — clear and show dashboard
    log.warning("pipeline.social.resume_unknown_step", step=step, user_id=user.id)
    await _expire_social_checkpoint(msg, redis, state, user)


async def _expire_social_checkpoint(
    msg: Message,
    redis: RedisClient,
    state: FSMContext,
    user: User,
) -> None:
    """Clear social checkpoint and show expiry message."""
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await state.clear()
    await safe_edit_text(
        msg,
        "\u26a0\ufe0f Сессия устарела. Нажмите /start чтобы начать заново.",
        reply_markup=menu_kb(),
    )


@router.callback_query(F.data == "pipeline:restart")
async def pipeline_restart(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Restart pipeline — clear checkpoint and start fresh (E49)."""
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await state.clear()
    msg = safe_message(callback)
    if msg:
        text, kb = await _build_dashboard(user, is_new_user, db, redis, dashboard_service_factory)
        await edit_screen(msg, "welcome.png", text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "pipeline:cancel")
async def pipeline_cancel(callback: CallbackQuery, redis: RedisClient, user: User) -> None:
    """Cancel active pipeline checkpoint."""
    await redis.delete(CacheKeys.pipeline_state(user.id))
    await callback.answer("Публикация отменена.")
    msg = safe_message(callback)
    if msg:
        await msg.delete()


@router.callback_query(F.data.startswith("pipeline:"))
async def pipeline_stale_catchall(callback: CallbackQuery) -> None:
    """Catch-all for stale pipeline callbacks after FSM timeout/cancel.

    Without this, clicks on old pipeline keyboards silently drop
    (no handler matches without FSM state) → "spinning clock" forever.
    """
    await callback.answer("Сессия завершена. Нажмите /start для продолжения.", show_alert=True)


@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery) -> None:
    """No-op callback for pagination counters and spacer buttons."""
    await callback.answer()


# ---------------------------------------------------------------------------
# Reply text dispatch
# ---------------------------------------------------------------------------


@router.message(F.text == "Отмена")
async def reply_cancel(
    message: Message,
    state: FSMContext,
    user: User,
    is_new_user: bool,
    db: SupabaseClient,
    redis: RedisClient,
    dashboard_service_factory: DashboardServiceFactory,
) -> None:
    """Reply keyboard: Cancel → clear FSM + pipeline checkpoint, show Dashboard."""
    interrupted = await ensure_no_active_fsm(state)
    # Clear pipeline checkpoint if it exists (BUG-4: reply cancel must clean up Redis)
    await redis.delete(CacheKeys.pipeline_state(user.id))
    if interrupted:
        await message.answer(f"{interrupted} \u2014 отменено.")
    text, kb = await _build_dashboard(user, is_new_user, db, redis, dashboard_service_factory)
    await message.answer(text, reply_markup=kb)
