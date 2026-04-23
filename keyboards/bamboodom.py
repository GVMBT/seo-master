"""Inline keyboards for the Bamboodom admin section."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def bamboodom_entry_kb() -> InlineKeyboardMarkup:
    """Entry-screen keyboard."""
    rows = [
        [InlineKeyboardButton(text="Smoke-test", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Контекст сайта", callback_data="bamboodom:context")],
        [InlineKeyboardButton(text="Артикулы", callback_data="bamboodom:codes")],
        [InlineKeyboardButton(text="AI-публикация", callback_data="bamboodom:ai:start")],
        [InlineKeyboardButton(text="Публикация в sandbox", callback_data="bamboodom:publish")],
        [InlineKeyboardButton(text="История публикаций", callback_data="bamboodom:history")],
        [InlineKeyboardButton(text="Настройки", callback_data="bamboodom:settings")],
        [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_smoke_result_kb() -> InlineKeyboardMarkup:
    """Smoke-test result screen."""
    rows = [
        [InlineKeyboardButton(text="Повторить", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_context_kb() -> InlineKeyboardMarkup:
    """Context-screen: refresh + back."""
    rows = [
        [InlineKeyboardButton(text="Обновить", callback_data="bamboodom:context:refresh")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_codes_kb() -> InlineKeyboardMarkup:
    """Codes-screen: refresh + back."""
    rows = [
        [InlineKeyboardButton(text="Обновить", callback_data="bamboodom:codes:refresh")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_publish_input_kb() -> InlineKeyboardMarkup:
    """Publish — entry FSM state: example + cancel."""
    rows = [
        [InlineKeyboardButton(text="Вставить пример JSON", callback_data="bamboodom:publish:example")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_publish_confirm_kb() -> InlineKeyboardMarkup:
    """Publish — confirm state."""
    rows = [
        [InlineKeyboardButton(text="Отправить", callback_data="bamboodom:publish:submit")],
        [InlineKeyboardButton(text="Вернуться к редактированию", callback_data="bamboodom:publish")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_publish_result_kb(article_url: str | None) -> InlineKeyboardMarkup:
    """Publish — result screen. Article URL is a direct HTTP link when available."""
    rows: list[list[InlineKeyboardButton]] = []
    if article_url:
        rows.append([InlineKeyboardButton(text="Открыть статью", url=article_url)])
    rows.append([InlineKeyboardButton(text="Опубликовать ещё", callback_data="bamboodom:publish")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_history_kb() -> InlineKeyboardMarkup:
    """History-screen keyboard."""
    rows = [
        [InlineKeyboardButton(text="Опубликовать ещё", callback_data="bamboodom:publish")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_settings_kb() -> InlineKeyboardMarkup:
    """Settings stub: only back button."""
    rows = [
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_material_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 1: choose material category."""
    rows = [
        [InlineKeyboardButton(text="WPC панели", callback_data="bamboodom:ai:mat:wpc")],
        [InlineKeyboardButton(text="Гибкая керамика", callback_data="bamboodom:ai:mat:flex")],
        [InlineKeyboardButton(text="Реечные панели", callback_data="bamboodom:ai:mat:reiki")],
        [InlineKeyboardButton(text="Алюминиевые профили", callback_data="bamboodom:ai:mat:profiles")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_keyword_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 2: waiting for keyword. Only cancel button."""
    rows = [
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_preview_kb() -> InlineKeyboardMarkup:
    """AI FSM — step 4: preview with publish / regenerate / cancel."""
    rows = [
        [InlineKeyboardButton(text="Опубликовать", callback_data="bamboodom:ai:publish")],
        [InlineKeyboardButton(text="Перегенерировать", callback_data="bamboodom:ai:regenerate")],
        [InlineKeyboardButton(text="Отмена", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_ai_result_kb(article_url: str | None) -> InlineKeyboardMarkup:
    """AI FSM — step 5: result screen."""
    rows: list[list[InlineKeyboardButton]] = []
    if article_url:
        rows.append([InlineKeyboardButton(text="Открыть статью", url=article_url)])
    rows.append([InlineKeyboardButton(text="Ещё статью", callback_data="bamboodom:ai:start")])
    rows.append([InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
