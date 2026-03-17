"""Inline keyboards for Dashboard, Projects, Categories, Connections."""

import math
from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts.legal import PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL
from db.models import Category, PlatformConnection, Project
from keyboards.pagination import PAGE_SIZE, _safe_cb, paginate

# ---------------------------------------------------------------------------
# Common: cancel keyboard for FSM text input states
# ---------------------------------------------------------------------------


def menu_kb() -> InlineKeyboardMarkup:
    """Single-button keyboard to return to dashboard. Use for dead-end messages."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Меню", callback_data="nav:dashboard")],
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
    """Consent screen: privacy policy, terms (URL links), accept button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика конфиденциальности", url=PRIVACY_POLICY_URL)],
            [InlineKeyboardButton(text="Оферта", url=TERMS_OF_SERVICE_URL)],
            [InlineKeyboardButton(text="Принимаю", callback_data="legal:consent:accept")],
        ]
    )


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


def dashboard_kb(
    *,
    is_admin: bool = False,
) -> InlineKeyboardMarkup:
    """Dashboard keyboard with nav row (Projects | Profile | Tokens)."""
    rows: list[list[InlineKeyboardButton]] = []

    # Nav row
    rows.append(
        [
            InlineKeyboardButton(
                text="Проекты",
                callback_data="nav:projects",
            ),
            InlineKeyboardButton(
                text="Профиль",
                callback_data="nav:profile",
            ),
            InlineKeyboardButton(
                text="Тарифы",
                callback_data="nav:tokens",
            ),
        ]
    )

    if is_admin:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Админка",
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


def project_card_kb(project_id: int, *, has_keywords: bool) -> InlineKeyboardMarkup:
    """Project card action buttons (UX_TOOLBOX.md section 3.1).

    Pipeline and scheduler buttons are shown only when ``has_keywords=True``
    (at least one category with keywords exists).
    """
    pid = project_id
    rows: list[list[InlineKeyboardButton]] = []

    if has_keywords:
        rows.append([
            InlineKeyboardButton(
                text="Написать статью",
                callback_data=f"pipeline:article:project:{pid}",
                style=ButtonStyle.PRIMARY,
            ),
            InlineKeyboardButton(
                text="Создать пост",
                callback_data=f"pipeline:social:project:{pid}",
                style=ButtonStyle.PRIMARY,
            ),
        ])

    rows.append([
        InlineKeyboardButton(text="Настройки", callback_data=f"project:{pid}:edit"),
        InlineKeyboardButton(text="Категории", callback_data=f"project:{pid}:categories"),
    ])

    rows.append([
        InlineKeyboardButton(text="Контент", callback_data=f"project:{pid}:content_settings"),
    ])

    if has_keywords:
        rows.append([
            InlineKeyboardButton(text="Подключения", callback_data=f"project:{pid}:connections"),
            InlineKeyboardButton(text="Планировщик", callback_data=f"project:{pid}:scheduler"),
        ])
    else:
        rows.append([
            InlineKeyboardButton(text="Подключения", callback_data=f"project:{pid}:connections"),
        ])

    rows.append([
        InlineKeyboardButton(
            text="Удалить проект",
            callback_data=f"project:{pid}:delete",
            style=ButtonStyle.DANGER,
        ),
    ])
    rows.append([InlineKeyboardButton(text="\u2b05\ufe0f К проектам", callback_data="nav:projects")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


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
]


def project_edit_kb(
    project_id: int,
    completed: dict[str, bool] | None = None,
) -> InlineKeyboardMarkup:
    """Edit screen: field buttons in 2-column grid + delete + back.

    ``completed`` maps field names to filled status; filled fields get a
    checkmark prefix on the button label.
    """
    pid = project_id
    filled = completed or {}
    rows: list[list[InlineKeyboardButton]] = []

    # 2-column layout for fields
    for i in range(0, len(_EDIT_FIELDS), 2):
        row: list[InlineKeyboardButton] = []
        for field, label in _EDIT_FIELDS[i : i + 2]:
            prefix = "\u2705 " if filled.get(field) else ""
            row.append(
                InlineKeyboardButton(
                    text=f"{prefix}{label}",
                    callback_data=f"project:{pid}:edit:{field}",
                )
            )
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
                    text="Подтвердить удаление",
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

_PLATFORM_LABELS_RU: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Телеграм",
    "vk": "ВКонтакте",
    "pinterest": "Пинтерест",
}


