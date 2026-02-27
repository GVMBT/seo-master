"""Shared constants for the SEO Master Bot.

S1c: Platform type strings used across routers, services, and repositories.
Centralizes string literals to prevent typos and enable IDE refactoring.
"""

# Platform type identifiers (match platform_connections.platform_type in DB)
PLATFORM_WORDPRESS: str = "wordpress"
PLATFORM_TELEGRAM: str = "telegram"
PLATFORM_VK: str = "vk"
PLATFORM_PINTEREST: str = "pinterest"

# Human-readable platform labels (Russian UI)
PLATFORM_LABELS: dict[str, str] = {
    PLATFORM_WORDPRESS: "WordPress",
    PLATFORM_TELEGRAM: "Телеграм",
    PLATFORM_VK: "ВКонтакте",
    PLATFORM_PINTEREST: "Пинтерест",
}
