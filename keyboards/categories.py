"""Category, connection, keywords, description, and prices keyboards."""

import math
from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, PlatformConnection
from keyboards.common import format_connection_display
from keyboards.pagination import PAGE_SIZE, _safe_cb

__all__ = [
    "category_card_kb",
    "category_created_kb",
    "category_delete_confirm_kb",
    "category_list_empty_kb",
    "category_list_kb",
    "connection_delete_confirm_kb",
    "connection_list_kb",
    "connection_manage_kb",
    "description_kb",
    "description_review_kb",
    "keywords_cluster_delete_list_kb",
    "keywords_cluster_list_kb",
    "keywords_delete_all_confirm_kb",
    "keywords_empty_kb",
    "keywords_results_kb",
    "keywords_summary_kb",
    "prices_kb",
]


# ---------------------------------------------------------------------------
# Category list
# ---------------------------------------------------------------------------


def category_list_kb(categories: list[Category], project_id: int, page: int = 1) -> InlineKeyboardMarkup:
    """Category list with pagination. Item cb: category:{id}:card."""
    from keyboards.pagination import paginate

    kb, _ = paginate(
        items=categories,
        page=page,
        cb_prefix=f"categories:{project_id}",
        item_text="name",
        item_cb="category:{id}:card",
        item_style=ButtonStyle.PRIMARY,
    )
    kb.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="Создать категорию",
                callback_data=f"category:{project_id}:create",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )
    kb.inline_keyboard.append(
        [
            InlineKeyboardButton(text="К проекту", callback_data=f"project:{project_id}:card"),
        ]
    )
    return kb


def category_list_empty_kb(project_id: int) -> InlineKeyboardMarkup:
    """Empty category list keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать категорию",
                    callback_data=f"category:{project_id}:create",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [InlineKeyboardButton(text="К проекту", callback_data=f"project:{project_id}:card")],
        ]
    )


# ---------------------------------------------------------------------------
# Category card
# ---------------------------------------------------------------------------


def category_card_kb(category_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Category card actions (UX_TOOLBOX.md section 8)."""
    cid = category_id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Описание", callback_data=f"category:{cid}:description"),
                InlineKeyboardButton(text="Ключевые фразы", callback_data=f"category:{cid}:keywords"),
            ],
            [
                InlineKeyboardButton(text="Цены", callback_data=f"category:{cid}:prices"),
            ],
            [
                InlineKeyboardButton(
                    text="Удалить категорию",
                    callback_data=f"category:{cid}:delete",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [InlineKeyboardButton(text="К категориям", callback_data=f"project:{project_id}:categories")],
        ]
    )


def category_delete_confirm_kb(category_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Category delete confirmation dialog."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"category:{category_id}:delete:confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"category:{category_id}:card"),
            ],
        ]
    )


