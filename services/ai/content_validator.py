"""Content validation: placeholder detection, length checks, structure.

Source of truth: API_CONTRACTS.md section 3.7.
"""

import re
from dataclasses import dataclass, field

PLACEHOLDER_PATTERNS: list[str] = [
    r"\[INSERT",
    r"Lorem ipsum",
    r"\bTODO\b",
    r"\[YOUR",
    r"<placeholder>",
    r"\{заполнить\}",
    r"ПРИМЕР ТЕКСТА",
]

# Platform-specific limits
PLATFORM_LIMITS: dict[str, dict[str, int]] = {
    "telegram": {"max_text": 4096, "max_caption": 1024},
    "vk": {"max_text": 16384},
    "pinterest": {"max_description": 500, "max_title": 100},
    "wordpress": {"min_article": 500},
}


@dataclass
class ValidationResult:
    """Result of content validation."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ContentValidator:
    """Validates generated content before publishing."""

    def validate(
        self,
        content: str,
        content_type: str,
        platform: str,
    ) -> ValidationResult:
        """Validate content against rules for content_type and platform."""
        errors: list[str] = []
        warnings: list[str] = []

        # Common: placeholder detection
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                errors.append(f"Обнаружен placeholder-текст: {pattern}")

        # Common: minimum length for articles
        wp_limits = PLATFORM_LIMITS["wordpress"]
        if content_type == "article" and len(content) < wp_limits["min_article"]:
            errors.append(f"Текст слишком короткий ({len(content)} символов, мин. {wp_limits['min_article']})")

        # WordPress article structure
        if platform == "wordpress" and content_type == "article":
            if not re.search(r"<h1[^>]*>", content):
                errors.append("Отсутствует H1-заголовок")
            h1_count = len(re.findall(r"<h1[^>]*>", content))
            if h1_count > 1:
                errors.append(f"Несколько H1-заголовков ({h1_count}) — допускается только один")
            if not re.search(r"<p[^>]*>.{50,}", content):
                errors.append("Нет абзацев связного текста (мин. 50 символов)")

        # Platform-specific length for social posts
        if content_type == "social_post":
            tg = PLATFORM_LIMITS["telegram"]
            vk = PLATFORM_LIMITS["vk"]
            pin = PLATFORM_LIMITS["pinterest"]

            if platform == "telegram" and len(content) > tg["max_text"]:
                errors.append(f"Текст превышает лимит Telegram ({len(content)}/{tg['max_text']})")

            if platform == "vk" and len(content) > vk["max_text"]:
                errors.append(f"Текст превышает лимит VK ({len(content)}/{vk['max_text']})")

            if platform == "pinterest" and len(content) > pin["max_description"]:
                errors.append(f"Описание превышает лимит Pinterest ({len(content)}/{pin['max_description']})")

        # Warnings (non-blocking)
        if content_type == "article" and "faq" not in content.lower():
            warnings.append("Нет FAQ-секции")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def validate_images_meta(
        self,
        images_meta: list[dict[str, str]],
        expected_count: int,
        main_phrase: str,
    ) -> ValidationResult:
        """Validate AI-generated images_meta before reconciliation (API_CONTRACTS.md §3.7)."""
        errors: list[str] = []
        warnings: list[str] = []

        if len(images_meta) != expected_count:
            warnings.append(f"images_meta count ({len(images_meta)}) != expected ({expected_count})")

        for i, meta in enumerate(images_meta):
            # alt must not be empty
            alt = meta.get("alt", "").strip()
            if not alt:
                errors.append(f"images_meta[{i}].alt is empty")
            elif main_phrase.lower() not in alt.lower():
                warnings.append(f"images_meta[{i}].alt does not contain main_phrase")

            # filename must be valid slug (latin lowercase, hyphens, digits)
            fn = meta.get("filename", "")
            if not fn or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", fn):
                errors.append(f"images_meta[{i}].filename is not a valid slug: '{fn}'")
            if len(fn) > 180:
                errors.append(f"images_meta[{i}].filename too long ({len(fn)} chars)")

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
