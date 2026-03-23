"""Dashboard keyboards."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

__all__ = [
    "dashboard_kb",
    "dashboard_resume_kb",
]


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