def format_connection_display(conn: Any, *, with_status: bool = False) -> str:
    """Human-readable connection label.

    WordPress: domain (e.g. "smoketest.instawp.site")
    Social: Russian name (e.g. "ВКонтакте", "Пинтерест", "Телеграм")
    VK with group_name in metadata: "ВКонтакте: Group Name"
    """
    label: str = _PLATFORM_LABELS_RU.get(conn.platform_type, conn.platform_type)
    if conn.platform_type == "wordpress":
        text = str(conn.identifier)
    elif conn.platform_type == "vk":
        metadata = getattr(conn, "metadata", None) or {}
        group_name = metadata.get("group_name") if isinstance(metadata, dict) else None
        text = f"{label}: {group_name}" if group_name else label
    else:
        text = label
    if with_status:
        status = "\u2713" if getattr(conn, "status", None) == "active" else "\u2717"
        return f"{status} {text}"
    return text


def connection_list_kb(connections: list[PlatformConnection], project_id: int) -> InlineKeyboardMarkup:
    """Connection list with platform status + add buttons (UX_TOOLBOX.md section 5.1).

    Rule: 1 project = max 1 connection per platform type.
    "Add" buttons are hidden for platform types that already have a connection.
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Determine which platform types already exist
    connected_types = {conn.platform_type for conn in connections}

    for conn in connections:
        text = format_connection_display(conn, with_status=True)
        rows.append([InlineKeyboardButton(text=text, callback_data=f"conn:{conn.id}:manage")])

    # Add platform buttons — only for types NOT yet connected
    _ALL_PLATFORMS = [
        ("wordpress", "Подключить сайт"),
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


# ---------------------------------------------------------------------------
# Project content settings (psettings:{pid}:{target}:*)
# target = "d" (default) | "wordpress" | "telegram" | "vk" | "pinterest"
# ---------------------------------------------------------------------------

# Platform emoji mapping for button labels
_PLATFORM_EMOJI: dict[str, str] = {
    "wordpress": "\U0001f310",
    "telegram": "\u2708",
    "vk": "\U0001f535",
    "pinterest": "\U0001f4cc",
}

# Human-readable platform names
_PLATFORM_NAMES: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Telegram",
    "vk": "VK",
    "pinterest": "Pinterest",
}


def project_content_settings_kb(
    pid: int,
    connected_platforms: list[str] | None = None,
) -> InlineKeyboardMarkup:
    """Main content settings screen with platform tabs (grid layout)."""
    default_btn = InlineKeyboardButton(
        text="\u2699 \u041f\u043e \u0443\u043c\u043e\u043b\u0447\u0430\u043d\u0438\u044e",
        callback_data=f"psettings:{pid}:d:card",
    )
    rows: list[list[InlineKeyboardButton]] = [[default_btn]]
    # Add connected platforms in pairs
    platforms = connected_platforms or []
    pair: list[InlineKeyboardButton] = []
    for pt in platforms:
        emoji = _PLATFORM_EMOJI.get(pt, "")
        name = _PLATFORM_NAMES.get(pt, pt.capitalize())
        pair.append(
            InlineKeyboardButton(
                text=f"{emoji} {name}",
                callback_data=f"psettings:{pid}:{pt}:card",
            )
        )
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)
    back_btn = InlineKeyboardButton(
        text="\u041a \u043f\u0440\u043e\u0435\u043a\u0442\u0443",
        callback_data=f"project:{pid}:card",
    )
    rows.append([back_btn])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_platform_card_kb(pid: int, target: str) -> InlineKeyboardMarkup:
    """Platform card: [Text] [Images] / [Reset] [Back]."""
    p = f"psettings:{pid}:{target}"
    back_cb = f"psettings:{pid}:back"
    text_btn = InlineKeyboardButton(
        text="\u270f \u0422\u0435\u043a\u0441\u0442", callback_data=f"{p}:text",
    )
    img_btn = InlineKeyboardButton(
        text="\U0001f5bc \u0418\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u044f",
        callback_data=f"{p}:images",
    )
    rows: list[list[InlineKeyboardButton]] = [[text_btn, img_btn]]
    if target != "d":
        reset_btn = InlineKeyboardButton(
            text="\u274c \u0421\u0431\u0440\u043e\u0441\u0438\u0442\u044c",
            callback_data=f"{p}:reset",
        )
        back_btn = InlineKeyboardButton(
            text="\u2190 \u041a \u043f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0430\u043c",
            callback_data=back_cb,
        )
        rows.append([reset_btn, back_btn])
    else:
        back_btn = InlineKeyboardButton(
            text="\u2190 \u041a \u043f\u043b\u0430\u0442\u0444\u043e\u0440\u043c\u0430\u043c",
            callback_data=back_cb,
        )
        rows.append([back_btn])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _multi_select_grid(
    items: list[str],
    selected: set[str],
    cb_prefix: str,
    back_cb: str,
    *,
    cols: int = 2,
) -> InlineKeyboardMarkup:
    """Generic multi-select grid with checkmark prefix."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, item in enumerate(items):
        prefix = "\u2713 " if item in selected else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{item}",
                callback_data=f"{cb_prefix}:{idx}",
            ),
        )
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _single_select_grid(
    items: list[str],
    current: str | None,
    cb_prefix: str,
    back_cb: str,
    *,
    cols: int = 2,
) -> InlineKeyboardMarkup:
    """Generic single-select grid with checkmark prefix."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for idx, item in enumerate(items):
        prefix = "\u2713 " if item == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{item}",
                callback_data=f"{cb_prefix}:{idx}",
            ),
        )
        if len(row) == cols:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_text_menu_kb(pid: int, target: str = "d") -> InlineKeyboardMarkup:
    """Text settings sub-menu (2x2 grid)."""
    p = f"psettings:{pid}:{target}"
    btn = InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                btn(text="\u0414\u043b\u0438\u043d\u0430", callback_data=f"{p}:words"),
                btn(text="HTML-\u0441\u0442\u0438\u043b\u044c", callback_data=f"{p}:html"),
            ],
            [
                btn(text="\u0421\u0442\u0438\u043b\u044c", callback_data=f"{p}:tstyle"),
                btn(text="\u041d\u0430\u0437\u0430\u0434", callback_data=f"{p}:card"),
            ],
        ]
    )


def project_word_count_kb(pid: int, current: int | None, target: str = "d") -> InlineKeyboardMarkup:
    """Word count preset selection."""
    from bot.texts.content_options import WORD_COUNTS

    p = f"psettings:{pid}:{target}"
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for wc in WORD_COUNTS:
        prefix = "\u2713 " if wc == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{wc}",
                callback_data=f"{p}:wc:{wc}",
            ),
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", callback_data=f"{p}:text")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_html_style_kb(pid: int, current: str | None, target: str = "d") -> InlineKeyboardMarkup:
    """HTML style single-select grid."""
    from bot.texts.content_options import HTML_STYLES

    p = f"psettings:{pid}:{target}"
    return _single_select_grid(
        HTML_STYLES,
        current,
        f"{p}:hs",
        f"{p}:text",
    )


def project_text_style_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Text style multi-select grid."""
    from bot.texts.content_options import TEXT_STYLES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        TEXT_STYLES,
        selected,
        f"{p}:ts",
        f"{p}:text",
    )


