"""Project keyboards: list, card, edit, delete, created."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts.emoji import TOGGLE_ON
from db.models import Project
from keyboards.pagination import paginate

__all__ = [
    "project_card_kb",
    "project_created_kb",
    "project_delete_confirm_kb",
    "project_deleted_kb",
    "project_edit_kb",
    "project_list_empty_kb",
    "project_list_kb",
]

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


def project_list_kb(projects: list[Project], page: int = 1) -> InlineKeyboardMarkup:
    """Project list with pagination. Item cb: project:{id}:card."""
    kb, _ = paginate(
        items=projects,
        page=page,
        cb_prefix="projects",
        item_text="name",
        item_cb="project:{id}:card",
        item_style=ButtonStyle.PRIMARY,
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
            InlineKeyboardButton(text="Меню", callback_data="nav:dashboard"),
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
            [InlineKeyboardButton(text="Меню", callback_data="nav:dashboard")],
        ]
    )


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
        InlineKeyboardButton(text="О компании", callback_data=f"project:{pid}:edit"),
        InlineKeyboardButton(text="Категории", callback_data=f"project:{pid}:categories"),
    ])

    rows.append([
        InlineKeyboardButton(text="Стиль статей", callback_data=f"project:{pid}:content_settings"),
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
    rows.append([InlineKeyboardButton(text="К проектам", callback_data="nav:projects")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


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
            prefix = TOGGLE_ON if filled.get(field) else ""
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
            InlineKeyboardButton(text="К проекту", callback_data=f"project:{pid}:card"),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def project_delete_confirm_kb(project_id: int) -> InlineKeyboardMarkup:
    """Delete confirmation dialog."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Удалить",
                    callback_data=f"project:{project_id}:delete:confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(text="Отмена", callback_data=f"project:{project_id}:card"),
            ],
        ]
    )


def project_deleted_kb() -> InlineKeyboardMarkup:
    """Navigation after project deletion."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="К проектам", callback_data="nav:projects"),
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
