"""Inline keyboards for Dashboard, Projects, Categories, Connections."""

import math
from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, PlatformConnection, Project
from keyboards.pagination import PAGE_SIZE, _safe_cb, paginate
from services.tokens import COST_DESCRIPTION

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def dashboard_kb(
    has_wp: bool,
    has_social: bool,
    balance: int,
) -> InlineKeyboardMarkup:
    """Dashboard keyboard with pipeline CTAs and nav row.

    PRIMARY CTA logic (UX_PIPELINE.md section 2.4):
    - has WP, no social -> article is PRIMARY
    - has social, no WP -> social is PRIMARY
    - both or neither -> article is PRIMARY
    """
    rows: list[list[InlineKeyboardButton]] = []

    if balance <= 0:
        # Zero/negative balance: top-up CTA as PRIMARY + pipeline CTAs stay visible (section 2.7)
        rows.append(
            [
                InlineKeyboardButton(
                    text="Пополнить баланс",
                    callback_data="nav:tokens",
                    style=ButtonStyle.PRIMARY,
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Написать статью на сайт",
                    callback_data="pipeline:article:start",
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Создать пост в соцсети",
                    callback_data="pipeline:social:start",
                ),
            ]
        )
    else:
        # Pipeline CTAs
        article_primary = not (has_social and not has_wp)
        rows.append(
            [
                InlineKeyboardButton(
                    text="Написать статью на сайт",
                    callback_data="pipeline:article:start",
                    style=ButtonStyle.PRIMARY if article_primary else None,
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="Создать пост в соцсети",
                    callback_data="pipeline:social:start",
                    style=ButtonStyle.PRIMARY if not article_primary else None,
                ),
            ]
        )

    # Nav row
    rows.append(
        [
            InlineKeyboardButton(text="Мои проекты", callback_data="nav:projects"),
            InlineKeyboardButton(text="Профиль", callback_data="nav:profile"),
            InlineKeyboardButton(text="Токены", callback_data="nav:tokens"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def dashboard_resume_kb() -> InlineKeyboardMarkup:
    """Checkpoint resume keyboard (UX_PIPELINE.md section 2.6)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Продолжить",
                    callback_data="pipeline:resume",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(text="Начать заново", callback_data="pipeline:restart"),
                InlineKeyboardButton(
                    text="Отменить",
                    callback_data="pipeline:cancel",
                    style=ButtonStyle.DANGER,
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Project list
# ---------------------------------------------------------------------------


def project_list_kb(projects: list[Project], page: int = 1) -> InlineKeyboardMarkup:
    """Project list with pagination. Item cb: project:{id}:card."""
    kb, _ = paginate(
        items=projects,
        page=page,
        cb_prefix="projects",
        item_text="name",
        item_cb="project:{id}:card",
    )
    # Append create + dashboard buttons
    kb.inline_keyboard.append(
        [
            InlineKeyboardButton(
                text="Создать проект",
                callback_data="project:create",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )
    kb.inline_keyboard.append(
        [
            InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
        ]
    )
    return kb


def project_list_empty_kb() -> InlineKeyboardMarkup:
    """Empty project list keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать проект",
                    callback_data="project:create",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard")],
        ]
    )


# ---------------------------------------------------------------------------
# Project card
# ---------------------------------------------------------------------------


def project_card_kb(project_id: int) -> InlineKeyboardMarkup:
    """Project card action buttons (UX_TOOLBOX.md section 3.1)."""
    pid = project_id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Редактировать", callback_data=f"project:{pid}:edit"),
                InlineKeyboardButton(text="Категории", callback_data=f"project:{pid}:categories"),
            ],
            [
                InlineKeyboardButton(text="Подключения", callback_data=f"project:{pid}:connections"),
                InlineKeyboardButton(text="Планировщик", callback_data=f"project:{pid}:scheduler"),
            ],
            [
                InlineKeyboardButton(
                    text="Удалить проект",
                    callback_data=f"project:{pid}:delete",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [InlineKeyboardButton(text="К списку проектов", callback_data="nav:projects")],
        ]
    )


