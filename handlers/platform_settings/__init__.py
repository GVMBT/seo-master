"""
Platform Settings Package
Управление настройками изображений для платформ (Pinterest, Telegram, Website)

Включает:
- Выбор форматов изображений (множественный)
- Выбор стилей изображения (фотореализм, аниме и т.д.)
- Выбор тональности (черно-белое, золотой час и т.д.)
- Выбор камеры (Canon, Sony, iPhone и т.д.)
- Выбор ракурса (макро, aerial, вид сверху и т.д.)
- Выбор качества (HD, 4K, 8K, гиперреализм и т.д.)
"""

from .constants import (
    PLATFORM_FORMATS,
    IMAGE_STYLES,
    TONE_PRESETS,
    CAMERA_PRESETS,
    ANGLE_PRESETS,
    QUALITY_PRESETS,
    RECOMMENDED_FORMATS,
    TEXT_ON_IMAGE_PRESETS,
    COLLAGE_PRESETS
)

from .utils import (
    get_platform_settings,
    save_platform_settings,
    build_image_prompt
)

# Импортируем обработчики (они регистрируются автоматически)
from . import format_selector
from . import style_selector
from . import tone_camera_selector
from . import angle_selector
from . import quality_selector
from . import text_collage_selector

# Регистрируем angle и quality handlers
from loader import bot as bot_instance
angle_selector.register_angle_handlers(bot_instance)
quality_selector.register_quality_handlers(bot_instance)

__all__ = [
    'PLATFORM_FORMATS',
    'IMAGE_STYLES',
    'TONE_PRESETS',
    'CAMERA_PRESETS',
    'ANGLE_PRESETS',
    'QUALITY_PRESETS',
    'RECOMMENDED_FORMATS',
    'TEXT_ON_IMAGE_PRESETS',
    'COLLAGE_PRESETS',
    'get_platform_settings',
    'save_platform_settings',
    'build_image_prompt',
    'format_selector',
    'style_selector',
    'tone_camera_selector',
    'angle_selector',
    'quality_selector',
    'text_collage_selector'
]

