"""Router: Legacy quick publish handlers (deprecated).

The Quick Publish flow (quick:project/quick:cat callbacks) is deprecated
and replaced by Goal-Oriented Pipeline (Phase 13).

Category card publish dispatch (category:{id}:publish) has been extracted
to routers/publishing/dispatch.py.
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from db.client import SupabaseClient
from db.models import User
from db.repositories.categories import CategoriesRepository
from db.repositories.projects import ProjectsRepository
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="publishing_quick")


# ---------------------------------------------------------------------------
# Legacy quick publish handlers (deprecated -- replaced by Pipeline)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^quick:project:(\d+)$"))
async def cb_quick_project(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Legacy: quick publish project selection (deprecated)."""
    await callback.answer("Используйте «Написать статью» для публикации.", show_alert=True)


@router.callback_query(F.data.regexp(r"^quick:cat:(\d+):(wp|tg|vk|pi):(\d+)$"))
async def cb_quick_publish_target(
    callback: CallbackQuery,
    state: FSMContext,
    user: User,
    db: SupabaseClient,
) -> None:
    """Legacy: quick publish combo selection (deprecated)."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    category_id = int(parts[2])
    platform_short = parts[3]
    connection_id = int(parts[4])

    # Verify ownership
    cat_repo = CategoriesRepository(db)
    category = await cat_repo.get_by_id(category_id)
    if not category:
        await callback.answer("Категория не найдена.", show_alert=True)
        return
    project = await ProjectsRepository(db).get_by_id(category.project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Категория не найдена.", show_alert=True)
        return

    # Delegate to appropriate publish flow by synthesizing the correct callback_data
    if platform_short == "wp":
        callback.data = f"category:{category_id}:publish:wp:{connection_id}"  # type: ignore[assignment]
        from routers.publishing.preview import cb_article_start_with_conn

        await cb_article_start_with_conn(callback, user, db, state)
    else:
        plat_map = {"tg": "tg", "vk": "vk", "pi": "pin"}
        plat_code = plat_map.get(platform_short, platform_short)
        callback.data = f"category:{category_id}:publish:{plat_code}:{connection_id}"  # type: ignore[assignment]
        from routers.publishing.social import cb_social_start

        await cb_social_start(callback, state, user, db)


@router.callback_query(F.data.regexp(r"^page:quick_proj:(\d+)$"))
async def cb_quick_proj_page(callback: CallbackQuery) -> None:
    """Legacy: quick publish project pagination (deprecated)."""
    await callback.answer("Используйте «Написать статью» для публикации.", show_alert=True)


@router.callback_query(F.data.regexp(r"^page:quick_combo:(\d+):(\d+)$"))
async def cb_quick_combo_page(callback: CallbackQuery) -> None:
    """Legacy: quick publish combo pagination (deprecated)."""
    await callback.answer("Используйте «Написать статью» для публикации.", show_alert=True)
