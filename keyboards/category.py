"""Keyboard builders for category features: description, reviews, prices, media."""

from aiogram.utils.keyboard import InlineKeyboardBuilder

# ---------------------------------------------------------------------------
# Description keyboards (DescriptionGenerateFSM)
# ---------------------------------------------------------------------------


def description_confirm_kb(cat_id: int, cost: int) -> InlineKeyboardBuilder:
    """Confirm description generation: [Да, сгенерировать (N ток.)] [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, сгенерировать ({cost} ток.)", callback_data="desc:confirm")
    builder.button(text="Отмена", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


def description_result_kb(cat_id: int, regen_count: int) -> InlineKeyboardBuilder:
    """After generation: [Сохранить] [Перегенерировать (N/2)] [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить", callback_data="desc:save")
    label = "Перегенерировать" if regen_count < 2 else "Перегенерировать (платно)"
    builder.button(text=label, callback_data="desc:regen")
    builder.button(text="Отмена", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


def description_existing_kb(cat_id: int) -> InlineKeyboardBuilder:
    """When description already exists: [Перегенерировать] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Перегенерировать", callback_data=f"category:{cat_id}:description:regen")
    builder.button(text="К категории", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Review keyboards (ReviewGenerationFSM)
# ---------------------------------------------------------------------------


def review_quantity_kb(cat_id: int) -> InlineKeyboardBuilder:
    """Choose quantity: [3] [5] [10]."""
    builder = InlineKeyboardBuilder()
    for n in (3, 5, 10):
        builder.button(text=str(n), callback_data=f"review:qty:{cat_id}:{n}")
    builder.button(text="Отмена", callback_data=f"category:{cat_id}:card")
    builder.adjust(3, 1)
    return builder


def review_confirm_kb(cat_id: int, cost: int) -> InlineKeyboardBuilder:
    """Confirm review generation: [Да, сгенерировать (N ток.)] [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Да, сгенерировать ({cost} ток.)", callback_data="review:confirm")
    builder.button(text="Отмена", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


def review_result_kb(cat_id: int, regen_count: int) -> InlineKeyboardBuilder:
    """After generation: [Сохранить] [Перегенерировать (N/2)] [Отмена]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить", callback_data="review:save")
    label = "Перегенерировать" if regen_count < 2 else "Перегенерировать (платно)"
    builder.button(text=label, callback_data="review:regen")
    builder.button(text="Отмена", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


def review_existing_kb(cat_id: int, count: int) -> InlineKeyboardBuilder:
    """When reviews exist: [Перегенерировать] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Перегенерировать ({count} шт.)", callback_data=f"category:{cat_id}:reviews:regen")
    builder.button(text="К категории", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


# ---------------------------------------------------------------------------
# Price keyboards (PriceInputFSM)
# ---------------------------------------------------------------------------


def price_method_kb(cat_id: int) -> InlineKeyboardBuilder:
    """Choose input method: [Ввести текстом] [Загрузить Excel] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Ввести текстом", callback_data=f"price:cat:{cat_id}:text")
    builder.button(text="Загрузить Excel", callback_data=f"price:cat:{cat_id}:excel")
    builder.button(text="К категории", callback_data=f"category:{cat_id}:card")
    builder.adjust(2, 1)
    return builder


def price_result_kb(cat_id: int) -> InlineKeyboardBuilder:
    """After price input: [Сохранить] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Сохранить", callback_data="price:save")
    builder.button(text="К категории", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


def price_existing_kb(cat_id: int) -> InlineKeyboardBuilder:
    """When prices exist: [Обновить] [Очистить] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Обновить", callback_data=f"category:{cat_id}:prices:update")
    builder.button(text="Очистить", callback_data=f"price:cat:{cat_id}:clear")
    builder.button(text="К категории", callback_data=f"category:{cat_id}:card")
    builder.adjust(2, 1)
    return builder


# ---------------------------------------------------------------------------
# Media keyboards (F23 Media Gallery)
# ---------------------------------------------------------------------------


def media_menu_kb(cat_id: int, has_media: bool) -> InlineKeyboardBuilder:
    """Media menu: [Загрузить файлы] [Очистить?] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Загрузить файлы", callback_data=f"media:cat:{cat_id}:upload")
    if has_media:
        builder.button(text="Очистить", callback_data=f"media:cat:{cat_id}:clear")
    builder.button(text="К категории", callback_data=f"category:{cat_id}:card")
    builder.adjust(1)
    return builder


