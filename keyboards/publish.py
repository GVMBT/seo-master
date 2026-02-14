"""Inline keyboard builders for publishing, keywords, audit, competitor analysis."""

from aiogram.utils.keyboard import InlineKeyboardBuilder

from db.models import PlatformConnection, Project
from keyboards.pagination import PAGE_SIZE, paginate

# ---------------------------------------------------------------------------
# Article publish keyboards
# ---------------------------------------------------------------------------


def article_confirm_kb(category_id: int, connection_id: int, cost: int) -> InlineKeyboardBuilder:
    """Cost confirmation before article generation."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, сгенерировать ({cost} токенов)", callback_data="pub:article:confirm")
    builder.button(text="Отмена", callback_data=f"category:{category_id}:card")
    builder.adjust(1)
    return builder


def article_preview_kb(preview_id: int, regen_count: int) -> InlineKeyboardBuilder:
    """Article preview actions: publish, regenerate (with counter), cancel."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Опубликовать", callback_data="pub:article:publish")
    remaining = max(0, 2 - regen_count)
    builder.button(
        text=f"Перегенерировать ({remaining}/2)",
        callback_data="pub:article:regen",
    )
    builder.button(text="Отмена", callback_data="pub:article:cancel")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Social post publish keyboards
# ---------------------------------------------------------------------------


def social_confirm_kb(
    category_id: int, platform: str, connection_id: int, cost: int,
) -> InlineKeyboardBuilder:
    """Cost confirmation before social post generation."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, сгенерировать ({cost} токенов)", callback_data="pub:social:confirm")
    builder.button(text="Отмена", callback_data=f"category:{category_id}:card")
    builder.adjust(1)
    return builder


def social_review_kb(regen_count: int) -> InlineKeyboardBuilder:
    """Social post review: publish, regenerate, cancel."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Опубликовать", callback_data="pub:social:publish")
    remaining = max(0, 2 - regen_count)
    builder.button(
        text=f"Перегенерировать ({remaining}/2)",
        callback_data="pub:social:regen",
    )
    builder.button(text="Отмена", callback_data="pub:social:cancel")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Insufficient balance
# ---------------------------------------------------------------------------


def insufficient_balance_kb() -> InlineKeyboardBuilder:
    """Prompt to top up balance or cancel."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Пополнить", callback_data="tariffs:topup")
    builder.button(text="Отмена", callback_data="menu:main")
    builder.adjust(2)
    return builder


# ---------------------------------------------------------------------------
# Quick publish keyboards
# ---------------------------------------------------------------------------


def quick_project_list_kb(projects: list[Project], page: int = 0) -> InlineKeyboardBuilder:
    """Paginated project list for quick publish."""
    builder, _, _nav_count = paginate(
        items=projects,
        page=page,
        item_text_fn=lambda p: p.name,
        item_callback_fn=lambda p: f"quick:project:{p.id}",
        page_callback_fn=lambda pg: f"page:quick_proj:{pg}",
    )
    return builder


def quick_combo_list_kb(
    combos: list[dict[str, object]],
    project_id: int,
    page: int = 0,
) -> InlineKeyboardBuilder:
    """Paginated category→platform combos for quick publish.

    Each combo: {cat_id, cat_name, platform, conn_id, conn_name}.
    """
    _PLAT_DISPLAY = {"wordpress": "WP", "telegram": "TG", "vk": "VK", "pinterest": "Pin"}
    _PLAT_CODE = {"wordpress": "wp", "telegram": "tg", "vk": "vk", "pinterest": "pi"}

    builder, _, nav_count = paginate(
        items=combos,
        page=page,
        item_text_fn=lambda c: f"{c['cat_name']} → {_PLAT_DISPLAY.get(str(c['platform']), str(c['platform']))}",
        item_callback_fn=lambda c: (
            f"quick:cat:{c['cat_id']}:{_PLAT_CODE.get(str(c['platform']), str(c['platform'])[:2])}:{c['conn_id']}"
        ),
        page_callback_fn=lambda pg: f"page:quick_combo:{project_id}:{pg}",
    )
    # Add back button
    builder.button(text="Назад", callback_data="menu:main")
    # Re-adjust: paginate items + nav + back
    page_items_count = len(combos[page * PAGE_SIZE : (page + 1) * PAGE_SIZE])
    sizes = [1] * page_items_count
    if nav_count:
        sizes.append(nav_count)
    sizes.append(1)  # back
    builder.adjust(*sizes)
    return builder


def quick_wp_choice_kb(
    connections: list[PlatformConnection], category_id: int,
) -> InlineKeyboardBuilder:
    """Choose which WP connection when >1 WordPress (E28)."""
    builder = InlineKeyboardBuilder()
    for conn in connections:
        builder.button(
            text=conn.identifier,
            callback_data=f"quick:cat:{category_id}:wp:{conn.id}",
        )
    builder.button(text="Назад", callback_data="menu:main")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Platform choice for category publish
# ---------------------------------------------------------------------------


def publish_platform_choice_kb(
    category_id: int,
    connections: list[PlatformConnection],
) -> InlineKeyboardBuilder:
    """Choose platform/connection when category has >1 connection."""
    _PLAT_DISPLAY = {"wordpress": "WordPress", "telegram": "Telegram", "vk": "VK", "pinterest": "Pinterest"}
    builder = InlineKeyboardBuilder()
    for conn in connections:
        plat_name = _PLAT_DISPLAY.get(conn.platform_type, conn.platform_type)
        label = f"{plat_name}: {conn.identifier}"
        if len(label) > 60:
            label = label[:57] + "..."
        # Route: wp → article, others → social
        plat_short = {"wordpress": "wp", "telegram": "tg", "vk": "vk", "pinterest": "pin"}
        ps = plat_short.get(conn.platform_type, conn.platform_type[:2])
        builder.button(
            text=label,
            callback_data=f"category:{category_id}:publish:{ps}:{conn.id}",
        )
    builder.button(text="Назад", callback_data=f"category:{category_id}:card")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Keywords keyboards
# ---------------------------------------------------------------------------


def keywords_main_kb(category_id: int, has_keywords: bool) -> InlineKeyboardBuilder:
    """Keywords management menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Подобрать фразы", callback_data=f"category:{category_id}:kw:generate")
    builder.button(text="Загрузить свои", callback_data=f"category:{category_id}:kw:upload")
    builder.button(text="К категории", callback_data=f"category:{category_id}:card")
    builder.adjust(1)
    return builder