def project_image_menu_kb(pid: int, target: str = "d") -> InlineKeyboardMarkup:
    """Image settings sub-menu (2x5 grid)."""
    p = f"psettings:{pid}:{target}"
    btn = InlineKeyboardButton
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [btn(text="\u041f\u0440\u0435\u0432\u044c\u044e", callback_data=f"{p}:pfmt"),
             btn(text="\u0424\u043e\u0440\u043c\u0430\u0442\u044b", callback_data=f"{p}:afmts")],
            [btn(text="\u0421\u0442\u0438\u043b\u044c", callback_data=f"{p}:istyle"),
             btn(text="\u041a\u043e\u043b-\u0432\u043e", callback_data=f"{p}:icount")],
            [btn(text="\u0422\u0435\u043a\u0441\u0442/\u0444\u043e\u0442\u043e", callback_data=f"{p}:tximg"),
             btn(text="\u041a\u0430\u043c\u0435\u0440\u0430", callback_data=f"{p}:camera")],
            [btn(text="\u0420\u0430\u043a\u0443\u0440\u0441", callback_data=f"{p}:angle"),
             btn(text="\u041a\u0430\u0447\u0435\u0441\u0442\u0432\u043e", callback_data=f"{p}:quality")],
            [btn(text="\u0422\u043e\u043d\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u044c", callback_data=f"{p}:tone"),
             btn(text="\u041d\u0430\u0437\u0430\u0434", callback_data=f"{p}:card")],
        ]
    )


