"""Consistent screen text builder for all bot messages.

Usage:
    text = (
        Screen(E.ROCKET, "PVNDORA")
        .blank()
        .line(f"{E.WORDPRESS} site.com")
        .blank()
        .field(E.FOLDER, "Категорий", "2")
        .field(E.ANALYTICS, "Публикаций", "16")
        .hint("Управляйте проектом и контентом")
        .build()
    )
"""

from __future__ import annotations

from bot.texts.emoji import E

# Separator line constant
SEPARATOR = "\u2500" * 10


class Screen:
    """Fluent builder for structured bot screen text."""

    def __init__(self, icon: str, title: str) -> None:
        """Create screen with header: {icon} <b>{title}</b>"""
        self._lines: list[str] = [f"{icon} <b>{title}</b>"]

    def blank(self) -> Screen:
        """Add empty line (section separator)."""
        self._lines.append("")
        return self

    def line(self, text: str) -> Screen:
        """Add arbitrary text line."""
        self._lines.append(text)
        return self

    def field(self, icon: str, label: str, value: str | int) -> Screen:
        """Add field: {icon} {label}: {value}"""
        self._lines.append(f"{icon} {label}: {value}")
        return self

    def field_if(self, icon: str, label: str, value: str | None, *, max_len: int = 60) -> Screen:
        """Add field only if value is truthy. Truncate long values."""
        if not value:
            return self
        display = value[:max_len] + "\u2026" if len(value) > max_len else value
        self._lines.append(f"{icon} {label}: {display}")
        return self

    def check(self, label: str, ok: bool, detail: str = "") -> Screen:
        """Add checklist item: {CHECK/CLOSE} {label} -- {detail}"""
        icon = E.CHECK if ok else E.CLOSE
        suffix = f" \u2014 {detail}" if detail else ""
        self._lines.append(f"{icon} {label}{suffix}")
        return self

    def section(self, icon: str, title: str) -> Screen:
        """Add section header with blank line before it."""
        self._lines.append("")
        self._lines.append(f"{icon} <b>{title}</b>")
        return self

    def separator(self) -> Screen:
        """Add separator line."""
        self._lines.append(SEPARATOR)
        return self

    def hint(self, text: str) -> Screen:
        """Add separator + hint line: ────────── {LIGHTBULB} <i>{text}</i>"""
        self._lines.append(SEPARATOR)
        self._lines.append(f"{E.LIGHTBULB} <i>{text}</i>")
        return self

    def build(self) -> str:
        """Join all lines with newline."""
        return "\n".join(self._lines)