def keyword_quantity_kb(category_id: int) -> InlineKeyboardBuilder:
    """Choose keyword quantity: 50, 100, 150, 200."""
    builder = InlineKeyboardBuilder()
    for n in (50, 100, 150, 200):
        builder.button(text=str(n), callback_data=f"kw:qty:{category_id}:{n}")
    builder.adjust(4)
    return builder


def keyword_confirm_kb(category_id: int, cost: int) -> InlineKeyboardBuilder:
    """Confirm keyword generation cost."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, генерировать ({cost} токенов)", callback_data="kw:confirm")
    builder.button(text="Отмена", callback_data=f"category:{category_id}:card")
    builder.adjust(1)
    return builder


def keyword_results_kb(category_id: int) -> InlineKeyboardBuilder:
    """Keyword results: save or go back."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить", callback_data="kw:save")
    builder.button(text="К категории", callback_data=f"category:{category_id}:card")
    builder.adjust(2)
    return builder


# ---------------------------------------------------------------------------
# Audit keyboards
# ---------------------------------------------------------------------------


def audit_menu_kb(project_id: int, has_audit: bool) -> InlineKeyboardBuilder:
    """Site analysis menu: tech audit + competitor analysis."""
    builder = InlineKeyboardBuilder()
    label = "Перезапустить аудит" if has_audit else "Тех. аудит"
    builder.button(text=label, callback_data=f"project:{project_id}:audit:run")
    builder.button(text="Анализ конкурентов", callback_data=f"project:{project_id}:competitor")
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder


def audit_results_kb(project_id: int) -> InlineKeyboardBuilder:
    """After audit: re-run, competitor, or back."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Перезапустить", callback_data=f"project:{project_id}:audit:run")
    builder.button(text="Анализ конкурентов", callback_data=f"project:{project_id}:competitor")
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Competitor analysis keyboards
# ---------------------------------------------------------------------------


def competitor_confirm_kb(project_id: int, cost: int) -> InlineKeyboardBuilder:
    """Confirm competitor analysis cost."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, анализировать ({cost} токенов)", callback_data="comp:confirm")
    builder.button(text="Отмена", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder


def competitor_results_kb(project_id: int) -> InlineKeyboardBuilder:
    """Competitor analysis results: back to project."""
    builder = InlineKeyboardBuilder()
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder
