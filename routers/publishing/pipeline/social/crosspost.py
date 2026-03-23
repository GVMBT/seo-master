"""Cross-post flow (F6.4, UX_PIPELINE.md §6).

Adapts a published social post for other connected platforms using AI.
"""

from __future__ import annotations

import base64 as b64mod
import html
from typing import Any

import httpx
import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from bot.helpers import safe_edit_text, safe_message
from bot.texts import strings as S
from cache.client import RedisClient
from db.client import SupabaseClient
from db.models import PublicationLogCreate, User
from db.repositories.categories import CategoriesRepository
from db.repositories.publications import PublicationsRepository
from keyboards.inline import menu_kb
from routers.publishing.pipeline._common import SocialPipelineFSM
from routers.publishing.pipeline.social.generation import (
    _PUBLISH_LOCK_TTL,
    _get_content_type,
    _get_publisher,
)
from services.connections import ConnectionService
from services.publishers.base import PublishRequest, PublishResult

log = structlog.get_logger()
router = Router()

_SOCIAL_TYPES = {"telegram", "vk", "pinterest"}


@router.callback_query(F.data == "pipeline:crosspost:start")
async def crosspost_start(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
) -> None:
    """Start cross-post: show platform selection or go directly if only 1."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    project_id = data.get("project_id")
    connection_id = data.get("connection_id")
    generated_text = data.get("generated_text", "")
    keyword = data.get("generated_keyword", "")

    if not project_id or not connection_id or not generated_text:
        await callback.answer(S.PIPELINE_SESSION_EXPIRED, show_alert=True)
        return

    conn_svc = ConnectionService(db, http_client)
    all_conns = await conn_svc.get_by_project(project_id)
    targets = [
        c for c in all_conns
        if c.id != connection_id and c.platform_type in _SOCIAL_TYPES
    ]

    if not targets:
        await callback.answer(S.POST_CROSSPOST_NO_TARGETS, show_alert=True)
        return

    # Store targets and all selected by default
    target_ids = {c.id for c in targets}
    await state.update_data(
        crosspost_target_ids=list(target_ids),
        crosspost_selected_ids=list(target_ids),
    )

    if len(targets) == 1:
        # Skip selection screen, go directly to adaptation
        await state.update_data(crosspost_selected_ids=[targets[0].id])
        await state.set_state(SocialPipelineFSM.cross_post_running)
        await _execute_crosspost(msg, state, user, db, redis, http_client, ai_orchestrator, callback)
        return

    from keyboards.pipeline import crosspost_select_kb

    await safe_edit_text(
        msg,
        S.POST_CROSSPOST_TITLE.format(keyword=html.escape(keyword)) + "\n\n"
        + S.POST_CROSSPOST_QUESTION,
        reply_markup=crosspost_select_kb(targets, target_ids),
    )
    await state.set_state(SocialPipelineFSM.cross_post_select)
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.cross_post_select,
    F.data.startswith("pipeline:crosspost:toggle:"),
)
async def crosspost_toggle(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
) -> None:
    """Toggle a platform in cross-post selection."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer()
        return
    try:
        toggle_id = int(parts[3])
    except ValueError:
        await callback.answer()
        return

    data = await state.get_data()
    selected: set[int] = set(data.get("crosspost_selected_ids", []))
    target_ids: list[int] = data.get("crosspost_target_ids", [])

    if toggle_id in selected:
        selected.discard(toggle_id)
    else:
        selected.add(toggle_id)

    await state.update_data(crosspost_selected_ids=list(selected))

    # Rebuild keyboard with updated selection
    project_id: int = data.get("project_id", 0)
    conn_svc = ConnectionService(db, http_client)
    all_conns = await conn_svc.get_by_project(project_id)
    targets = [c for c in all_conns if c.id in target_ids]

    from keyboards.pipeline import crosspost_select_kb

    await msg.edit_reply_markup(reply_markup=crosspost_select_kb(targets, selected))
    await callback.answer()


@router.callback_query(
    SocialPipelineFSM.cross_post_select,
    F.data == "pipeline:crosspost:go",
)
async def crosspost_go(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
) -> None:
    """Execute cross-posting for selected platforms."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    data = await state.get_data()
    selected = data.get("crosspost_selected_ids", [])
    if not selected:
        await callback.answer(S.POST_CROSSPOST_MIN_ONE, show_alert=True)
        return

    await state.set_state(SocialPipelineFSM.cross_post_running)
    await _execute_crosspost(msg, state, user, db, redis, http_client, ai_orchestrator, callback)


@router.callback_query(F.data == "pipeline:crosspost:cancel")
async def crosspost_cancel(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Cancel cross-posting, return to dashboard."""
    msg = safe_message(callback)
    if not msg:
        await callback.answer()
        return

    await state.clear()
    await safe_edit_text(msg, S.POST_CROSSPOST_CANCELLED, reply_markup=menu_kb())
    await callback.answer()