def category_created_kb(category_id: int) -> InlineKeyboardMarkup:
    """Success screen after category creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="К категории",
                    callback_data=f"category:{category_id}:card",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Connection list
# ---------------------------------------------------------------------------


def connection_list_kb(connections: list[PlatformConnection], project_id: int) -> InlineKeyboardMarkup:
    """Connection list with platform status + add buttons (UX_TOOLBOX.md section 5.1).

    Rule: 1 project = max 1 connection per platform type (except VK: group + personal).
    "Add" buttons are hidden for platform types that already have a connection.
    VK allows both group and personal -- hide "+ VK" only if both are connected.
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Determine which platform types already exist
    connected_types = {conn.platform_type for conn in connections}

    # VK special case: allow group + personal
    vk_conns = [c for c in connections if c.platform_type == "vk"]
    vk_has_group = any(
        (c.credentials or {}).get("target") != "personal" for c in vk_conns
    )
    vk_has_personal = any(
        (c.credentials or {}).get("target") == "personal" for c in vk_conns
    )
    vk_full = vk_has_group and vk_has_personal

    for conn in connections:
        text = format_connection_display(conn, with_status=True)
        rows.append([InlineKeyboardButton(text=text, callback_data=f"conn:{conn.id}:manage")])

    # Add platform buttons -- only for types NOT yet connected
    _ALL_PLATFORMS = [
        ("wordpress", "+ Сайт"),
        ("telegram", "+ Telegram"),
        ("vk", "+ VK"),
        ("pinterest", "+ Pinterest"),
    ]
    add_buttons = []
    for ptype, label in _ALL_PLATFORMS:
        if ptype == "vk":
            if vk_full:
                continue
        elif ptype in connected_types:
            continue
        add_buttons.append(
            InlineKeyboardButton(text=label, callback_data=f"conn:{project_id}:add:{ptype}")
        )
    # Layout: 2 per row
    for i in range(0, len(add_buttons), 2):
        rows.append(add_buttons[i : i + 2])

    rows.append(
        [
            InlineKeyboardButton(text="К проекту", callback_data=f"project:{project_id}:card"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Connection manage
# ---------------------------------------------------------------------------


def connection_manage_kb(conn_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Manage single connection -- delete + back."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"conn:{conn_id}:delete",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [InlineKeyboardButton(text="К подключениям", callback_data=f"conn:{project_id}:list")],
        ]
    )


def connection_delete_confirm_kb(conn_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Connection delete confirmation dialog."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"conn:{conn_id}:delete:confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"conn:{conn_id}:manage"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


def keywords_empty_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Empty keywords screen (UX_TOOLBOX section 9.1)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Начать подбор", callback_data=f"kw:{cat_id}:generate")],
            [InlineKeyboardButton(text="Загрузить", callback_data=f"kw:{cat_id}:upload")],
            [InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card")],
        ]
    )


def keywords_summary_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Keywords summary with actions (UX_TOOLBOX section 9.2)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Кластеры", callback_data=f"kw:{cat_id}:clusters")],
            [InlineKeyboardButton(text="CSV", callback_data=f"kw:{cat_id}:download")],
            [InlineKeyboardButton(text="Добавить ещё", callback_data=f"kw:{cat_id}:generate")],
            [InlineKeyboardButton(text="Загрузить", callback_data=f"kw:{cat_id}:upload")],
            [InlineKeyboardButton(text="Удалить кластер", callback_data=f"kw:{cat_id}:delete_cluster")],
            [
                InlineKeyboardButton(
                    text="Удалить все фразы",
                    callback_data=f"kw:{cat_id}:delete_all",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card")],
        ]
    )


def keywords_cluster_list_kb(
    clusters: list[dict[str, Any]],
    cat_id: int,
    page: int = 1,
) -> InlineKeyboardMarkup:
    """Paginated cluster list for drill-down (UX_TOOLBOX section 9.3)."""
    total = len(clusters)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE
    page_clusters = clusters[start : start + PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for idx_offset, cluster in enumerate(page_clusters):
        idx = start + idx_offset
        name = cluster.get("cluster_name", f"Cluster {idx}")
        phrase_count = len(cluster.get("phrases", []))
        volume = cluster.get("total_volume", 0)
        text = f"{name} ({phrase_count} фраз, {volume:,}/мес)"
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=_safe_cb(f"kw:cluster:{cat_id}:{idx}"),
                ),
            ]
        )

    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(InlineKeyboardButton(text="\u25c0", callback_data=f"page:clusters:{cat_id}:{page - 1}"))
        else:
            nav_row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton(text="\u25b6", callback_data=f"page:clusters:{cat_id}:{page + 1}"))
        else:
            nav_row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(text="К ключевым фразам", callback_data=f"category:{cat_id}:keywords"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def keywords_cluster_delete_list_kb(
    clusters: list[dict[str, Any]],
    cat_id: int,
    page: int = 1,
) -> InlineKeyboardMarkup:
    """Cluster list with [X] prefix for deletion (UX_TOOLBOX section 9.7)."""
    total = len(clusters)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))

    start = (page - 1) * PAGE_SIZE
    page_clusters = clusters[start : start + PAGE_SIZE]

    rows: list[list[InlineKeyboardButton]] = []
    for idx_offset, cluster in enumerate(page_clusters):
        idx = start + idx_offset
        name = cluster.get("cluster_name", f"Cluster {idx}")
        text = f"[X] {name}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=_safe_cb(f"kw:{cat_id}:del_cluster:{idx}"),
                ),
            ]
        )

    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if page > 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="\u25c0",
                    callback_data=f"page:del_clusters:{cat_id}:{page - 1}",
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        nav_row.append(InlineKeyboardButton(text=f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            nav_row.append(
                InlineKeyboardButton(
                    text="\u25b6",
                    callback_data=f"page:del_clusters:{cat_id}:{page + 1}",
                )
            )
        else:
            nav_row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(text="К ключевым фразам", callback_data=f"category:{cat_id}:keywords"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def keywords_results_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Post-generation results navigation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Кластеры", callback_data=f"kw:{cat_id}:clusters")],
            [InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card")],
        ]
    )


def keywords_delete_all_confirm_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Delete-all keywords confirmation (two-step)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить все фразы",
                    callback_data=f"kw:{cat_id}:delete_all:yes",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"category:{cat_id}:keywords"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


def description_kb(cat_id: int, has_description: bool) -> InlineKeyboardMarkup:
    """Description screen actions (UX_TOOLBOX section 10 / 10.3)."""
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="Написать вручную", callback_data=f"desc:{cat_id}:manual")],
        [
            InlineKeyboardButton(
                text="Улучшить с ИИ",
                callback_data=f"desc:{cat_id}:generate",
            ),
        ],
    ]
    if has_description:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Удалить описание",
                    callback_data=f"desc:{cat_id}:delete",
                    style=ButtonStyle.DANGER,
                ),
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def description_review_kb(cat_id: int, regen_count: int) -> InlineKeyboardMarkup:
    """Review generated description: save / regenerate / cancel (UX_TOOLBOX section 10.1)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Сохранить",
                    callback_data=f"desc:{cat_id}:review_save",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(text="Перегенерировать", callback_data=f"desc:{cat_id}:review_regen"),
                InlineKeyboardButton(text="Отмена", callback_data=f"desc:{cat_id}:review_cancel"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------


def prices_kb(cat_id: int, has_prices: bool) -> InlineKeyboardMarkup:
    """Prices screen actions (UX_TOOLBOX section 11 / 11.3)."""
    rows: list[list[InlineKeyboardButton]] = []
    if has_prices:
        rows.append([InlineKeyboardButton(text="Обновить текстом", callback_data=f"prices:{cat_id}:text")])
        rows.append([InlineKeyboardButton(text="Загрузить Excel", callback_data=f"prices:{cat_id}:excel")])
        rows.append(
            [
                InlineKeyboardButton(
                    text="Удалить прайс",
                    callback_data=f"prices:{cat_id}:delete",
                    style=ButtonStyle.DANGER,
                ),
            ]
        )
    else:
        rows.append([InlineKeyboardButton(text="Добавить текстом", callback_data=f"prices:{cat_id}:text")])
        rows.append([InlineKeyboardButton(text="Загрузить Excel", callback_data=f"prices:{cat_id}:excel")])
    rows.append(
        [
            InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