def project_preview_format_kb(pid: int, current: str | None, target: str = "d") -> InlineKeyboardMarkup:
    """Preview format single-select (aspect ratios)."""
    from bot.texts.content_options import ASPECT_RATIOS

    p = f"psettings:{pid}:{target}"
    return _single_select_grid(
        ASPECT_RATIOS,
        current,
        f"{p}:pf",
        f"{p}:images",
        cols=5,
    )


def project_article_format_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Article format multi-select (aspect ratios)."""
    from bot.texts.content_options import ASPECT_RATIOS

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        ASPECT_RATIOS,
        selected,
        f"{p}:af",
        f"{p}:images",
        cols=5,
    )


def project_image_style_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Image style multi-select grid."""
    from bot.texts.content_options import IMAGE_STYLES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        IMAGE_STYLES,
        selected,
        f"{p}:is",
        f"{p}:images",
    )


def project_image_count_kb(pid: int, current: int | None, target: str = "d") -> InlineKeyboardMarkup:
    """Image count selection 0-10."""
    p = f"psettings:{pid}:{target}"
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in range(11):
        prefix = "\u2713 " if n == current else ""
        row.append(
            InlineKeyboardButton(
                text=f"{prefix}{n}",
                callback_data=f"{p}:ic:{n}",
            ),
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", callback_data=f"{p}:images")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_text_on_image_kb(pid: int, current: int | None, target: str = "d") -> InlineKeyboardMarkup:
    """Text-on-image percentage selection."""
    from bot.texts.content_options import TEXT_ON_IMAGE

    p = f"psettings:{pid}:{target}"
    rows: list[list[InlineKeyboardButton]] = []
    for pct in TEXT_ON_IMAGE:
        prefix = "\u2713 " if pct == current else ""
        rows.append([
            InlineKeyboardButton(
                text=f"{prefix}{pct}%",
                callback_data=f"{p}:to:{pct}",
            ),
        ])
    rows.append([InlineKeyboardButton(text="\u041d\u0430\u0437\u0430\u0434", callback_data=f"{p}:images")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_camera_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Camera multi-select grid."""
    from bot.texts.content_options import CAMERAS

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        CAMERAS,
        selected,
        f"{p}:cm",
        f"{p}:images",
    )


def project_angle_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Angle multi-select grid."""
    from bot.texts.content_options import ANGLES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        ANGLES,
        selected,
        f"{p}:an",
        f"{p}:images",
    )


def project_quality_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Quality multi-select grid."""
    from bot.texts.content_options import QUALITY

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        QUALITY,
        selected,
        f"{p}:ql",
        f"{p}:images",
        cols=3,
    )


def project_tone_kb(pid: int, selected: set[str], target: str = "d") -> InlineKeyboardMarkup:
    """Tone multi-select grid."""
    from bot.texts.content_options import TONES

    p = f"psettings:{pid}:{target}"
    return _multi_select_grid(
        TONES,
        selected,
        f"{p}:tn",
        f"{p}:images",
        cols=3,
    )


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
            InlineKeyboardButton(text="Политика", url=PRIVACY_POLICY_URL),
            InlineKeyboardButton(text="Оферта", url=TERMS_OF_SERVICE_URL),
        ],
        [InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def notifications_kb(
    notify_publications: bool,
    notify_balance: bool,
    notify_news: bool,
) -> InlineKeyboardMarkup:
    """Notification toggle keyboard."""

    def _toggle(label: str, enabled: bool, key: str) -> InlineKeyboardButton:
        mark = "\u2713" if enabled else "\u2717"
        return InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"profile:notify:{key}")

    rows = [
        [_toggle("Публикации", notify_publications, "publications")],
        [_toggle("Баланс", notify_balance, "balance")],
        [_toggle("Новости", notify_news, "news")],
        [InlineKeyboardButton(text="К профилю", callback_data="nav:profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def referral_kb() -> InlineKeyboardMarkup:
    """Referral program keyboard (link shown inline in message text)."""
    rows = [
        [InlineKeyboardButton(text="К профилю", callback_data="nav:profile")],
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
        [InlineKeyboardButton(text="К профилю", callback_data="nav:profile")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Tariffs & Payments (UX_TOOLBOX section 15)
# ---------------------------------------------------------------------------


def tariffs_kb() -> InlineKeyboardMarkup:
    """Package selection keyboard. Profi is PRIMARY (best value)."""
    from services.payments.packages import PACKAGES

    rows: list[list[InlineKeyboardButton]] = []
    for name, pkg in PACKAGES.items():
        style = ButtonStyle.PRIMARY if name == "profi" else None
        btn = InlineKeyboardButton(
            text=pkg.label,
            callback_data=f"tariff:{name}:buy",
        )
        if style:
            btn.style = style
        rows.append([btn])
    rows.append([InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_method_kb(package_name: str) -> InlineKeyboardMarkup:
    """Payment method selection: Stars or YooKassa."""
    rows = [
        [InlineKeyboardButton(text="Telegram Stars", callback_data=f"tariff:{package_name}:stars")],
        [InlineKeyboardButton(text="ЮKassa (карта)", callback_data=f"tariff:{package_name}:yookassa")],
        [InlineKeyboardButton(text="Назад", callback_data="nav:tokens")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def yookassa_link_kb(url: str, package_name: str) -> InlineKeyboardMarkup:
    """YooKassa payment link + back button."""
    rows = [
        [InlineKeyboardButton(text="Перейти к оплате", url=url)],
        [InlineKeyboardButton(text="Назад", callback_data=f"tariff:{package_name}:buy")],
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


def scheduler_type_kb(project_id: int) -> InlineKeyboardMarkup:
    """Scheduler type selection: articles or social posts."""
    pid = project_id
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Статьи на сайт",
                    callback_data=f"project:{pid}:sched_articles",
                ),
                InlineKeyboardButton(
                    text="Посты в соцсети",
                    callback_data=f"project:{pid}:sched_social",
                ),
            ],
            [InlineKeyboardButton(text="\u2b05\ufe0f К проекту", callback_data=f"project:{pid}:card")],
        ]
    )


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
    """Article (WordPress) connection list with schedule summaries."""
    rows: list[list[InlineKeyboardButton]] = []
    for conn in connections:
        sched = schedules.get(conn.id)
        display = format_connection_display(conn)
        if sched and sched.enabled:
            days_str = ", ".join(_DAY_LABELS.get(d) or d for d in sched.schedule_days)
            label = f"{display} ({days_str})"
        else:
            label = f"{display} (нет расписания)"
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
                text="Назад",
                callback_data=f"project:{project_id}:sched_articles",
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
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"scheduler:{cat_id}:conn_list")])
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
        display = format_connection_display(conn)
        if sched and sched.enabled:
            days_str = ", ".join(_DAY_LABELS.get(d) or d for d in sched.schedule_days)
            cross_count = len(sched.cross_post_connection_ids) if sched.cross_post_connection_ids else 0
            cross_badge = f" +{cross_count} кросс" if cross_count else ""
            label = f"{display} ({days_str}{cross_badge})"
        else:
            label = f"{display} (нет расписания)"
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
                text="Назад",
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
        display = format_connection_display(conn)
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{mark}{display}",
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
    rows.append([InlineKeyboardButton(text="Назад", callback_data=f"scheduler:{cat_id}:social_conn_list")])
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
        [InlineKeyboardButton(text="Статус API", callback_data="admin:api_status")],
        [InlineKeyboardButton(text="Просмотр пользователя", callback_data="admin:user_lookup")],
        [InlineKeyboardButton(text="Рассылка", callback_data="admin:broadcast")],
        [InlineKeyboardButton(text="Затраты API", callback_data="admin:api_costs")],
        [InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_actions_kb(user_id: int, *, is_blocked: bool) -> InlineKeyboardMarkup:
    """User management action buttons for admin user card."""
    rows = [
        [
            InlineKeyboardButton(text="Начислить", callback_data=f"admin:user:{user_id}:credit"),
            InlineKeyboardButton(text="Списать", callback_data=f"admin:user:{user_id}:debit"),
        ],
    ]
    if is_blocked:
        rows.append(
            [InlineKeyboardButton(text="Разблокировать", callback_data=f"admin:user:{user_id}:unblock")],
        )
    else:
        rows.append(
            [InlineKeyboardButton(text="Заблокировать", callback_data=f"admin:user:{user_id}:block")],
        )
    rows.append(
        [InlineKeyboardButton(text="Активность", callback_data=f"admin:user:{user_id}:activity")],
    )
    rows.append(
        [InlineKeyboardButton(text="\u2b05\ufe0f К панели", callback_data="admin:panel")],
    )
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
