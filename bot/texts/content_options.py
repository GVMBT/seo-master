"""Shared content option constants for project-level content settings.

Used by routers/projects/content_settings.py and keyboards/inline.py.
"""

# Text styles (multi-select)
TEXT_STYLES: list[str] = [
    "Рекламный",
    "Мотивационный",
    "Дружелюбный",
    "Разговорный",
    "Профессиональный",
    "Креативный",
    "Информативный",
    "С юмором",
    "Мужской",
    "Женский",
]

# HTML styles (single-select)
HTML_STYLES: list[str] = [
    "Новостной",
    "Блоговый",
    "Журнальный",
    "Корпоративный",
    "Минималистичный",
    "Креативный",
    "Академический",
    "Интернет-магазин",
    "Лендинг",
    "Портфолио",
]

# Word count presets
WORD_COUNTS: list[int] = [500, 1000, 1500, 2000, 2500, 3000]

# Image styles (multi-select)
IMAGE_STYLES: list[str] = [
    "Фотореалистичный",
    "Аниме",
    "Масляная живопись",
    "Акварель",
    "Мультяшный",
    "Набросок",
    "3D рендер",
    "Пиксель-арт",
    "Минимализм",
    "Киберпанк",
]

# Aspect ratios — ONLY Gemini-supported formats
ASPECT_RATIOS: list[str] = [
    "1:1",
    "2:3",
    "3:2",
    "3:4",
    "4:3",
    "4:5",
    "5:4",
    "9:16",
    "16:9",
    "21:9",
]

# Cameras (multi-select)
CAMERAS: list[str] = [
    "Canon EOS R5",
    "Nikon Z9",
    "Sony A7R IV",
    "Fujifilm X-T4",
    "Leica Q2",
    "Hasselblad X1D",
    "Phase One XF",
    "Pentax 645Z",
    "GoPro Hero",
    "DJI Mavic",
]

# Angles (multi-select)
ANGLES: list[str] = [
    "На уровне глаз",
    "Вид сверху",
    "Снизу вверх",
    "Сверху вниз",
    "Голландский угол",
    "Через плечо",
    "Крупный план",
    "Широкий план",
    "Макро",
    "Аэросъемка",
]

# Quality (multi-select)
QUALITY: list[str] = ["Ultra HD", "RAW", "Кинематограф", "Студийное", "Профессионал", "8K"]

# Tones (multi-select)
TONES: list[str] = ["Теплая", "Пастель", "Нейтральная", "Яркая", "Натуральная"]

# Text on image percentages
TEXT_ON_IMAGE: list[int] = [0, 25, 50, 75, 100]
