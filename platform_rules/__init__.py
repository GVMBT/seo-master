# -*- coding: utf-8 -*-
"""
Platform Rules
Правила и ограничения для различных платформ
"""

from .platforms_registry import (
    get_platform_rules,
    platform_exists,
    get_all_platforms,
    PlatformRules
)

__all__ = [
    'get_platform_rules',
    'platform_exists',
    'get_all_platforms',
    'PlatformRules'
]