# ---------------------------------------------------------------------------
# Project edit
# ---------------------------------------------------------------------------

_EDIT_FIELDS: list[tuple[str, str]] = [
    ("name", "Название"),
    ("company_name", "Компания"),
    ("specialization", "Специализация"),
    ("website_url", "Сайт"),
    ("company_city", "Город"),
    ("company_address", "Адрес"),
    ("company_phone", "Телефон"),
    ("company_email", "Эл. почта"),
    ("timezone", "Часовой пояс"),
]


def project_edit_kb(project_id: int) -> InlineKeyboardMarkup:
    """Edit screen: field buttons in 2-column grid + delete + back."""
    pid = project_id
    rows: list[list[InlineKeyboardButton]] = []

    # 2-column layout for fields
    for i in range(0, len(_EDIT_FIELDS), 2):
        row: list[InlineKeyboardButton] = []
        for field, label in _EDIT_FIELDS[i : i + 2]:
            row.append(InlineKeyboardButton(text=label, callback_data=f"project:{pid}:edit:{field}"))
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                text="Удалить проект",
                callback_data=f"project:{pid}:delete",
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="К проекту", callback_data=f"project:{pid}:card"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Project delete confirm
# ---------------------------------------------------------------------------


def project_delete_confirm_kb(project_id: int) -> InlineKeyboardMarkup:
    """Delete confirmation dialog."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подтвердить удаление",
                    callback_data=f"project:{project_id}:delete:confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"project:{project_id}:card"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Project created
# ---------------------------------------------------------------------------


def project_deleted_kb() -> InlineKeyboardMarkup:
    """Navigation after project deletion."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="К списку проектов", callback_data="nav:projects"),
                InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
            ],
        ]
    )


def project_created_kb(project_id: int) -> InlineKeyboardMarkup:
    """Success screen after project creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="К проекту",
                    callback_data=f"project:{project_id}:card",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Category list
# ---------------------------------------------------------------------------


def category_list_kb(categories: list[Category], project_id: int, page: int = 1) -> InlineKeyboardMarkup:
    """Category list with pagination. Item cb: category:{id}:card."""
    kb, _ = paginate(
        items=categories,
        page=page,
        cb_prefix=f"categories:{project_id}",
        item_text="name",
        item_cb="category:{id}:card",
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
                InlineKeyboardButton(text="Ключевые фразы", callback_data=f"category:{cid}:keywords"),
                InlineKeyboardButton(text="Описание", callback_data=f"category:{cid}:description"),
            ],
            [
                InlineKeyboardButton(text="Цены", callback_data=f"category:{cid}:prices"),
                InlineKeyboardButton(text="Настройки", callback_data=f"category:{cid}:content_settings"),
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
                    text="Подтвердить удаление",
                    callback_data=f"category:{category_id}:delete:confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"category:{category_id}:card"),
            ],
        ]
    )


def category_created_kb(category_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Success screen after category creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="К категории",
                    callback_data=f"category:{category_id}:card",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(text="К категориям", callback_data=f"project:{project_id}:categories"),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Connection list
# ---------------------------------------------------------------------------

_PLATFORM_ICONS: dict[str, str] = {
    "wordpress": "WP",
    "telegram": "TG",
    "vk": "VK",
    "pinterest": "Pin",
}


def connection_list_kb(connections: list[PlatformConnection], project_id: int) -> InlineKeyboardMarkup:
    """Connection list with platform status + add buttons (UX_TOOLBOX.md section 5.1)."""
    rows: list[list[InlineKeyboardButton]] = []

    for conn in connections:
        icon = _PLATFORM_ICONS.get(conn.platform_type, conn.platform_type)
        status = "\U0001f7e2" if conn.status == "active" else "\U0001f534"
        text = f"{status} {icon}: {conn.identifier}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"conn:{conn.id}:manage")])

    # Add platform buttons
    rows.append(
        [
            InlineKeyboardButton(text="+ WordPress", callback_data=f"conn:{project_id}:add:wordpress"),
            InlineKeyboardButton(text="+ Telegram", callback_data=f"conn:{project_id}:add:telegram"),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(text="+ VK", callback_data=f"conn:{project_id}:add:vk"),
            InlineKeyboardButton(text="+ Pinterest", callback_data=f"conn:{project_id}:add:pinterest"),
        ]
    )
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
    """Manage single connection — delete + back."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить подключение",
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
                    text="Подтвердить удаление",
                    callback_data=f"conn:{conn_id}:delete:confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"conn:{conn_id}:manage"),
            ],
        ]
    )


