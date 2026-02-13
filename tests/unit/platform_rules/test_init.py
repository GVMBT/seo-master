"""Tests for platform_rules/__init__.py — get_rule_for_platform() factory.

Covers: all 4 platforms, unknown platform ValueError.
"""

from __future__ import annotations

import pytest

from platform_rules import (
    PinterestRule,
    TelegramRule,
    VKRule,
    WordPressRule,
    get_rule_for_platform,
)


class TestGetRuleForPlatform:
    def test_wordpress_returns_wordpress_rule(self) -> None:
        rule = get_rule_for_platform("wordpress")
        assert isinstance(rule, WordPressRule)

    def test_telegram_returns_telegram_rule(self) -> None:
        rule = get_rule_for_platform("telegram")
        assert isinstance(rule, TelegramRule)

    def test_vk_returns_vk_rule(self) -> None:
        rule = get_rule_for_platform("vk")
        assert isinstance(rule, VKRule)

    def test_pinterest_returns_pinterest_rule(self) -> None:
        rule = get_rule_for_platform("pinterest")
        assert isinstance(rule, PinterestRule)

    def test_unknown_platform_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_rule_for_platform("tiktok")

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_rule_for_platform("")

    def test_case_sensitive(self) -> None:
        """Platform identifiers are lowercase only."""
        with pytest.raises(ValueError, match="Unsupported platform"):
            get_rule_for_platform("WordPress")

    def test_returns_new_instance_each_call(self) -> None:
        r1 = get_rule_for_platform("wordpress")
        r2 = get_rule_for_platform("wordpress")
        assert r1 is not r2
