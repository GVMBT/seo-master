"""Inline keyboards for Dashboard, Projects, Categories, Connections."""

import math
from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, PlatformConnection, Project
from keyboards.pagination import PAGE_SIZE, _safe_cb, paginate
from services.tokens import COST_DESCRIPTION

# ---------------------------------------------------------------------------
# Common: cancel keyboard for FSM text input states
# ---------------------------------------------------------------------------


def menu_kb() -> InlineKeyboardMarkup:
    """Single-button keyboard to return to dashboard. Use for dead-end messages."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\U0001f4cb \u041c\u0435\u043d\u044e", callback_data="nav:dashboard")],
        ]
    )


def cancel_kb(callback_data: str = "fsm:cancel") -> InlineKeyboardMarkup:
    """Inline cancel button for text input FSM states.

    Provides a visible [Отмена] button so users do not have to
    type the magic word.  The existing text-based "Отмена" handler
    remains as a fallback.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=callback_data)],
        ]
    )


def consent_kb() -> InlineKeyboardMarkup:
    """Consent screen: privacy policy, terms, accept button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика конфиденциальности", callback_data="legal:consent:privacy")],
            [InlineKeyboardButton(text="Оферта", callback_data="legal:consent:terms")],
            [InlineKeyboardButton(text="Принимаю", callback_data="legal:consent:accept")],
        ]
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def dashboard_kb(
    has_wp: bool,
    has_social: bool,
    balance: int,
    *,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    """Dashboard keyboard with pipeline CTAs and nav row.

    Article button is always PRIMARY.
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
        rows.append(
            [
                InlineKeyboardButton(
                    text="Написать статью на сайт",
                    callback_data="pipeline:article:start",
                    style=ButtonStyle.PRIMARY,
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

    # Nav row
    rows.append(
        [
            InlineKeyboardButton(
                text="\U0001f4c1 Мои проекты",
                callback_data="nav:projects",
            ),
            InlineKeyboardButton(
                text="\U0001f464 Профиль",
                callback_data="nav:profile",
            ),
            InlineKeyboardButton(
                text="\U0001f4b0 Токены",
                callback_data="nav:tokens",
            ),
        ]
    )

    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="\U0001f6e1 Админка",
                    callback_data="admin:panel",
                ),
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
                    text="Отмена",
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
            InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard"),
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
            [InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard")],
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
            ],
            [
                InlineKeyboardButton(text="Статьи", callback_data=f"project:{pid}:sched_articles"),
                InlineKeyboardButton(text="Соцсети", callback_data=f"project:{pid}:sched_social"),
            ],
            [
                InlineKeyboardButton(
                    text="Удалить проект",
                    callback_data=f"project:{pid}:delete",
                    style=ButtonStyle.DANGER,
                ),
            ],
            [InlineKeyboardButton(text="\u2b05\ufe0f К проектам", callback_data="nav:projects")],
        ]
    )


# ---------------------------------------------------------------------------
# Project edit
# ---------------------------------------------------------------------------

