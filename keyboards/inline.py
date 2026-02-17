"""Inline keyboards for Dashboard, Projects, Categories, Connections."""

from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, PlatformConnection, Project
from keyboards.pagination import paginate

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
        rows.append([
            InlineKeyboardButton(
                text="Пополнить баланс",
                callback_data="nav:tokens",
                style=ButtonStyle.PRIMARY,
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                text="Написать статью на сайт",
                callback_data="pipeline:article:start",
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                text="Создать пост в соцсети",
                callback_data="pipeline:social:start",
            ),
        ])
    else:
        # Pipeline CTAs
        article_primary = not (has_social and not has_wp)
        rows.append([
            InlineKeyboardButton(
                text="Написать статью на сайт",
                callback_data="pipeline:article:start",
                style=ButtonStyle.PRIMARY if article_primary else None,
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                text="Создать пост в соцсети",
                callback_data="pipeline:social:start",
                style=ButtonStyle.PRIMARY if not article_primary else None,
            ),
        ])

    # Nav row
    rows.append([
        InlineKeyboardButton(text="Мои проекты", callback_data="nav:projects"),
        InlineKeyboardButton(text="Профиль", callback_data="nav:profile"),
        InlineKeyboardButton(text="Токены", callback_data="nav:tokens"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def dashboard_resume_kb() -> InlineKeyboardMarkup:
    """Checkpoint resume keyboard (UX_PIPELINE.md section 2.6)."""
    return InlineKeyboardMarkup(inline_keyboard=[
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
    ])


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
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="Создать проект",
            callback_data="project:create",
            style=ButtonStyle.SUCCESS,
        ),
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
    ])
    return kb


def project_list_empty_kb() -> InlineKeyboardMarkup:
    """Empty project list keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Создать проект",
                callback_data="project:create",
                style=ButtonStyle.SUCCESS,
            ),
        ],
        [InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard")],
    ])


# ---------------------------------------------------------------------------
# Project card
# ---------------------------------------------------------------------------


def project_card_kb(project_id: int) -> InlineKeyboardMarkup:
    """Project card action buttons (UX_TOOLBOX.md section 3.1)."""
    pid = project_id
    return InlineKeyboardMarkup(inline_keyboard=[
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
    ])


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
    ("company_email", "Email"),
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

    rows.append([
        InlineKeyboardButton(
            text="Удалить проект",
            callback_data=f"project:{pid}:delete",
            style=ButtonStyle.DANGER,
        ),
    ])
    rows.append([
        InlineKeyboardButton(text="К проекту", callback_data=f"project:{pid}:card"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Project delete confirm
# ---------------------------------------------------------------------------


def project_delete_confirm_kb(project_id: int) -> InlineKeyboardMarkup:
    """Delete confirmation dialog."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Подтвердить удаление",
                callback_data=f"project:{project_id}:delete:confirm",
                style=ButtonStyle.DANGER,
            ),
            InlineKeyboardButton(text="Отмена", callback_data=f"project:{project_id}:card"),
        ],
    ])


# ---------------------------------------------------------------------------
# Project created
# ---------------------------------------------------------------------------


def project_deleted_kb() -> InlineKeyboardMarkup:
    """Navigation after project deletion."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="К списку проектов", callback_data="nav:projects"),
            InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
        ],
    ])


def project_created_kb(project_id: int) -> InlineKeyboardMarkup:
    """Success screen after project creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="К проекту",
                callback_data=f"project:{project_id}:card",
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(text="Главное меню", callback_data="nav:dashboard"),
        ],
    ])


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
    kb.inline_keyboard.append([
        InlineKeyboardButton(
            text="Создать категорию",
            callback_data=f"category:{project_id}:create",
            style=ButtonStyle.SUCCESS,
        ),
    ])
    kb.inline_keyboard.append([
        InlineKeyboardButton(text="К проекту", callback_data=f"project:{project_id}:card"),
    ])
    return kb


def category_list_empty_kb(project_id: int) -> InlineKeyboardMarkup:
    """Empty category list keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Создать категорию",
                callback_data=f"category:{project_id}:create",
                style=ButtonStyle.SUCCESS,
            ),
        ],
        [InlineKeyboardButton(text="К проекту", callback_data=f"project:{project_id}:card")],
    ])


# ---------------------------------------------------------------------------
# Category card
# ---------------------------------------------------------------------------


def category_card_kb(category_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Category card actions (UX_TOOLBOX.md section 8)."""
    cid = category_id
    return InlineKeyboardMarkup(inline_keyboard=[
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
    ])


def category_delete_confirm_kb(category_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Category delete confirmation dialog."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Подтвердить удаление",
                callback_data=f"category:{category_id}:delete:confirm",
                style=ButtonStyle.DANGER,
            ),
            InlineKeyboardButton(text="Отмена", callback_data=f"category:{category_id}:card"),
        ],
    ])


def category_created_kb(category_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Success screen after category creation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="К категории",
                callback_data=f"category:{category_id}:card",
                style=ButtonStyle.SUCCESS,
            ),
            InlineKeyboardButton(text="К категориям", callback_data=f"project:{project_id}:categories"),
        ],
    ])


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
    rows.append([
        InlineKeyboardButton(text="+ WordPress", callback_data=f"conn:{project_id}:add:wordpress"),
        InlineKeyboardButton(text="+ Telegram", callback_data=f"conn:{project_id}:add:telegram"),
    ])
    rows.append([
        InlineKeyboardButton(text="+ VK", callback_data=f"conn:{project_id}:add:vk"),
        InlineKeyboardButton(text="+ Pinterest", callback_data=f"conn:{project_id}:add:pinterest"),
    ])
    rows.append([
        InlineKeyboardButton(text="К проекту", callback_data=f"project:{project_id}:card"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Connection manage
# ---------------------------------------------------------------------------


def connection_manage_kb(conn_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Manage single connection — delete + back."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Удалить подключение",
                callback_data=f"conn:{conn_id}:delete",
                style=ButtonStyle.DANGER,
            ),
        ],
        [InlineKeyboardButton(text="К подключениям", callback_data=f"conn:{project_id}:list")],
    ])


def connection_delete_confirm_kb(conn_id: int, project_id: int) -> InlineKeyboardMarkup:
    """Connection delete confirmation dialog."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="Подтвердить удаление",
                callback_data=f"conn:{conn_id}:delete:confirm",
                style=ButtonStyle.DANGER,
            ),
            InlineKeyboardButton(text="Отмена", callback_data=f"conn:{conn_id}:manage"),
        ],
    ])


def vk_group_select_kb(groups: list[dict[str, Any]], project_id: int) -> InlineKeyboardMarkup:
    """VK group selection keyboard."""
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups:
        gid = group.get("id", 0)
        name = str(group.get("name", f"Group {gid}"))
        rows.append([InlineKeyboardButton(text=name, callback_data=f"vk:group:{gid}")])
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
