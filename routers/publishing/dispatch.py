"""Router: Publish dispatch from category card -> ArticlePublishFSM or SocialPostPublishFSM.

Extracted from quick.py during Pipeline migration (Phase 13A).
Toolbox category card [Опубликовать] button still uses this handler.
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from bot.config import get_settings
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnection, User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.publish import publish_platform_choice_kb
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="publishing_dispatch")


@router.callback_query(F.data.regexp(r"^category:(\d+):publish$"))
async def cb_publish_dispatch(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Dispatch [Опубликовать] from category card to the right publish flow.

    Logic:
    - 0 connections -> "Подключите платформу"
    - 1 WP -> ArticlePublishFSM
    - 1 social -> SocialPostPublishFSM
    - >1 -> platform choice keyboard
    """
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    category_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    cat_repo = CategoriesRepository(db)
    category = await cat_repo.get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    connections: list[PlatformConnection] = await ConnectionsRepository(db, cm).get_by_project(project.id)
    active = [c for c in connections if c.status == "active"]

    if not active:
        await callback.answer("Подключите хотя бы одну платформу.", show_alert=True)
        return

    if len(active) == 1:
        conn = active[0]
        plat_short = {"wordpress": "wp", "telegram": "tg", "vk": "vk", "pinterest": "pin"}
        ps = plat_short.get(conn.platform_type, conn.platform_type[:2])
        if conn.platform_type == "wordpress":
            callback.data = f"category:{category_id}:publish:wp:{conn.id}"  # type: ignore[assignment]
            from routers.publishing.preview import cb_article_start_with_conn

            await cb_article_start_with_conn(callback, user, db, state)
        else:
            callback.data = f"category:{category_id}:publish:{ps}:{conn.id}"  # type: ignore[assignment]
            from routers.publishing.social import cb_social_start

            await cb_social_start(callback, state, user, db)
        return

    # Multiple connections -- show platform choice
    await msg.edit_text(
        "Выберите платформу для публикации:",
        reply_markup=publish_platform_choice_kb(category_id, active).as_markup(),
    )
    await callback.answer()
