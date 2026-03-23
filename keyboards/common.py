"""Common keyboards: menu, cancel, consent, and shared utilities."""

from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.texts.legal import PRIVACY_POLICY_URL, TERMS_OF_SERVICE_URL

__all__ = [
    "cancel_kb",
    "consent_kb",
    "format_connection_display",
    "menu_kb",
]

_PLATFORM_LABELS_RU: dict[str, str] = {
    "wordpress": "WordPress",
    "telegram": "Телеграм",
    "vk": "ВКонтакте",
    "pinterest": "Пинтерест",
}


def menu_kb() -> InlineKeyboardMarkup:
    """Single-button keyboard to return to dashboard. Use for dead-end messages."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Меню", callback_data="nav:dashboard")],
        ]
    )


def cancel_kb(callback_data: str = "fsm:cancel") -> InlineKeyboardMarkup:
    """Inline cancel button for text input FSM states.

    Provides a visible [Отмена] button so users do not have to
    type the magic word.  The existing text-based "Отмена" handler
    remains as a fallback.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Отмена", callback_data=callback_data)],
        ]
    )


def consent_kb() -> InlineKeyboardMarkup:
    """Consent screen: privacy policy, terms (URL links), accept button."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Политика конфиденциальности", url=PRIVACY_POLICY_URL)],
            [InlineKeyboardButton(text="Оферта", url=TERMS_OF_SERVICE_URL)],
            [InlineKeyboardButton(text="Принимаю", callback_data="legal:consent:accept")],
        ]
    )


def format_connection_display(conn: Any, *, with_status: bool = False) -> str:
    """Human-readable connection label.

    WordPress: domain (e.g. "smoketest.instawp.site")
    Social: Russian name (e.g. "ВКонтакте", "Пинтерест", "Телеграм")
    VK with group_name in metadata: "ВКонтакте: Group Name"
    """
    label = _PLATFORM_LABELS_RU.get(conn.platform_type) or str(conn.platform_type)
    if conn.platform_type == "wordpress":
        text = str(conn.identifier)
    elif conn.platform_type == "vk":
        metadata = getattr(conn, "metadata", None) or {}
        group_name = metadata.get("group_name") if isinstance(metadata, dict) else None
        text = f"{label}: {group_name}" if group_name else label
    else:
        text = label
    if with_status:
        status = "\u2713" if getattr(conn, "status", None) == "active" else "\u2717"
        return f"{status} {text}"
    return text