async def _execute_crosspost(
    msg: Message,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    ai_orchestrator: Any,
    callback: CallbackQuery,
) -> None:
    """Run AI adaptation and publish for each selected platform."""
    from services.ai.social_posts import SocialPostService
    from services.tokens import TokenService, estimate_cross_post_cost

    data = await state.get_data()
    selected_ids: list[int] = data.get("crosspost_selected_ids", [])
    project_id: int = data.get("project_id", 0)
    category_id: int = data.get("category_id", 0)
    generated_text: str = data.get("generated_text", "")
    keyword: str = data.get("generated_keyword", "")
    platform_type: str = data.get("platform_type", "")

    # E07: Redis NX lock to prevent double-click
    lock_key = f"crosspost:{user.id}:{project_id}"
    acquired = await redis.set(lock_key, "1", ex=_PUBLISH_LOCK_TTL, nx=True)
    if not acquired:
        await safe_edit_text(msg, S.PIPELINE_PUBLISH_LOCKED)
        await callback.answer()
        return

    settings = get_settings()
    token_svc = TokenService(db=db, admin_ids=settings.admin_ids)
    social_svc = SocialPostService(ai_orchestrator, db, skip_rate_limit=True)
    conn_svc = ConnectionService(db, http_client)

    # Progress message
    await safe_edit_text(msg, S.POST_CROSSPOST_RUNNING)

    results: list[str] = []
    total_cost = 0

    try:
        for conn_id in selected_ids:
            conn = await conn_svc.get_by_id(conn_id)
            if not conn or conn.status != "active":
                results.append(f"\u274c {conn_id}: подключение неактивно")
                continue

            cost = estimate_cross_post_cost()

            # Balance check (not GOD_MODE)
            is_god = user.id in settings.admin_ids
            if not is_god and not await token_svc.check_balance(user.id, cost):
                results.append(f"\u274c {conn.platform_type.upper()}: недостаточно токенов")
                break

            try:
                adapted = await social_svc.adapt_for_platform(
                    original_text=generated_text,
                    source_platform=platform_type,
                    target_platform=conn.platform_type,
                    user_id=user.id,
                    project_id=project_id,
                    keyword=keyword,
                )

                if isinstance(adapted.content, dict):
                    adapted_text = adapted.content.get("text", "")
                    hashtags = adapted.content.get("hashtags", [])
                    if hashtags:
                        tags_str = " ".join(f"#{h.lstrip('#')}" for h in hashtags)
                        if tags_str not in adapted_text:
                            adapted_text = f"{adapted_text}\n\n{tags_str}"
                else:
                    adapted_text = str(adapted.content) if adapted.content else generated_text

                # Get publisher and publish (with token refresh for Pinterest)
                from services.publishers.factory import make_token_refresh_cb

                enc_key = settings.encryption_key.get_secret_value()
                on_refresh = make_token_refresh_cb(db, conn.id, enc_key)
                publisher = _get_publisher(conn.platform_type, http_client, settings, on_token_refresh=on_refresh)

                ct = _get_content_type(conn.platform_type)
                category = await CategoriesRepository(db).get_by_id(category_id)

                metadata: dict[str, str] = {}
                if conn.platform_type == "pinterest" and isinstance(adapted.content, dict):
                    metadata["pin_title"] = adapted.content.get("pin_title", "")[:100]

                # Attach image from FSM state (required for Pinterest)
                publish_images: list[bytes] = []
                image_b64_stored = data.get("generated_image_b64")
                if image_b64_stored:
                    publish_images = [b64mod.b64decode(image_b64_stored)]

                pub_result: PublishResult = await publisher.publish(
                    PublishRequest(
                        connection=conn,
                        content=adapted_text,
                        content_type=ct,
                        category=category,
                        metadata=metadata,
                        images=publish_images,
                    )
                )

                if not pub_result.success:
                    results.append(f"\u274c {conn.platform_type.upper()}: {pub_result.error}")
                    continue

                # Charge after successful publish
                if not is_god:
                    await token_svc.charge(
                        user.id, cost, "cross_post",
                        description=f"Cross-post: {keyword}",
                    )
                total_cost += cost

                # Log publication
                pub_repo = PublicationsRepository(db)
                await pub_repo.create_log(
                    PublicationLogCreate(
                        user_id=user.id,
                        project_id=project_id,
                        category_id=category_id,
                        platform_type=conn.platform_type,
                        connection_id=conn.id,
                        keyword=keyword,
                        content_type="cross_post",
                        tokens_spent=cost,
                        post_url=pub_result.post_url or "",
                    )
                )

                url_part = f": {pub_result.post_url}" if pub_result.post_url else ""
                results.append(f"\u2705 {conn.platform_type.upper()}{url_part}")

                log.info(
                    "pipeline.crosspost.published",
                    user_id=user.id,
                    platform=conn.platform_type,
                    conn_id=conn.id,
                )

            except Exception:
                log.exception("pipeline.crosspost.failed", conn_id=conn_id)
                results.append(f"\u274c {conn.platform_type.upper()}: ошибка адаптации")
    finally:
        await redis.delete(lock_key)

    # Show results
    balance = await token_svc.get_balance(user.id)
    result_lines = "\n".join(results)
    text = (
        f"Кросс-постинг завершён:\n\n"
        f"{result_lines}\n\n"
        f"Списано: {total_cost} ток. | Баланс: {balance} ток."
    )

    from keyboards.pipeline import crosspost_result_kb

    await safe_edit_text(msg, text, reply_markup=crosspost_result_kb())
    await state.set_state(SocialPipelineFSM.cross_post_result)
    await callback.answer()
