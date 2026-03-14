"""Tests for legal document handlers in routers/profile.py.

Covers:
- /privacy command handler (sends URL link)
- /terms command handler (sends URL link)
- Legal text compliance (third-party disclosures, token packages)
- Telegraph URL constants
- Profile keyboard legal URL buttons
- Consent keyboard legal URL buttons
- LEGAL_NOTICE in /start for new users
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from bot.texts.legal import (
    LEGAL_NOTICE,
    PRIVACY_POLICY,
    PRIVACY_POLICY_URL,
    TERMS_OF_SERVICE,
    TERMS_OF_SERVICE_URL,
)
from routers.profile import (
    cmd_privacy,
    cmd_terms,
)

# ---------------------------------------------------------------------------
# Legal text compliance
# ---------------------------------------------------------------------------


class TestLegalTexts:
    """Verify legal texts contain all required disclosures."""

    def test_privacy_policy_has_all_services(self) -> None:
        """Privacy policy must disclose all third-party data processors."""
        services = [
            "OpenRouter",
            "Anthropic",
            "DeepSeek",
            "Google",
            "Firecrawl",
            "DataForSEO",
            "Serper",
            "Supabase",
            "Upstash",
            "Telegraph",
            "Kassa",  # partial match for ЮKassa
        ]
        for svc in services:
            assert svc in PRIVACY_POLICY, f"Missing service disclosure: {svc}"

    def test_terms_has_all_packages(self) -> None:
        """Terms must list all token packages (5 tariffs)."""
        assert "1 000 токенов" in TERMS_OF_SERVICE  # mini
        assert "3 500 токенов" in TERMS_OF_SERVICE  # start (3000 + 500 bonus)
        assert "7 200 токенов" in TERMS_OF_SERVICE  # profi (6000 + 1200 bonus)
        assert "18 000 токенов" in TERMS_OF_SERVICE  # business (15000 + 3000 bonus)
        assert "50 000 токенов" in TERMS_OF_SERVICE  # maximum (40000 + 10000 bonus)

    def test_legal_notice_mentions_consent(self) -> None:
        assert "конфиденциальности" in LEGAL_NOTICE
        assert "оферту" in LEGAL_NOTICE
        assert "Принимаю" in LEGAL_NOTICE


# ---------------------------------------------------------------------------
# Telegraph URL constants
# ---------------------------------------------------------------------------


class TestTelegraphUrls:
    """Verify Telegraph URL constants are valid."""

    def test_privacy_url_is_telegraph(self) -> None:
        assert PRIVACY_POLICY_URL.startswith("https://telegra.ph/")

    def test_terms_url_is_telegraph(self) -> None:
        assert TERMS_OF_SERVICE_URL.startswith("https://telegra.ph/")

    def test_urls_are_different(self) -> None:
        assert PRIVACY_POLICY_URL != TERMS_OF_SERVICE_URL


# ---------------------------------------------------------------------------
# Command handlers: /privacy, /terms (now send URL links)
# ---------------------------------------------------------------------------


class TestCmdPrivacy:
    """Tests for /privacy command handler."""

    async def test_sends_privacy_link(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_privacy(message)
        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert PRIVACY_POLICY_URL in call_text

    async def test_response_contains_link_text(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_privacy(message)
        call_text = message.answer.call_args[0][0]
        assert "Политика конфиденциальности" in call_text


class TestCmdTerms:
    """Tests for /terms command handler."""

    async def test_sends_terms_link(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_terms(message)
        message.answer.assert_called_once()
        call_text = message.answer.call_args[0][0]
        assert TERMS_OF_SERVICE_URL in call_text

    async def test_response_contains_link_text(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_terms(message)
        call_text = message.answer.call_args[0][0]
        assert "оферта" in call_text.lower()


# ---------------------------------------------------------------------------
# Profile keyboard: legal URL buttons
# ---------------------------------------------------------------------------


class TestProfileKbLegalButtons:
    """Verify profile keyboard includes legal document URL buttons."""

    def test_profile_kb_has_privacy_url_button(self) -> None:
        from keyboards.inline import profile_kb

        kb = profile_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        privacy_btns = [b for b in all_buttons if b.url == PRIVACY_POLICY_URL]
        assert len(privacy_btns) == 1
        assert privacy_btns[0].text == "Политика"

    def test_profile_kb_has_terms_url_button(self) -> None:
        from keyboards.inline import profile_kb

        kb = profile_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        terms_btns = [b for b in all_buttons if b.url == TERMS_OF_SERVICE_URL]
        assert len(terms_btns) == 1
        assert terms_btns[0].text == "Оферта"

    def test_legal_buttons_on_same_row(self) -> None:
        from keyboards.inline import profile_kb

        kb = profile_kb()
        for row in kb.inline_keyboard:
            urls = [b.url for b in row if b.url]
            if PRIVACY_POLICY_URL in urls:
                assert TERMS_OF_SERVICE_URL in urls, "Privacy and Terms should be on the same row"
                break
        else:
            pytest.fail("No row contains privacy URL button")


# ---------------------------------------------------------------------------
# Consent keyboard: legal URL buttons
# ---------------------------------------------------------------------------


class TestConsentKbLegalButtons:
    """Verify consent keyboard uses URL buttons for legal docs."""

    def test_consent_kb_has_privacy_url(self) -> None:
        from keyboards.inline import consent_kb

        kb = consent_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        privacy_btns = [b for b in all_buttons if b.url == PRIVACY_POLICY_URL]
        assert len(privacy_btns) == 1

    def test_consent_kb_has_terms_url(self) -> None:
        from keyboards.inline import consent_kb

        kb = consent_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        terms_btns = [b for b in all_buttons if b.url == TERMS_OF_SERVICE_URL]
        assert len(terms_btns) == 1

    def test_consent_kb_has_accept_callback(self) -> None:
        from keyboards.inline import consent_kb

        kb = consent_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        accept_btns = [b for b in all_buttons if b.callback_data == "legal:consent:accept"]
        assert len(accept_btns) == 1
        assert accept_btns[0].text == "Принимаю"