def vk_group_select_kb(groups: list[dict[str, Any]], project_id: int) -> InlineKeyboardMarkup:
    """VK group selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups:
        gid = group.get("id", 0)
        name = str(group.get("name", f"Group {gid}"))
        rows.append([InlineKeyboardButton(text=name, callback_data=f"vk:group:{gid}:select")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pinterest_board_select_kb(boards: list[dict[str, Any]], project_id: int) -> InlineKeyboardMarkup:
    """Pinterest board selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for board in boards:
        bid = board.get("id", "")
        name = str(board.get("name", f"Board {bid}"))
        rows.append([InlineKeyboardButton(text=name, callback_data=f"pinterest:board:{bid}")])
    rows.append([InlineKeyboardButton(text="Отмена", callback_data=f"conn:{project_id}:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


def keywords_empty_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Empty keywords screen (UX_TOOLBOX section 9.1)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Начать подбор", callback_data=f"kw:{cat_id}:generate")],
            [InlineKeyboardButton(text="Загрузить свои фразы", callback_data=f"kw:{cat_id}:upload")],
            [InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card")],
        ]
    )


def keywords_summary_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Keywords summary with actions (UX_TOOLBOX section 9.2)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Посмотреть кластеры", callback_data=f"kw:{cat_id}:clusters")],
            [InlineKeyboardButton(text="Скачать все (CSV)", callback_data=f"kw:{cat_id}:download")],
            [InlineKeyboardButton(text="Добавить ещё фразы", callback_data=f"kw:{cat_id}:generate")],
            [InlineKeyboardButton(text="Загрузить свои фразы", callback_data=f"kw:{cat_id}:upload")],
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


def keywords_quantity_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Keyword quantity selection (UX_TOOLBOX section 9.5)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="50 фраз \u2014 50 токенов", callback_data=f"kw:{cat_id}:qty_50")],
            [InlineKeyboardButton(text="100 фраз \u2014 100 токенов", callback_data=f"kw:{cat_id}:qty_100")],
            [InlineKeyboardButton(text="150 фраз \u2014 150 токенов", callback_data=f"kw:{cat_id}:qty_150")],
            [InlineKeyboardButton(text="200 фраз \u2014 200 токенов", callback_data=f"kw:{cat_id}:qty_200")],
        ]
    )


def keywords_confirm_kb(cat_id: int, cost: int, balance: int) -> InlineKeyboardMarkup:
    """Keyword generation cost confirmation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, сгенерировать",
                    callback_data=f"kw:{cat_id}:confirm_yes",
                    style=ButtonStyle.SUCCESS,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"kw:{cat_id}:confirm_no"),
            ],
        ]
    )


def keywords_saved_answers_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Prompt to use saved answers or start fresh (UX_TOOLBOX section 9.5)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Использовать сохранённые",
                    callback_data=f"kw:{cat_id}:use_saved",
                ),
                InlineKeyboardButton(
                    text="Пройти заново",
                    callback_data=f"kw:{cat_id}:generate:new",
                ),
            ],
        ]
    )


def keywords_results_kb(cat_id: int) -> InlineKeyboardMarkup:
    """Post-generation results navigation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Посмотреть кластеры", callback_data=f"kw:{cat_id}:clusters")],
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
    gen_label = f"Сгенерировать AI ({COST_DESCRIPTION} токенов)"
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=gen_label, callback_data=f"desc:{cat_id}:generate")],
        [InlineKeyboardButton(text="Написать вручную", callback_data=f"desc:{cat_id}:manual")],
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


