"""Inline keyboards for Article and Social pipelines (UX_PIPELINE.md §12)."""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, Project
from keyboards.pagination import paginate
from services.readiness import ReadinessReport
from services.tokens import (
    COST_DESCRIPTION,
    COST_PER_IMAGE,
    estimate_keywords_cost,
)

# ---------------------------------------------------------------------------
# Step 1: Select project
# ---------------------------------------------------------------------------


def pipeline_projects_kb(
    projects: list[Project],
    page: int = 1,
) -> InlineKeyboardMarkup:
    """Project selection for pipeline step 1.

    callback_data: pipeline:article:{project_id}:select
    pagination: page:pipeline_projects:{page}
    """
    return paginate(
        items=projects,
        page=page,
        cb_prefix="pipeline_projects",
        item_text="name",
        item_cb="pipeline:article:{id}:select",
    )[0]


def pipeline_no_projects_kb() -> InlineKeyboardMarkup:
    """No projects — offer to create one inline."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать проект",
                    callback_data="pipeline:article:create_project",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="pipeline:article:cancel",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Step 2: Select WP connection
# ---------------------------------------------------------------------------


def pipeline_no_wp_kb() -> InlineKeyboardMarkup:
    """No WP connections — offer connect or preview-only."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подключить WordPress",
                    callback_data="pipeline:article:connect_wp",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Только превью (без публикации)",
                    callback_data="pipeline:article:preview_only",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Step 3: Select category
# ---------------------------------------------------------------------------


def pipeline_categories_kb(
    categories: list[Category],
    project_id: int,
    page: int = 1,
) -> InlineKeyboardMarkup:
    """Category selection for pipeline step 3.

    callback_data: pipeline:article:{project_id}:cat:{cat_id}
    """
    return paginate(
        items=categories,
        page=page,
        cb_prefix="pipeline_categories",
        item_text="name",
        item_cb=f"pipeline:article:{project_id}:cat:{{id}}",
    )[0]


def pipeline_no_categories_kb() -> InlineKeyboardMarkup:
    """No categories — prompt for inline creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать категорию",
                    callback_data="pipeline:article:create_category",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="pipeline:article:cancel",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Step 4: Readiness check
# ---------------------------------------------------------------------------


def pipeline_readiness_kb(report: ReadinessReport) -> InlineKeyboardMarkup:
    """Readiness checklist keyboard (UX_PIPELINE.md §4, step 4).

    Shows buttons only for missing items.
    """
    rows: list[list[InlineKeyboardButton]] = []

    if not report.has_keywords:
        cost_label = f" ({estimate_keywords_cost(100)} ток.)"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Подобрать ключевики{cost_label}",
                    callback_data="pipeline:readiness:keywords",
                ),
            ]
        )

    if not report.has_description:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Описание ({COST_DESCRIPTION} ток.)",
                    callback_data="pipeline:readiness:description",
                ),
            ]
        )

    if "prices" in report.missing_items:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Добавить цены",
                    callback_data="pipeline:readiness:prices",
                ),
            ]
        )

    if "images" in report.missing_items or report.image_count > 0:
        img_cost = report.image_count * COST_PER_IMAGE
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Изображения: {report.image_count} AI ({img_cost} ток.)",
                    callback_data="pipeline:readiness:images",
                ),
            ]
        )

    # Main CTA: generate
    rows.append(
        [
            InlineKeyboardButton(
                text="Всё ОК — генерировать",
                callback_data="pipeline:readiness:done",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )

    # Cancel pipeline
    rows.append(
        [
            InlineKeyboardButton(
                text="Отменить",
                callback_data="pipeline:article:cancel",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Step 5: Confirm cost
# ---------------------------------------------------------------------------


def pipeline_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard for pipeline step 5 (G6: includes cancel)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать статью",
                    callback_data="pipeline:article:confirm",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Вернуться к чеклисту",
                    callback_data="pipeline:article:back_readiness",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="pipeline:article:cancel",
                ),
            ],
        ]
    )


def pipeline_insufficient_balance_kb() -> InlineKeyboardMarkup:
    """Insufficient balance — offer to top up (E01, UX_PIPELINE §8.1)."""
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
                    callback_data="pipeline:article:cancel",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Step 7: Preview
# ---------------------------------------------------------------------------


def pipeline_preview_kb(
    telegraph_url: str | None = None,
    *,
    can_publish: bool = True,
    regen_count: int = 0,
    regen_cost: int = 0,
) -> InlineKeyboardMarkup:
    """Preview keyboard with publish/regenerate/cancel options.

    Args:
        telegraph_url: Telegraph preview link. None when E05 Telegraph down.
        can_publish: Whether WP connection is available.
        regen_count: Current regeneration count (0-based).
        regen_cost: Token cost for next regeneration (shown when count >= 2).
    """
    rows: list[list[InlineKeyboardButton]] = []

    # Preview link (E05: omitted when Telegraph is down)
    if telegraph_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Открыть превью",
                    url=telegraph_url,
                ),
            ]
        )

    if can_publish:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Опубликовать",
                    callback_data="pipeline:article:publish",
                    style=ButtonStyle.SUCCESS,
                ),
            ]
        )

    # Regen button: show cost when count >= MAX_REGENERATIONS_FREE (2)
    regen_text = "Перегенерировать"
    if regen_count >= 2 and regen_cost > 0:
        regen_text = f"Перегенерировать (~{regen_cost} ток.)"
    rows.append(
        [
            InlineKeyboardButton(
                text=regen_text,
                callback_data="pipeline:article:regenerate",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена — вернуть токены",
                callback_data="pipeline:article:cancel_refund",
                style=ButtonStyle.DANGER,
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def pipeline_preview_no_wp_kb(
    telegraph_url: str | None = None,
    *,
    regen_count: int = 0,
    regen_cost: int = 0,
) -> InlineKeyboardMarkup:
    """Preview-only keyboard — Variant B, no WP (G1).

    Shows: preview link, connect WP, copy HTML, regenerate, cancel.
    """
    rows: list[list[InlineKeyboardButton]] = []

    if telegraph_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Открыть превью",
                    url=telegraph_url,
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Подключить WordPress и опубликовать",
                callback_data="pipeline:article:connect_wp_publish",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Скопировать HTML",
                callback_data="pipeline:article:copy_html",
            ),
        ]
    )

    regen_text = "Перегенерировать"
    if regen_count >= 2 and regen_cost > 0:
        regen_text = f"Перегенерировать (~{regen_cost} ток.)"
    rows.append(
        [
            InlineKeyboardButton(
                text=regen_text,
                callback_data="pipeline:article:regenerate",
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отмена — вернуть токены",
                callback_data="pipeline:article:cancel_refund",
                style=ButtonStyle.DANGER,
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Step 8: Result
# ---------------------------------------------------------------------------


def pipeline_result_kb(post_url: str | None = None) -> InlineKeyboardMarkup:
    """Result keyboard after successful publication."""
    rows: list[list[InlineKeyboardButton]] = []

    if post_url:
        rows.append(
            [
                InlineKeyboardButton(
                    text="Открыть на сайте",
                    url=post_url,
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Ещё статью",
                callback_data="pipeline:article:more",
                style=ButtonStyle.PRIMARY,
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Настроить автопубликацию",
                callback_data="nav:scheduler",
            ),
            InlineKeyboardButton(
                text="Главное меню",
                callback_data="nav:dashboard",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


# ---------------------------------------------------------------------------
# Step 6: Generation error
# ---------------------------------------------------------------------------


def pipeline_generation_error_kb() -> InlineKeyboardMarkup:
    """Error keyboard after failed generation (E35)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить",
                    callback_data="pipeline:article:confirm",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="pipeline:article:cancel",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Shared: Exit protection (§7.5)
