"""Inline keyboards for the Bamboodom admin section (Session 1)."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def bamboodom_entry_kb() -> InlineKeyboardMarkup:
    """Entry-screen keyboard: smoke-test + settings-stub + back to admin panel."""
    rows = [
        [InlineKeyboardButton(text="Smoke-test", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Настройки", callback_data="bamboodom:settings")],
        [InlineKeyboardButton(text="К панели", callback_data="admin:panel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_smoke_result_kb() -> InlineKeyboardMarkup:
    """Smoke-test result screen: retry + back to section entry."""
    rows = [
        [InlineKeyboardButton(text="Повторить", callback_data="bamboodom:smoke")],
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def bamboodom_settings_kb() -> InlineKeyboardMarkup:
    """Settings stub: only back button for Session 1."""
    rows = [
        [InlineKeyboardButton(text="Назад", callback_data="bamboodom:entry")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)