def description_confirm_kb(cat_id: int, balance: int) -> InlineKeyboardMarkup:
    """AI description generation cost confirmation (UX_TOOLBOX section 10.1).

    Shows [Пополнить баланс] instead of [Да, сгенерировать] when balance < 20 (E01).
    """
    cost = COST_DESCRIPTION
    if balance >= cost:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="Да, сгенерировать",
                        callback_data=f"desc:{cat_id}:confirm_yes",
                        style=ButtonStyle.SUCCESS,
                    ),
                    InlineKeyboardButton(text="Отмена", callback_data=f"desc:{cat_id}:confirm_no"),
                ],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Пополнить баланс", callback_data="nav:tokens"),
                InlineKeyboardButton(text="Отмена", callback_data=f"desc:{cat_id}:confirm_no"),
            ],
        ]
    )


def description_review_kb(cat_id: int, regen_count: int) -> InlineKeyboardMarkup:
    """Review generated description: save / regenerate / cancel (UX_TOOLBOX section 10.1).

    After 2 free regenerations, button shows cost (FSM_SPEC 2.2).
    Regenerate is always available (paid after limit).
    """
    regen_text = "Перегенерировать"
    if regen_count >= 2:
        regen_text = f"Перегенерировать ({COST_DESCRIPTION} токенов)"

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
                InlineKeyboardButton(text=regen_text, callback_data=f"desc:{cat_id}:review_regen"),
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


# ---------------------------------------------------------------------------
# Content settings
# ---------------------------------------------------------------------------

_TEXT_STYLES: list[str] = [
    "Рекламный",
    "Мотивационный",
    "Дружелюбный",
    "Разговорный",
    "Профессиональный",
    "Креативный",
    "Информативный",
    "С юмором",
    "Мужской",
    "Женский",
]

_IMAGE_STYLES: list[str] = [
    "Фотореализм",
    "Аниме",
    "Масло",
    "Акварель",
    "Мультяшный",
    "Минимализм",
]


def content_settings_kb(cat_id: int, settings: dict[str, Any]) -> InlineKeyboardMarkup:
    """Main content settings screen (UX_TOOLBOX section 12)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Длина статьи", callback_data=f"settings:{cat_id}:text_length")],
            [InlineKeyboardButton(text="Стиль текста", callback_data=f"settings:{cat_id}:text_style")],
            [
                InlineKeyboardButton(
                    text="Количество изображений",
                    callback_data=f"settings:{cat_id}:img_count",
                ),
            ],
            [InlineKeyboardButton(text="Стиль изображений", callback_data=f"settings:{cat_id}:img_style")],
            [InlineKeyboardButton(text="К категории", callback_data=f"category:{cat_id}:card")],
        ]
    )


def text_style_kb(cat_id: int, selected: list[str]) -> InlineKeyboardMarkup:
    """Multi-select text style grid (UX_TOOLBOX section 12.2)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, style in enumerate(_TEXT_STYLES):
        prefix = "\u2713 " if style in selected else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{style}",
                callback_data=f"settings:{cat_id}:ts:{idx}",
            ),
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="Сохранить",
                callback_data=f"settings:{cat_id}:ts_save",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_count_kb(cat_id: int, current: int) -> InlineKeyboardMarkup:
    """Image count selection 0-10 (UX_TOOLBOX section 12.3)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in range(11):
        text = f"\u2022{n}\u2022" if n == current else str(n)
        row.append(
            InlineKeyboardButton(
                text=text,
                callback_data=f"settings:{cat_id}:imgcnt:{n}",
            ),
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(text="К настройкам", callback_data=f"category:{cat_id}:content_settings")],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def image_style_kb(cat_id: int, current: str | None) -> InlineKeyboardMarkup:
    """Image style selection grid (UX_TOOLBOX section 12.4)."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, style in enumerate(_IMAGE_STYLES):
        prefix = "\u2713 " if style == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{style}",
                callback_data=f"settings:{cat_id}:is:{idx}",
            ),
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [InlineKeyboardButton(text="К настройкам", callback_data=f"category:{cat_id}:content_settings")],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