_EDIT_FIELDS: list[tuple[str, str]] = [
    ("name", "Название"),
    ("company_name", "Компания"),
    ("specialization", "Специализация"),
    ("description", "Описание"),
    ("advantages", "Преимущества"),
    ("experience", "Опыт"),
    ("website_url", "Сайт"),
    ("company_city", "Город"),
    ("company_phone", "Телефон"),
    ("company_email", "Эл. почта"),
    ("company_address", "Адрес"),
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
            InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{pid}:card"),
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
                InlineKeyboardButton(text="\u2b05\ufe0f К проектам", callback_data="nav:projects"),
                InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard"),
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
                InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard"),
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
            InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{project_id}:card"),
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
            [InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{project_id}:card")],
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
    """Connection list with platform status + add buttons (UX_TOOLBOX.md section 5.1).

    Rule: 1 project = max 1 connection per platform type.
    "Add" buttons are hidden for platform types that already have a connection.
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Determine which platform types already exist
    connected_types = {conn.platform_type for conn in connections}

    for conn in connections:
        icon = _PLATFORM_ICONS.get(conn.platform_type, conn.platform_type)
        status = "\U0001f7e2" if conn.status == "active" else "\U0001f534"
        text = f"{status} {icon}: {conn.identifier}"
        rows.append([InlineKeyboardButton(text=text, callback_data=f"conn:{conn.id}:manage")])

    # Add platform buttons — only for types NOT yet connected
    _ALL_PLATFORMS = [
        ("wordpress", "Добавить WordPress"),
        ("telegram", "Добавить Telegram"),
        ("vk", "Добавить VK"),
        ("pinterest", "Добавить Pinterest"),
    ]
    add_buttons = [
        InlineKeyboardButton(text=label, callback_data=f"conn:{project_id}:add:{ptype}")
        for ptype, label in _ALL_PLATFORMS
        if ptype not in connected_types
    ]
    # Layout: 2 per row
    for i in range(0, len(add_buttons), 2):
        rows.append(add_buttons[i : i + 2])

    rows.append(
        [
            InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{project_id}:card"),
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


# ---------------------------------------------------------------------------
# Profile (UX_TOOLBOX section 14)
# ---------------------------------------------------------------------------


def profile_kb() -> InlineKeyboardMarkup:
    """Profile main screen keyboard."""
    rows = [
        [InlineKeyboardButton(text="Пополнить баланс", callback_data="nav:tokens", style=ButtonStyle.PRIMARY)],
        [InlineKeyboardButton(text="Уведомления", callback_data="profile:notifications")],
        [InlineKeyboardButton(text="Реферальная программа", callback_data="profile:referral")],
        [
            InlineKeyboardButton(text="Политика", callback_data="profile:privacy"),
            InlineKeyboardButton(text="Оферта", callback_data="profile:terms"),
        ],
        [InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notifications_kb(
    notify_publications: bool,
    notify_balance: bool,
    notify_news: bool,
) -> InlineKeyboardMarkup:
    """Notification toggle keyboard."""

    def _toggle(label: str, enabled: bool, key: str) -> InlineKeyboardButton:
        mark = "\u2705" if enabled else "\u274c"
        return InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"profile:notify:{key}")

    rows = [
        [_toggle("Публикации", notify_publications, "publications")],
        [_toggle("Баланс", notify_balance, "balance")],
        [_toggle("Новости", notify_news, "news")],
        [InlineKeyboardButton(text="\u2b05\ufe0f К профилю", callback_data="nav:profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_kb() -> InlineKeyboardMarkup:
    """Referral program keyboard (link shown inline in message text)."""
    rows = [
        [InlineKeyboardButton(text="\u2b05\ufe0f К профилю", callback_data="nav:profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_account_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation dialog for account deletion (152-FZ compliance)."""
    rows = [
        [
            InlineKeyboardButton(
                text="Да, удалить аккаунт",
                callback_data="account:delete:confirm",
                style=ButtonStyle.DANGER,
            ),
        ],
        [InlineKeyboardButton(text="Отмена", callback_data="account:delete:cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_account_cancelled_kb() -> InlineKeyboardMarkup:
    """Keyboard shown after account deletion is cancelled."""
    rows = [
        [InlineKeyboardButton(text="\u2b05\ufe0f К профилю", callback_data="nav:profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Tariffs & Payments (UX_TOOLBOX section 15)
# ---------------------------------------------------------------------------


def tariffs_kb() -> InlineKeyboardMarkup:
    """Package selection keyboard. Standard is PRIMARY (best value)."""
    from services.payments.packages import PACKAGES

    rows: list[list[InlineKeyboardButton]] = []
    for name, pkg in PACKAGES.items():
        style = ButtonStyle.PRIMARY if name == "standard" else None
        discount = f" {pkg.discount}" if pkg.discount else ""
        btn = InlineKeyboardButton(
            text=f"{pkg.label} — {pkg.tokens} токенов / {pkg.price_rub} руб{discount}",
            callback_data=f"tariff:{name}:buy",
        )
        if style:
            btn.style = style
        rows.append([btn])
    rows.append([InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_kb(package_name: str) -> InlineKeyboardMarkup:
    """Payment method selection: Stars or YooKassa."""
    rows = [
        [InlineKeyboardButton(text="Telegram Stars", callback_data=f"tariff:{package_name}:stars")],
        [InlineKeyboardButton(text="ЮKassa (карта)", callback_data=f"tariff:{package_name}:yookassa")],
        [InlineKeyboardButton(text="\u2b05\ufe0f Назад", callback_data="nav:tokens")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yookassa_link_kb(url: str, package_name: str) -> InlineKeyboardMarkup:
    """YooKassa payment link + back button."""
    rows = [
        [InlineKeyboardButton(text="Перейти к оплате", url=url)],
        [InlineKeyboardButton(text="\u2b05\ufe0f Назад", callback_data=f"tariff:{package_name}:buy")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Scheduler (UX_TOOLBOX section 13)
# ---------------------------------------------------------------------------

_PRESETS: dict[str, tuple[str, list[str], list[str], int]] = {
    "1w": ("1 раз/нед", ["wed"], ["10:00"], 1),
    "3w": ("3 раза/нед", ["mon", "wed", "fri"], ["10:00"], 1),
    "daily": ("Каждый день", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], ["10:00"], 1),
}


def detect_active_preset(schedule_days: list[str], posts_per_day: int) -> str | None:
    """Match current schedule parameters to a preset key.

    Returns preset key ("1w", "3w", "daily") or "manual" if no preset matches.
    Returns None if schedule_days is empty or posts_per_day <= 0 (no schedule).
    """
    if not schedule_days or posts_per_day <= 0:
        return None

    day_set = set(schedule_days)
    for key, (_label, days, _times, ppd) in _PRESETS.items():
        if day_set == set(days) and posts_per_day == ppd:
            return key
    return "manual"


_DAY_LABELS: dict[str, str] = {
    "mon": "Пн",
    "tue": "Вт",
    "wed": "Ср",
    "thu": "Чт",
    "fri": "Пт",
    "sat": "Сб",
    "sun": "Вс",
}


def scheduler_cat_list_kb(categories: list[Any], project_id: int) -> InlineKeyboardMarkup:
    """Category list for scheduler entry."""
    rows: list[list[InlineKeyboardButton]] = []
    for cat in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    text=cat.name,
                    callback_data=f"scheduler:{project_id}:cat:{cat.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{project_id}:card")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduler_social_cat_list_kb(categories: list[Any], project_id: int) -> InlineKeyboardMarkup:
    """Category list for social scheduler entry."""
    rows: list[list[InlineKeyboardButton]] = []
    for cat in categories:
        rows.append(
            [
                InlineKeyboardButton(
                    text=cat.name,
                    callback_data=f"sched_social:{project_id}:cat:{cat.id}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{project_id}:card")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduler_conn_list_kb(
    connections: list[Any],
    schedules: dict[int, Any],
    cat_id: int,
    project_id: int,
) -> InlineKeyboardMarkup:
    """Connection list with schedule summaries."""
    rows: list[list[InlineKeyboardButton]] = []
    for conn in connections:
        sched = schedules.get(conn.id)
        if sched and sched.enabled:
            days_str = ", ".join(_DAY_LABELS.get(d) or d for d in sched.schedule_days)
            label = f"{conn.identifier} ({days_str})"
        else:
            label = f"{conn.identifier} (нет расписания)"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"scheduler:{cat_id}:conn:{conn.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="\u2b05\ufe0f Назад",
                callback_data=f"project:{project_id}:scheduler",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduler_config_kb(
    cat_id: int,
    conn_id: int,
    has_schedule: bool,
    schedule_days: list[str] | None = None,
    posts_per_day: int = 0,
) -> InlineKeyboardMarkup:
    """Schedule config: presets + manual + disable.

    Active preset is auto-detected from schedule_days/posts_per_day.
    If no schedule, "3w" gets PRIMARY as recommendation.
    """
    active_preset = detect_active_preset(schedule_days or [], posts_per_day)
    presets = [("3 раза/неделю", "3w"), ("1 раз/неделю", "1w"), ("Каждый день", "daily")]
    rows: list[list[InlineKeyboardButton]] = []
    for label, key in presets:
        if active_preset and active_preset == key:
            style = ButtonStyle.SUCCESS
            text = f"\u2705 {label}"
        elif not active_preset and key == "3w":
            style = ButtonStyle.PRIMARY
            text = label
        else:
            style = None
            text = label
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"sched:{cat_id}:{conn_id}:preset:{key}",
                    style=style,
                )
            ]
        )
    manual_text = "\u2705 Настроить вручную" if active_preset == "manual" else "Настроить вручную"
    manual_style = ButtonStyle.SUCCESS if active_preset == "manual" else None
    rows.append(
        [
            InlineKeyboardButton(
                text=manual_text,
                callback_data=f"sched:{cat_id}:{conn_id}:manual",
                style=manual_style,
            )
        ]
    )
    if has_schedule:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отключить расписание",
                    callback_data=f"sched:{cat_id}:{conn_id}:disable",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="\u2b05\ufe0f Назад", callback_data=f"scheduler:{cat_id}:conn_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_days_kb(selected: set[str]) -> InlineKeyboardMarkup:
    """Day selection grid for manual schedule setup."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for key, label in _DAY_LABELS.items():
        mark = "\u2713 " if key in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{label}", callback_data=f"sched:day:{key}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(text="Готово", callback_data="sched:days:done"),
            InlineKeyboardButton(text="Отмена", callback_data="sched:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_count_kb() -> InlineKeyboardMarkup:
    """Posts per day selection (1-5)."""
    row = [InlineKeyboardButton(text=str(i), callback_data=f"sched:count:{i}") for i in range(1, 6)]
    cancel_row = [InlineKeyboardButton(text="Отмена", callback_data="sched:cancel")]
    return InlineKeyboardMarkup(inline_keyboard=[row, cancel_row])


_SOCIAL_TYPES = {"telegram", "vk", "pinterest"}


def scheduler_social_conn_list_kb(
    connections: list[Any],
    schedules: dict[int, Any],
    cat_id: int,
    project_id: int,
) -> InlineKeyboardMarkup:
    """Social connection list with cross-post count badges."""
    rows: list[list[InlineKeyboardButton]] = []
    for conn in connections:
        if conn.platform_type not in _SOCIAL_TYPES:
            continue
        sched = schedules.get(conn.id)
        if sched and sched.enabled:
            days_str = ", ".join(_DAY_LABELS.get(d) or d for d in sched.schedule_days)
            cross_count = len(sched.cross_post_connection_ids) if sched.cross_post_connection_ids else 0
            cross_badge = f" +{cross_count} кросс" if cross_count else ""
            label = f"{conn.identifier} ({days_str}{cross_badge})"
        else:
            label = f"{conn.identifier} (нет расписания)"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"sched_social:{cat_id}:conn:{conn.id}",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="\u2b05\ufe0f Назад",
                callback_data=f"project:{project_id}:sched_social",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduler_crosspost_kb(
    cat_id: int,
    conn_id: int,
    social_connections: list[Any],
    selected_ids: list[int],
) -> InlineKeyboardMarkup:
    """Cross-post toggle checkboxes for dependent platforms."""
    rows: list[list[InlineKeyboardButton]] = []
    for conn in social_connections:
        if conn.id == conn_id:
            continue  # skip lead connection
        mark = "\u2713 " if conn.id in selected_ids else ""
        icon = _PLATFORM_ICONS.get(conn.platform_type, conn.platform_type)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{icon}: {conn.identifier}",
                    callback_data=f"sched_xp:{cat_id}:{conn_id}:{conn.id}:toggle",
                )
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                text="Сохранить",
                callback_data=f"sched_xp:{cat_id}:{conn_id}:save",
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(
                text="Отмена",
                callback_data=f"sched_social:{cat_id}:conn:{conn_id}",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def scheduler_social_config_kb(
    cat_id: int,
    conn_id: int,
    has_schedule: bool,
    has_other_social: bool = False,
    schedule_days: list[str] | None = None,
    posts_per_day: int = 0,
) -> InlineKeyboardMarkup:
    """Schedule config for social connections: presets + manual + cross-post + disable.

    Active preset is auto-detected from schedule_days/posts_per_day.
    If no schedule, "3w" gets PRIMARY as recommendation.
    """
    active_preset = detect_active_preset(schedule_days or [], posts_per_day)
    presets = [("3 раза/неделю", "3w"), ("1 раз/неделю", "1w"), ("Каждый день", "daily")]
    rows: list[list[InlineKeyboardButton]] = []
    for label, key in presets:
        if active_preset and active_preset == key:
            style = ButtonStyle.SUCCESS
            text = f"\u2705 {label}"
        elif not active_preset and key == "3w":
            style = ButtonStyle.PRIMARY
            text = label
        else:
            style = None
            text = label
        rows.append(
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=f"sched:{cat_id}:{conn_id}:preset:{key}",
                    style=style,
                )
            ]
        )
    manual_text = "\u2705 Настроить вручную" if active_preset == "manual" else "Настроить вручную"
    manual_style = ButtonStyle.SUCCESS if active_preset == "manual" else None
    rows.append(
        [
            InlineKeyboardButton(
                text=manual_text,
                callback_data=f"sched:{cat_id}:{conn_id}:manual",
                style=manual_style,
            )
        ]
    )
    if has_schedule and has_other_social:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Кросс-постинг",
                    callback_data=f"sched_xp:{cat_id}:{conn_id}:config",
                )
            ]
        )
    if has_schedule:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Отключить расписание",
                    callback_data=f"sched:{cat_id}:{conn_id}:disable",
                    style=ButtonStyle.DANGER,
                )
            ]
        )
    rows.append([InlineKeyboardButton(text="\u2b05\ufe0f Назад", callback_data=f"scheduler:{cat_id}:social_conn_list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def schedule_times_kb(selected: set[str], required: int) -> InlineKeyboardMarkup:
    """Time slot grid (06:00-23:00). Shows selected count vs required."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for hour in range(6, 24):
        time_str = f"{hour:02d}:00"
        mark = "\u2713 " if time_str in selected else ""
        row.append(InlineKeyboardButton(text=f"{mark}{time_str}", callback_data=f"sched:time:{time_str}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    done_text = f"Готово ({len(selected)}/{required})"
    rows.append(
        [
            InlineKeyboardButton(text=done_text, callback_data="sched:times:done"),
            InlineKeyboardButton(text="Отмена", callback_data="sched:cancel"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Admin (UX_TOOLBOX section 16)
# ---------------------------------------------------------------------------


def admin_panel_kb() -> InlineKeyboardMarkup:
    """Admin panel main keyboard."""
    rows = [
        [InlineKeyboardButton(text="Мониторинг", callback_data="admin:monitoring")],
        [InlineKeyboardButton(text="Просмотр пользователя", callback_data="admin:user_lookup")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="Затраты API", callback_data="admin:api_costs")],
        [InlineKeyboardButton(text="\U0001f4cb Главное меню", callback_data="nav:dashboard")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_audience_kb() -> InlineKeyboardMarkup:
    """Broadcast audience selection."""
    rows = [
        [InlineKeyboardButton(text="Все пользователи", callback_data="broadcast:audience:all")],
        [InlineKeyboardButton(text="Активные 7 дней", callback_data="broadcast:audience:active_7d")],
        [InlineKeyboardButton(text="Активные 30 дней", callback_data="broadcast:audience:active_30d")],
        [InlineKeyboardButton(text="Оплатившие", callback_data="broadcast:audience:paid")],
        [InlineKeyboardButton(text="Отмена", callback_data="admin:panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def broadcast_confirm_kb() -> InlineKeyboardMarkup:
    """Broadcast confirm/cancel."""
    rows = [
        [InlineKeyboardButton(text="Отправить", callback_data="broadcast:send", style=ButtonStyle.DANGER)],
        [InlineKeyboardButton(text="Отмена", callback_data="admin:panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
