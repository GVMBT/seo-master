"""Inline keyboard builders for Goal-Oriented Pipeline (PIPELINE_UX_PROPOSAL.md)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import Category, PlatformConnection, Project
from keyboards.pagination import paginate

if TYPE_CHECKING:
    from services.readiness import ReadinessItem


def pipeline_project_list_kb(
    projects: list[Project],
    page: int = 0,
    last_used_id: int | None = None,
) -> InlineKeyboardBuilder:
    """Project selection for pipeline step 1."""
    sorted_projects = sorted(
        projects,
        key=lambda p: (p.id != last_used_id, p.name),
    )
    builder, _, _nav_count = paginate(
        items=sorted_projects,
        page=page,
        item_text_fn=lambda p: p.name,
        item_callback_fn=lambda p: f"pipeline:article:project:{p.id}",
        page_callback_fn=lambda pg: f"page:pipeline_proj:{pg}",
    )
    builder.button(text="Отмена", callback_data="menu:main")
    return builder


def pipeline_wp_list_kb(
    connections: list[PlatformConnection],
    project_id: int,
) -> InlineKeyboardBuilder:
    """WP connection selection for pipeline step 2."""
    builder = InlineKeyboardBuilder()
    for conn in connections:
        text = conn.identifier
        if len(text) > 55:
            text = text[:52] + "..."
        builder.button(text=text, callback_data=f"pipeline:article:wp:{conn.id}")
    builder.button(text="Только превью (без публикации)", callback_data="pipeline:article:wp:preview_only")
    builder.button(text="Отмена", callback_data="menu:main")
    builder.adjust(1)
    return builder


def pipeline_category_list_kb(
    categories: list[Category],
    page: int = 0,
) -> InlineKeyboardBuilder:
    """Category selection for pipeline step 3."""
    builder, _, _nav_count = paginate(
        items=categories,
        page=page,
        item_text_fn=lambda c: c.name,
        item_callback_fn=lambda c: f"pipeline:article:cat:{c.id}",
        page_callback_fn=lambda pg: f"page:pipeline_cat:{pg}",
    )
    builder.button(text="Отмена", callback_data="menu:main")
    return builder


def pipeline_confirm_kb(cost: int, is_god_mode: bool = False) -> InlineKeyboardBuilder:
    """Cost confirmation for pipeline step 5."""
    builder = InlineKeyboardBuilder()
    if is_god_mode:
        builder.button(
            text=f"Создать статью ({cost} ток. — GOD_MODE бесплатно)",
            callback_data="pipeline:article:generate",
            style="success",
        )
    else:
        builder.button(
            text=f"Создать статью ({cost} токенов)",
            callback_data="pipeline:article:generate",
            style="success",
        )
    builder.button(text="Отмена", callback_data="pipeline:article:cancel")
    builder.adjust(1)
    return builder


def pipeline_preview_kb(regen_count: int, has_wp: bool = True) -> InlineKeyboardBuilder:
    """Preview actions for pipeline step 7."""
    builder = InlineKeyboardBuilder()
    if has_wp:
        builder.button(
            text="Опубликовать",
            callback_data="pipeline:article:publish",
            style="success",
        )
    remaining = max(0, 2 - regen_count)
    builder.button(
        text=f"Перегенерировать ({remaining}/2)",
        callback_data="pipeline:article:regen",
    )
    builder.button(
        text="Отмена — вернуть токены",
        callback_data="pipeline:article:cancel_refund",
        style="danger",
    )
    builder.adjust(1)
    return builder


def pipeline_resume_kb() -> InlineKeyboardBuilder:
    """Resume interrupted pipeline (E49)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Продолжить", callback_data="pipeline:resume")
    builder.button(text="Начать заново", callback_data="pipeline:restart")
    builder.button(text="Отменить", callback_data="pipeline:cancel")
    builder.adjust(1)
    return builder


def pipeline_post_publish_kb() -> InlineKeyboardBuilder:
    """Post-publish actions for pipeline step 8 success (PROPOSAL section 4.1 step 8)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Ещё статью",
        callback_data="pipeline:article:start",
        style="primary",
    )
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder


def pipeline_no_entities_kb(entity: str, project_id: int = 0) -> InlineKeyboardBuilder:
    """When user has no projects/WP/categories -- redirect to creation."""
    builder = InlineKeyboardBuilder()
    if entity == "project":
        builder.button(text="Создать проект", callback_data="projects:new")
    elif entity == "wp":
        builder.button(text="Подключить WordPress", callback_data=f"project:{project_id}:connections")
        builder.button(text="Только превью", callback_data="pipeline:article:wp:preview_only")
    elif entity == "category":
        builder.button(text="Создать категорию", callback_data=f"project:{project_id}:categories")
    builder.button(text="Отмена", callback_data="menu:main")
    builder.adjust(1)
    return builder


def pipeline_readiness_kb(
    items: list[ReadinessItem],
    all_ready: bool,
) -> InlineKeyboardBuilder:
    """Readiness checklist for pipeline step 4 (PROPOSAL section 4.1).

    Shows buttons only for unfilled items. The main "proceed" button
    is always visible so the user can skip optional enrichers.
    """
    builder = InlineKeyboardBuilder()

    for item in items:
        if item.ready:
            continue  # Don't show buttons for filled items

        # Button text includes cost if > 0
        cost_text = f" ({item.cost} ток.)" if item.cost > 0 else ""

        builder.button(
            text=f"{item.label}{cost_text}",
            callback_data=f"pipeline:article:ready:{item.key}",
        )

    builder.button(
        text="Всё OK — генерировать →",
        callback_data="pipeline:article:ready:proceed",
        style="success",
    )
    builder.button(text="Отмена", callback_data="pipeline:article:cancel")
    builder.adjust(1)
    return builder


def pipeline_keywords_options_kb(auto_cost: int = 100) -> InlineKeyboardBuilder:
    """Keyword generation options (PROPOSAL section 4.1 step 4a)."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"Подобрать автоматически ({auto_cost} ток.)",
        callback_data="pipeline:article:kw:auto",
    )
    builder.button(
        text="Настроить параметры",
        callback_data="pipeline:article:kw:custom",
    )
    builder.button(
        text="Назад к чеклисту",
        callback_data="pipeline:article:kw:back",
    )
    builder.adjust(1)
    return builder


def pipeline_keywords_geo_kb() -> InlineKeyboardBuilder:
    """Geography quick-select for auto keyword generation."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Москва",
        callback_data="pipeline:article:kw:geo:msk",
    )
    builder.button(
        text="Санкт-Петербург",
        callback_data="pipeline:article:kw:geo:spb",
    )
    builder.button(
        text="Вся Россия",
        callback_data="pipeline:article:kw:geo:ru",
    )
    builder.button(
        text="Ввести свой",
        callback_data="pipeline:article:kw:geo:custom",
    )
    builder.adjust(2)
    return builder


def pipeline_keywords_qty_kb() -> InlineKeyboardBuilder:
    """Keyword quantity selection for custom params."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="50 фраз (50 ток.)",
        callback_data="pipeline:article:kw:qty:50",
    )
    builder.button(
        text="100 фраз (100 ток.)",
        callback_data="pipeline:article:kw:qty:100",
    )
    builder.button(
        text="150 фраз (150 ток.)",
        callback_data="pipeline:article:kw:qty:150",
    )
    builder.button(
        text="200 фраз (200 ток.)",
        callback_data="pipeline:article:kw:qty:200",
    )
    builder.adjust(2)
    return builder
