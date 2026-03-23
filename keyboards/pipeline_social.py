"""Social pipeline + crosspost keyboards (UX_PIPELINE.md §5-6)."""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts.emoji import TOGGLE_ON
from db.models import PlatformConnection
from keyboards.common import format_connection_display
from services.readiness import ReadinessReport

__all__ = [
    "crosspost_result_kb",
    "crosspost_select_kb",
    "social_confirm_kb",
    "social_connections_kb",
    "social_exit_confirm_kb",
    "social_insufficient_balance_kb",
    "social_no_connections_kb",
    "social_readiness_kb",
    "social_result_kb",
    "social_review_kb",
]


# ---------------------------------------------------------------------------
# Social Pipeline keyboards (UX_PIPELINE.md §5)
# ---------------------------------------------------------------------------


def social_connections_kb(
    connections: list[PlatformConnection],
    project_id: int,
) -> InlineKeyboardMarkup:
    """Social connection selection for pipeline step 2 (UX_PIPELINE.md §5.2).

    Shows connected platforms + "Подключить ещё".
    VK connections display group_name from metadata (P2-7 fix).
    """
    rows: list[list[InlineKeyboardButton]] = []

    for conn in connections:
        display = format_connection_display(conn)
        rows.append(
            [
                InlineKeyboardButton(
                    text=display,
                    callback_data=f"pipeline:social:{project_id}:conn:{conn.id}",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Подключить ещё",
                callback_data="pipeline:social:add_connection",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="pipeline:social:back_project",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data="pipeline:social:cancel",
                style=ButtonStyle.DANGER,
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def social_no_connections_kb(
    exclude_types: set[str] | None = None,
) -> InlineKeyboardMarkup:
    """No social connections — offer to connect.

    Args:
        exclude_types: Platform types to hide (already connected). P1-3 fix.
    """
    exclude = exclude_types or set()
    platforms = [
        ("Подключить Телеграм", "pipeline:social:connect:telegram", "telegram", True),
        ("Подключить ВКонтакте", "pipeline:social:connect:vk", "vk", False),
        ("Подключить Пинтерест", "pipeline:social:connect:pinterest", "pinterest", False),
    ]
    rows: list[list[InlineKeyboardButton]] = []
    for text, cb, ptype, is_primary in platforms:
        if ptype in exclude:
            continue
        if is_primary and not rows:
            btn = InlineKeyboardButton(text=text, callback_data=cb, style=ButtonStyle.PRIMARY)
        else:
            btn = InlineKeyboardButton(text=text, callback_data=cb)
        rows.append([btn])

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад",
                callback_data="pipeline:social:back_project",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data="pipeline:social:cancel",
                style=ButtonStyle.DANGER,
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def social_readiness_kb(report: ReadinessReport) -> InlineKeyboardMarkup:
    """Simplified readiness checklist for social pipeline (UX_PIPELINE.md §5.4).

    Only keywords + description. No prices/images.
    """
    rows: list[list[InlineKeyboardButton]] = []

    if not report.has_description:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Описание",
                    callback_data="pipeline:social:readiness:description",
                ),
            ]
        )

    if not report.has_keywords:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Подобрать ключевики",
                    callback_data="pipeline:social:readiness:keywords",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=TOGGLE_ON + "Готово \u2014 генерировать",
                callback_data="pipeline:social:readiness:done",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена",
                callback_data="pipeline:social:cancel",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def social_exit_confirm_kb() -> InlineKeyboardMarkup:
    """Exit confirmation for social pipeline steps 4-7."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, выйти",
                    callback_data="pipeline:social:exit_confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    text="Продолжить",
                    callback_data="pipeline:social:exit_cancel",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Social Pipeline: Confirm / Insufficient / Review / Result (F6.3, steps 5-7)
# ---------------------------------------------------------------------------


def social_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard for social pipeline step 5."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать пост",
                    callback_data="pipeline:social:confirm",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="К чеклисту",
                    callback_data="pipeline:social:back_readiness",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="pipeline:social:cancel",
                ),
            ],
        ]
    )


def social_insufficient_balance_kb() -> InlineKeyboardMarkup:
    """Insufficient balance for social post — offer to top up (E01)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Пополнить баланс",
                    callback_data="nav:tokens",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="pipeline:social:cancel",
                ),
            ],
        ]
    )


def social_review_kb(
    regen_count: int = 0,
    regen_cost: int = 40,
    telegraph_url: str | None = None,
) -> InlineKeyboardMarkup:
    """Review keyboard for social post after generation (step 6).

    Args:
        regen_count: How many times regenerated so far (0-based).
        regen_cost: Token cost for paid regeneration.
        telegraph_url: Telegraph preview page URL (shown as button if present).
    """
    rows: list[list[InlineKeyboardButton]] = []

    if telegraph_url:
        rows.append(
            [InlineKeyboardButton(text="Превью", url=telegraph_url)]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Опубликовать",
                callback_data="pipeline:social:publish",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )

    # Regen button: free for first 2, then costs tokens
    if regen_count < 2:
        remaining = 2 - regen_count
        regen_text = f"Перегенерировать (осталось {remaining})"
    else:
        regen_text = f"Перегенерировать ({regen_cost} ток.)"
    rows.append(
        [
            InlineKeyboardButton(
                text=regen_text,
                callback_data="pipeline:social:regen",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена (возврат)",
                callback_data="pipeline:social:cancel_refund",
                style=ButtonStyle.DANGER,
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def social_result_kb(
    post_url: str | None,
    has_crosspost_targets: bool = False,
) -> InlineKeyboardMarkup:
    """Result keyboard after successful social post publication.

    Args:
        post_url: Direct link to the published post (None if unavailable).
        has_crosspost_targets: True if there are other social connections
            available for cross-posting.
    """
    rows: list[list[InlineKeyboardButton]] = []

    if post_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Открыть пост",
                    url=post_url,
                ),
            ]
        )

    if has_crosspost_targets:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Кросс-пост (~10 ток.)",
                    callback_data="pipeline:crosspost:start",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Меню",
                callback_data="nav:dashboard",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Cross-post: platform selection (F6.4, UX_PIPELINE.md §6)
# ---------------------------------------------------------------------------

def crosspost_select_kb(
    connections: list[PlatformConnection],
    selected_ids: set[int],
) -> InlineKeyboardMarkup:
    """Toggle-checkboxes for cross-post platform selection.

    Args:
        connections: Other social connections (lead excluded).
        selected_ids: Currently selected connection IDs.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for conn in connections:
        display = format_connection_display(conn)
        check = TOGGLE_ON if conn.id in selected_ids else ""
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{check}{display}",
                    callback_data=f"pipeline:crosspost:toggle:{conn.id}",
                ),
            ]
        )

    action_row: list[InlineKeyboardButton] = []
    if selected_ids:
        cost = len(selected_ids) * 10
        action_row.append(
            InlineKeyboardButton(
                text=f"Адаптировать (~{cost} ток.)",
                callback_data="pipeline:crosspost:go",
                style=ButtonStyle.SUCCESS,
            )
        )
    action_row.append(
        InlineKeyboardButton(
            text="Отмена",
            callback_data="pipeline:crosspost:cancel",
        )
    )
    rows.append(action_row)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def crosspost_result_kb() -> InlineKeyboardMarkup:
    """Result keyboard after cross-posting is done."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Меню",
                    callback_data="nav:dashboard",
                ),
            ]
        ]
    )
