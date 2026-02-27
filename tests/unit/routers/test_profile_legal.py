"""Tests for legal document handlers in routers/profile.py.

Covers:
- /privacy command handler
- /terms command handler
- profile:privacy callback handler
- profile:terms callback handler
- split_message utility
- LEGAL_NOTICE in /start for new users
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.types import InaccessibleMessage

from bot.texts.legal import (
    LEGAL_NOTICE,
    PRIVACY_POLICY,
    PRIVACY_POLICY_CHUNKS,
    TERMS_OF_SERVICE,
    TERMS_OF_SERVICE_CHUNKS,
    split_message,
)
from routers.profile import (
    _send_legal_chunks,
    cb_privacy,
    cb_terms,
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

    def test_legal_notice_references_commands(self) -> None:
        assert "/privacy" in LEGAL_NOTICE
        assert "/terms" in LEGAL_NOTICE


# ---------------------------------------------------------------------------
# _send_legal_chunks helper
# ---------------------------------------------------------------------------


class TestSendLegalChunks:
    """Tests for _send_legal_chunks helper."""

    async def test_sends_all_chunks(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        chunks = ["Part 1", "Part 2", "Part 3"]
        await _send_legal_chunks(message, chunks)
        assert message.answer.call_count == 3
        message.answer.assert_any_call("Part 1")
        message.answer.assert_any_call("Part 2")
        message.answer.assert_any_call("Part 3")

    async def test_sends_single_chunk(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await _send_legal_chunks(message, ["Only one part"])
        message.answer.assert_called_once_with("Only one part")


# ---------------------------------------------------------------------------
# Command handlers: /privacy, /terms
# ---------------------------------------------------------------------------


class TestCmdPrivacy:
    """Tests for /privacy command handler."""

    async def test_sends_privacy_policy(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_privacy(message)
        assert message.answer.call_count == len(PRIVACY_POLICY_CHUNKS)

    async def test_first_chunk_contains_title(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_privacy(message)
        first_call_text = message.answer.call_args_list[0][0][0]
        assert "Политика конфиденциальности" in first_call_text


class TestCmdTerms:
    """Tests for /terms command handler."""

    async def test_sends_terms(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_terms(message)
        assert message.answer.call_count == len(TERMS_OF_SERVICE_CHUNKS)

    async def test_first_chunk_contains_title(self) -> None:
        message = MagicMock()
        message.answer = AsyncMock()
        await cmd_terms(message)
        first_call_text = message.answer.call_args_list[0][0][0]
        assert "оферта" in first_call_text.lower()


# ---------------------------------------------------------------------------
# Callback handlers: profile:privacy, profile:terms
# ---------------------------------------------------------------------------


class TestCbPrivacy:
    """Tests for profile:privacy callback handler."""

    async def test_sends_privacy_via_callback(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock()
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()
        await cb_privacy(callback)
        assert callback.message.answer.call_count == len(PRIVACY_POLICY_CHUNKS)
        callback.answer.assert_called_once()

    async def test_inaccessible_message_returns_early(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()
        await cb_privacy(callback)
        callback.answer.assert_called_once()

    async def test_no_message_returns_early(self) -> None:
        callback = MagicMock()
        callback.message = None
        callback.answer = AsyncMock()
        await cb_privacy(callback)
        callback.answer.assert_called_once()


class TestCbTerms:
    """Tests for profile:terms callback handler."""

    async def test_sends_terms_via_callback(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock()
        callback.message.answer = AsyncMock()
        callback.answer = AsyncMock()
        await cb_terms(callback)
        assert callback.message.answer.call_count == len(TERMS_OF_SERVICE_CHUNKS)
        callback.answer.assert_called_once()

    async def test_inaccessible_message_returns_early(self) -> None:
        callback = MagicMock()
        callback.message = MagicMock(spec=InaccessibleMessage)
        callback.answer = AsyncMock()
        await cb_terms(callback)
        callback.answer.assert_called_once()


# ---------------------------------------------------------------------------
# Profile keyboard: legal buttons
# ---------------------------------------------------------------------------


class TestProfileKbLegalButtons:
    """Verify profile keyboard includes legal document buttons."""

    def test_profile_kb_has_privacy_button(self) -> None:
        from keyboards.inline import profile_kb

        kb = profile_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        privacy_btns = [b for b in all_buttons if b.callback_data == "profile:privacy"]
        assert len(privacy_btns) == 1
        assert privacy_btns[0].text == "Политика"

    def test_profile_kb_has_terms_button(self) -> None:
        from keyboards.inline import profile_kb

        kb = profile_kb()
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        terms_btns = [b for b in all_buttons if b.callback_data == "profile:terms"]
        assert len(terms_btns) == 1
        assert terms_btns[0].text == "Оферта"

    def test_legal_buttons_on_same_row(self) -> None:
        from keyboards.inline import profile_kb

        kb = profile_kb()
        for row in kb.inline_keyboard:
            cbs = [b.callback_data for b in row]
            if "profile:privacy" in cbs:
                assert "profile:terms" in cbs, "Privacy and Terms should be on the same row"
                break
        else:
            pytest.fail("No row contains profile:privacy button")
