"""Router: Quick Publish — 2-step callback flow (no FSM).

USER_FLOWS_AND_UI_MAP.md: Reply button [Быстрая публикация] → project list → combo list → delegate to FSM.
"""

from __future__ import annotations

import structlog
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.config import get_settings
from db.client import SupabaseClient
from db.credential_manager import CredentialManager
from db.models import PlatformConnection, Project, User
from db.repositories.categories import CategoriesRepository
from db.repositories.connections import ConnectionsRepository
from db.repositories.projects import ProjectsRepository
from keyboards.publish import (
    quick_combo_list_kb,
    quick_project_list_kb,
)
from routers._helpers import guard_callback_message

log = structlog.get_logger()

router = Router(name="publishing_quick")

# Platform short code → full name mapping (must match _PLAT_CODE in keyboards/publish.py)
_PLAT_SHORT_TO_FULL: dict[str, str] = {
    "wp": "wordpress",
    "tg": "telegram",
    "vk": "vk",
    "pi": "pinterest",
}


# ---------------------------------------------------------------------------
# Entry point — called from start.py reply button
# ---------------------------------------------------------------------------


async def send_quick_publish_menu(message: Message, user: User, db: SupabaseClient) -> None:
    """Build and send quick publish project/combo selection.

    Called from start.py when user taps [Быстрая публикация] reply button.
    """
    projects = await ProjectsRepository(db).get_by_user(user.id)
    if not projects:
        await message.answer("У вас нет проектов. Создайте первый проект, чтобы публиковать контент.")
        return

    if len(projects) == 1:
        # Skip project selection, go straight to combos
        combos = await _build_combos(projects[0], db)
        if not combos:
            await message.answer(
                "Нет доступных комбинаций для публикации.\n"
                "Добавьте категорию и подключите платформу."
            )
            return
        await message.answer(
            "Выберите что публиковать:",
            reply_markup=quick_combo_list_kb(combos, projects[0].id).as_markup(),
        )
        return

    # Multiple projects — show project list
    await message.answer(
        "Выберите проект:",
        reply_markup=quick_project_list_kb(projects).as_markup(),
    )


# ---------------------------------------------------------------------------
# Category card → [Опубликовать] — platform dispatch
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^category:(\d+):publish$"))
async def cb_publish_dispatch(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """Dispatch [Опубликовать] from category card to the right publish flow.

    Logic:
    - 0 connections → "Подключите платформу"
    - 1 WP → ArticlePublishFSM
    - 1 social → SocialPostPublishFSM
    - >1 → platform choice keyboard
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
            await cb_article_start_with_conn(callback, state, user, db)
        else:
            callback.data = f"category:{category_id}:publish:{ps}:{conn.id}"  # type: ignore[assignment]
            from routers.publishing.social import cb_social_start
            await cb_social_start(callback, state, user, db)
        return

    # Multiple connections — show platform choice
    from keyboards.publish import publish_platform_choice_kb
    await msg.edit_text(
        "Выберите платформу для публикации:",
        reply_markup=publish_platform_choice_kb(category_id, active).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Project selection
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^quick:project:(\d+)$"))
async def cb_quick_project(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """User selected a project — show category→platform combos."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    project_id = int(callback.data.split(":")[2])  # type: ignore[union-attr]
    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    combos = await _build_combos(project, db)
    if not combos:
        await callback.answer("Нет категорий или подключений.", show_alert=True)
        return

    await msg.edit_text(
        "Выберите что публиковать:",
        reply_markup=quick_combo_list_kb(combos, project.id).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Combo selection → delegate to ArticlePublishFSM / SocialPostPublishFSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^quick:cat:(\d+):(wp|tg|vk|pi):(\d+)$"))
async def cb_quick_publish_target(
    callback: CallbackQuery, state: FSMContext, user: User, db: SupabaseClient,
) -> None:
    """User selected a category+platform combo — delegate to the appropriate FSM."""
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
        # Route to ArticlePublishFSM (preview.py handles category:{id}:publish:wp:{conn_id})
        callback.data = f"category:{category_id}:publish:wp:{connection_id}"  # type: ignore[assignment]
        from routers.publishing.preview import cb_article_start_with_conn

        await cb_article_start_with_conn(callback, state, user, db)
    else:
        # Route to SocialPostPublishFSM
        plat_map = {"tg": "tg", "vk": "vk", "pi": "pin"}
        plat_code = plat_map.get(platform_short, platform_short)
        callback.data = f"category:{category_id}:publish:{plat_code}:{connection_id}"  # type: ignore[assignment]
        from routers.publishing.social import cb_social_start

        await cb_social_start(callback, state, user, db)
    # callback.answer() is handled by the delegated handler


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


@router.callback_query(F.data.regexp(r"^page:quick_proj:(\d+)$"))
async def cb_quick_proj_page(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Paginate quick publish project list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    page = int(callback.data.split(":")[-1])  # type: ignore[union-attr]
    projects = await ProjectsRepository(db).get_by_user(user.id)
    await msg.edit_text(
        "Выберите проект:",
        reply_markup=quick_project_list_kb(projects, page=page).as_markup(),
    )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^page:quick_combo:(\d+):(\d+)$"))
async def cb_quick_combo_page(callback: CallbackQuery, user: User, db: SupabaseClient) -> None:
    """Paginate quick publish combo list."""
    msg = await guard_callback_message(callback)
    if msg is None:
        return

    parts = callback.data.split(":")  # type: ignore[union-attr]
    # page:quick_combo:{project_id}:{page} → indices 2, 3
    project_id = int(parts[2])
    page = int(parts[3])

    project = await ProjectsRepository(db).get_by_id(project_id)
    if not project or project.user_id != user.id:
        await callback.answer("Проект не найден.", show_alert=True)
        return

    combos = await _build_combos(project, db)
    await msg.edit_text(
        "Выберите что публиковать:",
        reply_markup=quick_combo_list_kb(combos, project_id, page=page).as_markup(),
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _build_combos(project: Project, db: SupabaseClient) -> list[dict[str, object]]:
    """Build category→platform combo list for quick publish.

    Returns list of dicts: {cat_id, cat_name, platform, conn_id, conn_name}.
    """
    settings = get_settings()
    cm = CredentialManager(settings.encryption_key.get_secret_value())
    conn_repo = ConnectionsRepository(db, cm)

    categories = await CategoriesRepository(db).get_by_project(project.id)
    connections: list[PlatformConnection] = await conn_repo.get_by_project(project.id)

    if not categories or not connections:
        return []

    combos: list[dict[str, object]] = []
    for cat in categories:
        for conn in connections:
            if conn.status != "active":
                continue
            combos.append({
                "cat_id": cat.id,
                "cat_name": cat.name,
                "platform": conn.platform_type,
                "conn_id": conn.id,
                "conn_name": conn.identifier,
            })
    return combos