# ---------------------------------------------------------------------------


def pipeline_exit_confirm_kb() -> InlineKeyboardMarkup:
    """Exit confirmation for steps 4-7."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, выйти",
                    callback_data="pipeline:article:exit_confirm",
                    style=ButtonStyle.DANGER,
                ),
                InlineKeyboardButton(
                    text="Продолжить",
                    callback_data="pipeline:article:exit_cancel",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Readiness sub-flow: Keywords
# ---------------------------------------------------------------------------


def pipeline_keywords_options_kb() -> InlineKeyboardMarkup:
    """Keyword generation options in readiness sub-flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Подобрать автоматически (100 фраз — 100 ток.)",
                    callback_data="pipeline:readiness:keywords:auto",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Настроить параметры",
                    callback_data="pipeline:readiness:keywords:configure",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Загрузить свои",
                    callback_data="pipeline:readiness:keywords:upload",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад к чеклисту",
                    callback_data="pipeline:readiness:back",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Readiness sub-flow: Description
# ---------------------------------------------------------------------------


def pipeline_description_options_kb() -> InlineKeyboardMarkup:
    """Description options in readiness sub-flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Сгенерировать AI ({COST_DESCRIPTION} токенов)",
                    callback_data="pipeline:readiness:description:ai",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Написать вручную",
                    callback_data="pipeline:readiness:description:manual",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад к чеклисту",
                    callback_data="pipeline:readiness:back",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Readiness sub-flow: Prices
# ---------------------------------------------------------------------------


def pipeline_prices_options_kb() -> InlineKeyboardMarkup:
    """Prices input options in readiness sub-flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Добавить текстом",
                    callback_data="pipeline:readiness:prices:text",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Загрузить Excel",
                    callback_data="pipeline:readiness:prices:excel",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад к чеклисту",
                    callback_data="pipeline:readiness:back",
                ),
            ],
        ]
    )


# ---------------------------------------------------------------------------
# Readiness sub-flow: Images
# ---------------------------------------------------------------------------


def pipeline_images_options_kb(current_count: int = 4) -> InlineKeyboardMarkup:
    """Image count options in readiness sub-flow."""
    options = [0, 1, 2, 3, 4, 6, 8, 10]
    rows: list[list[InlineKeyboardButton]] = []

    row: list[InlineKeyboardButton] = []
    for count in options:
        label = f"{count}" if count != current_count else f"[{count}]"
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"pipeline:readiness:images:{count}",
            )
        )
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append(
        [
            InlineKeyboardButton(
                text="Назад к чеклисту",
                callback_data="pipeline:readiness:back",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)
