"""Platform-specific content validation rules.

Factory function ``get_rule_for_platform`` returns the appropriate
``PlatformRule`` subclass for a given platform identifier.
"""

from __future__ import annotations

from platform_rules.base import PlatformRule, ValidationResult
from platform_rules.pinterest import PinterestRule
from platform_rules.telegram import TelegramRule
from platform_rules.vk import VKRule
from platform_rules.wordpress import WordPressRule

__all__ = [
    "PinterestRule",
    "PlatformRule",
    "TelegramRule",
    "VKRule",
    "ValidationResult",
    "WordPressRule",
    "get_rule_for_platform",
]

_RULES: dict[str, type[PlatformRule]] = {
    "wordpress": WordPressRule,
    "telegram": TelegramRule,
    "vk": VKRule,
    "pinterest": PinterestRule,
}


def get_rule_for_platform(platform: str) -> PlatformRule:
    """Return a PlatformRule instance for the given platform identifier.

    Raises ``ValueError`` if the platform is not supported.
    """
    rule_cls = _RULES.get(platform)
    if rule_cls is None:
        raise ValueError(f"Unsupported platform: {platform!r}")
    return rule_cls()
