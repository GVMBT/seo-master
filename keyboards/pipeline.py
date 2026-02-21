"""Inline keyboards for Article and Social pipelines (UX_PIPELINE.md §12)."""

from __future__ import annotations

from typing import Any

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from db.models import Category, PlatformConnection, Project
from keyboards.pagination import paginate
from services.readiness import ReadinessReport
from services.tokens import (
    COST_DESCRIPTION,
    COST_PER_IMAGE,
    estimate_keywords_cost,
)

# ---------------------------------------------------------------------------
# Step 1: Select project (shared article/social)
# ---------------------------------------------------------------------------


def pipeline_projects_kb(
    projects: list[Project],
    page: int = 1,
    pipeline_type: str = "article",
) -> InlineKeyboardMarkup:
    """Project selection for pipeline step 1.

    callback_data: pipeline:{type}:{project_id}:select
    pagination: page:pipeline_{type}_projects:{page}
    """
    return paginate(
        items=projects,
        page=page,
        cb_prefix=f"pipeline_{pipeline_type}_projects",
        item_text="name",
        item_cb=f"pipeline:{pipeline_type}:{{id}}:select",
    )[0]


def pipeline_no_projects_kb(pipeline_type: str = "article") -> InlineKeyboardMarkup:
    """No projects — offer to create one inline."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать проект",
                    callback_data=f"pipeline:{pipeline_type}:create_project",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"pipeline:{pipeline_type}:cancel",
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
    pipeline_type: str = "article",
) -> InlineKeyboardMarkup:
    """Category selection for pipeline step 3.

    callback_data: pipeline:{type}:{project_id}:cat:{cat_id}
    """
    return paginate(
        items=categories,
        page=page,
        cb_prefix=f"pipeline_{pipeline_type}_categories",
        item_text="name",
        item_cb=f"pipeline:{pipeline_type}:{project_id}:cat:{{id}}",
    )[0]


def pipeline_no_categories_kb(pipeline_type: str = "article") -> InlineKeyboardMarkup:
    """No categories — prompt for inline creation."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Создать категорию",
                    callback_data=f"pipeline:{pipeline_type}:create_category",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data=f"pipeline:{pipeline_type}:cancel",
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
    """Error keyboard after failed generation (UX_PIPELINE §8.3, E35).

    3 buttons: Повторить / Другая тема / Главное меню.
    """
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
                    text="Другая тема",
                    callback_data="pipeline:article:change_topic",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Главное меню",
                    callback_data="nav:dashboard",
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


def pipeline_keywords_qty_kb() -> InlineKeyboardMarkup:
    """Keyword quantity selection for pipeline readiness sub-flow."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="50 фраз (50 ток.)",
                    callback_data="pipeline:readiness:keywords:qty_50",
                ),
                InlineKeyboardButton(
                    text="100 фраз (100 ток.)",
                    callback_data="pipeline:readiness:keywords:qty_100",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="150 фраз (150 ток.)",
                    callback_data="pipeline:readiness:keywords:qty_150",
                ),
                InlineKeyboardButton(
                    text="200 фраз (200 ток.)",
                    callback_data="pipeline:readiness:keywords:qty_200",
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


def pipeline_keywords_confirm_kb(cost: int, balance: int) -> InlineKeyboardMarkup:
    """Confirm keyword generation cost in pipeline readiness sub-flow."""
    rows: list[list[InlineKeyboardButton]] = []
    if balance >= cost:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Подобрать ({cost} ток.)",
                    callback_data="pipeline:readiness:keywords:confirm",
                    style=ButtonStyle.SUCCESS,
                ),
            ]
        )
    else:
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
                text="Назад к чеклисту",
                callback_data="pipeline:readiness:keywords:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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


def pipeline_back_to_checklist_kb() -> InlineKeyboardMarkup:
    """Single 'Back to checklist' button for text-input sub-flows (M5)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Назад к чеклисту",
                    callback_data="pipeline:readiness:back",
                ),
            ],
        ]
    )


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
        platform_labels = {
            "telegram": "Телеграм",
            "vk": "ВКонтакте",
            "pinterest": "Пинтерест",
        }
        label = platform_labels.get(conn.platform_type, conn.platform_type)
        # P2-7: Show group_name for VK instead of raw club123456
        metadata = conn.metadata or {}
        if conn.platform_type == "vk" and metadata.get("group_name"):
            display = f"{label}: {metadata['group_name']}"
        else:
            display = f"{label}: {conn.identifier}"
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
                text="Отмена",
                callback_data="pipeline:social:cancel",
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
                text="Отмена",
                callback_data="pipeline:social:cancel",
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def vk_group_select_pipeline_kb(groups: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    """VK group selection within social pipeline."""
    rows: list[list[InlineKeyboardButton]] = []
    for group in groups:
        rows.append(
            [
                InlineKeyboardButton(
                    text=group["name"],
                    callback_data=f"pipeline:social:vk_group:{group['id']}",
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


def social_readiness_kb(report: ReadinessReport) -> InlineKeyboardMarkup:
    """Simplified readiness checklist for social pipeline (UX_PIPELINE.md §5.4).

    Only keywords + description. No prices/images.
    """
    rows: list[list[InlineKeyboardButton]] = []

    if not report.has_keywords:
        cost_label = f" ({estimate_keywords_cost(100)} ток.)"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Подобрать ключевики{cost_label}",
                    callback_data="pipeline:social:readiness:keywords",
                ),
            ]
        )

    if not report.has_description:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"Описание ({COST_DESCRIPTION} ток.)",
                    callback_data="pipeline:social:readiness:description",
                ),
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="Всё ОК — генерировать",
                callback_data="pipeline:social:readiness:done",
                style=ButtonStyle.SUCCESS,
            ),
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="Отменить",
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
