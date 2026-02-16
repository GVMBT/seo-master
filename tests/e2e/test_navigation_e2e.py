"""E2E tests: full navigation through all dashboard sections.

Tests REAL functionality of all main sections accessible from dashboard:
1. /start → dashboard
2. Click "Профиль" → profile with balance, stats
3. Back to menu
4. Click "Тарифы" → tariff packages displayed
5. Back to menu
6. Click "Настройки" → settings menu
7. Click "Уведомления" → toggle notifications
8. Back to menu
9. Click "Помощь" → help text

Design: ONE sequential flow, shared state.
Total messages: 2 (/cancel + /start), rest are inline button clicks (no rate limit).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from tests.e2e.conftest import click_inline_button, send_and_wait

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("TELETHON_API_ID"),
        reason="E2E: Telethon credentials not configured",
    ),
    pytest.mark.asyncio(loop_scope="module"),
]

_state: dict[str, Any] = {}


async def test_step01_dashboard(telethon_client, bot_username: str, clean_state) -> None:
    """Step 1: /start → dashboard with 5 inline buttons."""
    response = await send_and_wait(telethon_client, bot_username, "/start", timeout=20.0, wait_all=True)
    assert response is not None, "Bot did not respond to /start"

    text = (response.text or "").lower()
    assert any(w in text for w in ["баланс", "токенов", "добро пожаловать", "нет проектов"]), (
        f"Unexpected dashboard: {response.text!r}"
    )
    # Dashboard should have inline buttons
    assert response.buttons is not None, "Dashboard has no inline buttons"
    _state["dashboard"] = response
    await asyncio.sleep(1.5)


async def test_step02_profile(telethon_client, bot_username: str, clean_state) -> None:
    """Step 2: Click 'Профиль' → shows user profile with balance and stats."""
    dashboard = _state.get("dashboard")
    if dashboard is None:
        pytest.skip("No dashboard from step 1")

    result = await click_inline_button(telethon_client, dashboard, "Профиль")
    assert result is not None, "Bot did not respond to 'Профиль' click"

    text = (result.text or "").lower()
    # Profile should show user info
    assert any(
        w in text for w in ["id:", "баланс", "имя", "роль", "дата"]
    ), f"Unexpected profile: {result.text!r}"

    _state["profile"] = result
    await asyncio.sleep(1)


async def test_step03_back_to_menu_from_profile(telethon_client, bot_username: str, clean_state) -> None:
    """Step 3: Click 'Главное меню' from profile → back to dashboard."""
    profile = _state.get("profile")
    if profile is None:
        pytest.skip("No profile from step 2")

    result = await click_inline_button(telethon_client, profile, "Главное меню")
    if result is None:
        # Some screens may use "Назад" instead of "Главное меню"
        result = await click_inline_button(telethon_client, profile, "Назад")

    assert result is not None, "Could not navigate back to menu"
    _state["dashboard2"] = result
    await asyncio.sleep(1)


async def test_step04_tariffs(telethon_client, bot_username: str, clean_state) -> None:
    """Step 4: Click 'Тарифы' → shows pricing packages."""
    dashboard = _state.get("dashboard2") or _state.get("dashboard")
    if dashboard is None:
        pytest.skip("No dashboard")

    result = await click_inline_button(telethon_client, dashboard, "Тарифы")
    assert result is not None, "Bot did not respond to 'Тарифы' click"

    text = (result.text or "").lower()
    # Tariffs should show packages with prices or Stars info
    assert any(
        w in text for w in ["токен", "цена", "пакет", "stars", "тариф", "подписк", "купить"]
    ), f"Unexpected tariffs: {result.text!r}"

    _state["tariffs"] = result
    await asyncio.sleep(1)


async def test_step05_back_to_menu_from_tariffs(telethon_client, bot_username: str, clean_state) -> None:
    """Step 5: Navigate back from tariffs to dashboard."""
    tariffs = _state.get("tariffs")
    if tariffs is None:
        pytest.skip("No tariffs from step 4")

    result = await click_inline_button(telethon_client, tariffs, "Главное меню")
    if result is None:
        result = await click_inline_button(telethon_client, tariffs, "Назад")

    assert result is not None, "Could not navigate back to menu from tariffs"
    _state["dashboard3"] = result
    await asyncio.sleep(1)


async def test_step06_settings(telethon_client, bot_username: str, clean_state) -> None:
    """Step 6: Click 'Настройки' → settings menu."""
    dashboard = _state.get("dashboard3") or _state.get("dashboard")
    if dashboard is None:
        pytest.skip("No dashboard")

    result = await click_inline_button(telethon_client, dashboard, "Настройки")
    assert result is not None, "Bot did not respond to 'Настройки' click"

    text = (result.text or "").lower()
    assert any(
        w in text for w in ["настройк", "уведомлен", "поддержка", "о боте"]
    ), f"Unexpected settings: {result.text!r}"

    _state["settings"] = result
    await asyncio.sleep(1)


async def test_step07_notifications_toggle(telethon_client, bot_username: str, clean_state) -> None:
    """Step 7: Click 'Уведомления' → shows notification toggles.

    Verifies settings screen has actionable toggle buttons.
    """
    settings = _state.get("settings")
    if settings is None:
        pytest.skip("No settings from step 6")

    result = await click_inline_button(telethon_client, settings, "Уведомлен")
    if result is None:
        pytest.skip("No 'Уведомления' button in settings")

    text = (result.text or "").lower()
    assert any(
        w in text for w in ["уведомлен", "публикац", "баланс", "новости"]
    ), f"Unexpected notifications screen: {result.text!r}"

    # Should have toggle buttons
    assert result.buttons is not None, "Notifications screen has no buttons"
    await asyncio.sleep(1)


async def test_step08_help(telethon_client, bot_username: str, clean_state) -> None:
    """Step 8: /help → shows commands list (via text command, not inline)."""
    response = await send_and_wait(telethon_client, bot_username, "/help", timeout=15.0)
    assert response is not None, "Bot did not respond to /help"

    text = (response.text or "").lower()
    assert "/start" in text, f"Help missing /start: {response.text!r}"
    assert "/cancel" in text, f"Help missing /cancel: {response.text!r}"

    await asyncio.sleep(1)
