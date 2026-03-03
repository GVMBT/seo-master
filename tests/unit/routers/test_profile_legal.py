"""Tests for legal document handlers in routers/profile.py.

Covers:
- /privacy command handler (sends URL link)
- /terms command handler (sends URL link)
- split_message utility
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
    PRIVACY_POLICY_CHUNKS,
    PRIVACY_POLICY_URL,
    TERMS_OF_SERVICE,
    TERMS_OF_SERVICE_CHUNKS,
    TERMS_OF_SERVICE_URL,
    split_message,
)
from routers.profile import (
    cmd_privacy,
    cmd_terms,
)

_MODULE = "routers.profile"


# ---------------------------------------------------------------------------
# split_message tests
# ---------------------------------------------------------------------------


class TestSplitMessage:
    """Tests for bot.texts.legal.split_message."""

    def test_short_text_no_split(self) -> None:
        text = "Hello world"
        result = split_message(text, limit=100)
        assert result == [text]

    def test_exact_limit_no_split(self) -> None:
        text = "A" * 4096
        result = split_message(text, limit=4096)
        assert result == [text]

    def test_splits_on_double_newline(self) -> None:
        part1 = "A" * 100
        part2 = "B" * 100
        text = f"{part1}\n\n{part2}"
        result = split_message(text, limit=150)
        assert len(result) == 2
        assert result[0] == part1
        assert result[1] == part2

    def test_splits_on_single_newline_fallback(self) -> None:
        part1 = "A" * 100
        part2 = "B" * 100
        text = f"{part1}\n{part2}"
        result = split_message(text, limit=150)
        assert len(result) == 2
        assert result[0] == part1
        assert result[1] == part2

    def test_hard_cut_no_newlines(self) -> None:
        text = "A" * 200
        result = split_message(text, limit=100)
        assert len(result) == 2
        assert result[0] == "A" * 100
        assert result[1] == "A" * 100

    def test_multiple_chunks(self) -> None:
        parts = ["Section " + str(i) + " " + "x" * 80 for i in range(5)]
        text = "\n\n".join(parts)
        result = split_message(text, limit=100)
        assert len(result) >= 3

    def test_empty_string(self) -> None:
        result = split_message("")
        assert result == [""]


# ---------------------------------------------------------------------------
# Pre-computed chunks validation
# ---------------------------------------------------------------------------


class TestLegalTexts:
    """Verify pre-computed legal text chunks are valid."""

    def test_privacy_policy_chunks_not_empty(self) -> None:
        assert len(PRIVACY_POLICY_CHUNKS) >= 1

    def test_terms_chunks_not_empty(self) -> None:
        assert len(TERMS_OF_SERVICE_CHUNKS) >= 1

    def test_privacy_chunks_under_limit(self) -> None:
        for chunk in PRIVACY_POLICY_CHUNKS:
            assert len(chunk) <= 4096, f"Chunk too long: {len(chunk)} chars"

    def test_terms_chunks_under_limit(self) -> None:
        for chunk in TERMS_OF_SERVICE_CHUNKS:
            assert len(chunk) <= 4096, f"Chunk too long: {len(chunk)} chars"

    def test_privacy_chunks_reconstruct_original(self) -> None:
        """Joining chunks should cover the full text content."""
        joined = "\n\n".join(PRIVACY_POLICY_CHUNKS)
        # All content from the original must appear in the joined version
        # (split_message drops separators, so we check key phrases)
        assert "Политика конфиденциальности" in joined
        assert "152-ФЗ" in joined
        assert "OpenRouter" in joined
        assert "[EMAIL]" in joined

    def test_terms_chunks_reconstruct_original(self) -> None:
        joined = "\n\n".join(TERMS_OF_SERVICE_CHUNKS)
        assert "Публичная оферта" in joined
        assert "1 токен = 1 рубль" in joined
        assert "438 ГК РФ" in joined
        assert "[EMAIL]" in joined

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
        """Terms must list all token packages."""
        assert "500 токенов" in TERMS_OF_SERVICE
        assert "2 000 токенов" in TERMS_OF_SERVICE
        assert "5 000 токенов" in TERMS_OF_SERVICE

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
