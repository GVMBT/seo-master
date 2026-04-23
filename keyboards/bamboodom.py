"""Inline keyboards for the Bamboodom admin section."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def bamboodom_entry_kb() -> InlineKeyboardMarkup:
    """Entry-screen keyboard."""
    rows = [
        [InlineKeyboardButton(text="Smoke-test", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Контекст сайта", callback_data="bamboodom:context")],
        [InlineKeyboardButton(text="Артикулы", callback_data="bamboodom:codes")],
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


def bamboodom_settings_kb() -> InlineKeyboardMarkup:
    """Settings stub: only back button."""
    rows = [
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
