"""Keyboard builders for built-in help system (F46)."""

from aiogram.utils.keyboard import InlineKeyboardBuilder


def help_main_kb() -> InlineKeyboardBuilder:
    """Help sections menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Первое подключение", callback_data="help:connect")
    builder.button(text="Создание проекта", callback_data="help:project")
    builder.button(text="Категории", callback_data="help:category")
    builder.button(text="Публикация", callback_data="help:publish")
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(2, 2, 1)
    return builder


def help_back_kb() -> InlineKeyboardBuilder:
    """Back to help + main menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Назад к помощи", callback_data="help:main")
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(2)
    return builder
