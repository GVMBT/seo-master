"""Reusable error recovery keyboards.

Dead-end error messages violate UX best practice -- every error should offer
an actionable next step. These keyboards provide consistent recovery options
for common error scenarios (EDGE_CASES.md E01-E52, UI_STRATEGY.md section 2.1).

NOTE: ``insufficient_balance_kb()`` lives in ``keyboards/publish.py`` (E01).
"""

from aiogram.utils.keyboard import InlineKeyboardBuilder

# Max callback_data size per Telegram Bot API
_MAX_CALLBACK_BYTES = 64


def _validate_callback_data(value: str, param_name: str) -> None:
    """Validate callback_data length (Telegram Bot API: max 64 bytes)."""
    byte_len = len(value.encode("utf-8"))
    if byte_len > _MAX_CALLBACK_BYTES:
        msg = f"{param_name} exceeds 64 bytes ({byte_len}): {value!r}"
        raise ValueError(msg)


def error_not_found_kb(back_callback: str = "menu:main") -> InlineKeyboardBuilder:
    """Entity not found -- [Назад] [Главное меню]."""
    _validate_callback_data(back_callback, "back_callback")
    builder = InlineKeyboardBuilder()
    if back_callback != "menu:main":
        builder.button(text="Назад", callback_data=back_callback)
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder


def error_retry_kb(retry_callback: str, cancel_callback: str = "menu:main") -> InlineKeyboardBuilder:
    """Generic recoverable error -- [Повторить] [Отмена]."""
    _validate_callback_data(retry_callback, "retry_callback")
    _validate_callback_data(cancel_callback, "cancel_callback")
    builder = InlineKeyboardBuilder()
    builder.button(text="Повторить", callback_data=retry_callback)
    builder.button(text="Отмена", callback_data=cancel_callback)
    builder.adjust(2)
    return builder


def error_connection_failed_kb(project_id: int) -> InlineKeyboardBuilder:
    """Platform connection issue -- [Проверить подключения] [К проекту]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Проверить подключения", callback_data=f"project:{project_id}:connections")
    builder.button(text="К проекту", callback_data=f"project:{project_id}:card")
    builder.adjust(1)
    return builder


def error_no_keywords_kb(category_id: int) -> InlineKeyboardBuilder:
    """No keywords available for rotation -- [Подобрать фразы] [К категории]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Подобрать фразы", callback_data=f"category:{category_id}:kw:generate")
    builder.button(text="К категории", callback_data=f"category:{category_id}:card")
    builder.adjust(1)
    return builder


def error_generic_kb() -> InlineKeyboardBuilder:
    """Unrecoverable error -- [Главное меню]."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Главное меню", callback_data="menu:main")
    builder.adjust(1)
    return builder
