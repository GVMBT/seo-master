"""
Константы для настроек изображений платформ
"""

# ═══════════════════════════════════════════════════════════════
# ФОРМАТЫ ИЗОБРАЖЕНИЙ
# ═══════════════════════════════════════════════════════════════

PLATFORM_FORMATS = {
    'pinterest': [
        ('2:3', '📱 2:3 (портрет)'),
        ('1:1', '⬜ 1:1 (квадрат)'),
        ('4:5', '📱 4:5 (портрет)'),
        ('9:16', '📱 9:16 (сторис)'),
        ('3:4', '📱 3:4 (портрет)'),
        ('16:9', '📺 16:9 (широкий)'),
        ('21:9', '📺 21:9 (ультра-широкий)'),
        ('24:9', '📺 24:9 (панорама)'),
    ],
    'telegram': [
        ('16:9', '📺 16:9 (широкий)'),
        ('1:1', '⬜ 1:1 (квадрат)'),
        ('4:3', '📺 4:3 (стандарт)'),
        ('3:2', '📺 3:2 (фото)'),
        ('21:9', '📺 21:9 (ультра-широкий)'),
        ('24:9', '📺 24:9 (панорама)'),
    ],
    'website': [
        ('16:9', '📺 16:9 (широкий)'),
        ('4:3', '📺 4:3 (стандарт)'),
        ('1:1', '⬜ 1:1 (квадрат)'),
        ('3:2', '📺 3:2 (фото)'),
        ('21:9', '📺 21:9 (ультра-широкий)'),
        ('24:9', '📺 24:9 (панорама)'),
    ],
    'vk': [
        ('32:9', '32:9 📹 (супер-панорама)'),
        ('24:9', '24:9 📹 (панорама)'),
        ('21:9', '21:9 🎬 (ультра-широкий)'),
        ('16:9', '16:9 📺 (широкий)'),
        ('16:10', '16:10 🖥 (монитор)'),
        ('3:2', '3:2 📷 (фото)'),
        ('4:3', '4:3 🖼 (классический)'),
        ('5:4', '5:4 🖼 (компактный)'),
        ('1:1', '1:1 ⬜ (квадрат)'),
        ('4:5', '4:5 📱 (портрет)'),
        ('9:16', '9:16 📱 (сторис)'),
        ('2:3', '2:3 📷 (портрет)'),
        ('3:4', '3:4 📄 (портрет)'),
        ('5:7', '5:7 📄 (портрет)'),
        ('A4', 'A4 (7:10) 📄'),
        ('letter', 'Letter (17:22) 📄'),
    ]
}

# ═══════════════════════════════════════════════════════════════
# СТИЛИ ИЗОБРАЖЕНИЙ
# ═══════════════════════════════════════════════════════════════

IMAGE_STYLES = {
    'photorealistic': {
        'name': '📸 Фотореалистичный',
        'prompt': 'photorealistic, high quality, detailed, professional photography, 8k'
    },
    'anime': {
        'name': '🌸 Anime',
        'prompt': 'anime style, manga art, vibrant colors, detailed eyes, Japanese animation'
    },
    'oil_painting': {
        'name': '🎨 Масляная живопись',
        'prompt': 'oil painting, artistic, brush strokes, canvas texture, classical art style'
    },
    'watercolor': {
        'name': '🖌 Акварель',
        'prompt': 'watercolor painting, soft colors, flowing paint, artistic, delicate'
    },
    'cartoon': {
        'name': '🎬 Мультяшный',
        'prompt': 'cartoon style, vibrant colors, simplified shapes, animated look, fun'
    },
    'sketch': {
        'name': '✏️ Набросок',
        'prompt': 'pencil sketch, hand-drawn, artistic, monochrome, detailed linework'
    },
    '3d_render': {
        'name': '🎭 3D рендер',
        'prompt': '3d render, cgi, realistic lighting, high detail, modern graphics'
    },
    'pixel_art': {
        'name': '🎮 Пиксель-арт',
        'prompt': 'pixel art, retro gaming, 8-bit style, blocky, nostalgic'
    },
    'minimalism': {
        'name': '⚪ Минимализм',
        'prompt': 'minimalist, simple, clean lines, modern, elegant, white space, geometric'
    },
    'cyberpunk': {
        'name': '🔮 Киберпанк',
        'prompt': 'cyberpunk style, neon lights, futuristic, dark atmosphere, high tech, dystopian'
    }
}

# ═══════════════════════════════════════════════════════════════
# ТОНАЛЬНОСТЬ
# ═══════════════════════════════════════════════════════════════

TONE_PRESETS = {
    'warm': {
        'name': '🔥 Теплая',
        'prompt': 'warm tones, golden lighting, cozy atmosphere, orange and yellow hues'
    },
    'cold': {
        'name': '❄️ Холодная',
        'prompt': 'cool tones, blue lighting, cold atmosphere, blue and cyan hues'
    },
    'neutral': {
        'name': '🤍 Нейтральная',
        'prompt': 'neutral colors, balanced tones, natural lighting, realistic color palette'
    },
    'vibrant': {
        'name': '🌈 Яркая',
        'prompt': 'vibrant and saturated, bold colors, high contrast, vivid hues'
    },
    'pastel': {
        'name': '🎨 Пастель',
        'prompt': 'pastel colors, soft tones, gentle palette, light and airy'
    },
    'monochrome': {
        'name': '⬛ Монохром',
        'prompt': 'monochrome, single color palette, tonal variations'
    },
    'sepia': {
        'name': '🍂 Сепия',
        'prompt': 'sepia tone, vintage brown tones, nostalgic atmosphere'
    },
    'vintage': {
        'name': '🌸 Винтаж',
        'prompt': 'vintage filter, faded colors, retro aesthetic, film grain'
    },
    'neon': {
        'name': '💡 Неон',
        'prompt': 'neon colors, glowing lights, cyberpunk aesthetic, bright electric hues'
    },
    'natural': {
        'name': '🌿 Натуральна',
        'prompt': 'natural colors, earthy tones, organic palette, true to life'
    },
    'bw': {
        'name': '⬜ Черно-белое',
        'prompt': 'black and white, high contrast, dramatic shadows, grayscale'
    },
    'dark': {
        'name': '🌑 Темная',
        'prompt': 'dark and moody, low key lighting, deep shadows, dramatic atmosphere'
    }
}

# ═══════════════════════════════════════════════════════════════
# КАМЕРЫ
# ═══════════════════════════════════════════════════════════════

CAMERA_PRESETS = {
    'canon_r5': {
        'name': '📷 Canon EOS R5',
        'prompt': 'Canon EOS R5, 50mm f/1.2 lens, shallow depth of field'
    },
    'nikon_z9': {
        'name': '📷 Nikon Z9',
        'prompt': 'Nikon Z9, 85mm f/1.4 lens, professional mirrorless'
    },
    'sony_a7r': {
        'name': '📷 Sony A7R IV',
        'prompt': 'Sony A7R IV, 85mm f/1.4 lens, portrait photography'
    },
    'fujifilm_xt4': {
        'name': '📷 Fujifilm X-T4',
        'prompt': 'Fujifilm X-T4, 35mm f/1.4 lens, film simulation aesthetic'
    },
    'leica_q2': {
        'name': '📷 Leica Q2',
        'prompt': 'Leica Q2, 28mm f/1.7 lens, premium compact camera'
    },
    'hasselblad': {
        'name': '📷 Hasselblad X1D',
        'prompt': 'Hasselblad X1D, 80mm lens, medium format, ultra high resolution'
    },
    'phase_one': {
        'name': '📷 Phase One XF',
        'prompt': 'Phase One XF, 80mm lens, medium format, studio quality'
    },
    'pentax_645z': {
        'name': '📷 Pentax 645Z',
        'prompt': 'Pentax 645Z, medium format, 75mm lens, landscape photography'
    },
    'gopro': {
        'name': '⚡ GoPro Hero',
        'prompt': 'GoPro Hero, ultra-wide lens, action shot perspective'
    },
    'dji_mavic': {
        'name': '📷 DJI Mavic',
        'prompt': 'DJI Mavic 3, aerial perspective, drone shot from above'
    }
}

# ═══════════════════════════════════════════════════════════════
# РАКУРСЫ И УГЛЫ ОБЗОРА
# ═══════════════════════════════════════════════════════════════

ANGLE_PRESETS = {
    'eye_level': {
        'name': '👁 На уровне глаз',
        'prompt': 'eye level shot, neutral perspective, straight on view'
    },
    'aerial': {
        'name': '🦅 Вид сверху',
        'prompt': 'aerial view, top-down perspective, bird eye view, drone shot'
    },
    'low_angle': {
        'name': '⬇️ Снизу вверх',
        'prompt': 'low angle shot, looking up, dramatic perspective from below'
    },
    'high_angle': {
        'name': '⬆️ Сверху вниз',
        'prompt': 'high angle shot, looking down, overhead perspective'
    },
    'dutch_angle': {
        'name': '🎯 Голландский угол',
        'prompt': 'dutch angle, tilted camera, dynamic diagonal composition'
    },
    'close_up': {
        'name': '🔍 Крупный план',
        'prompt': 'close-up shot, detailed view, focused subject'
    },
    'wide': {
        'name': '🖼 Широкий план',
        'prompt': 'wide shot, landscape view, environmental context'
    },
    'over_shoulder': {
        'name': '📸 Через плечо',
        'prompt': 'over the shoulder shot, conversation perspective'
    },
    'macro': {
        'name': '🎬 Макро',
        'prompt': 'extreme close-up, macro photography, detailed texture, shallow depth of field'
    },
    'drone': {
        'name': '🎥 Аэросъёмка',
        'prompt': 'drone shot, aerial cinematography, sweeping vista'
    }
}

# ═══════════════════════════════════════════════════════════════
# УРОВЕНЬ ДЕТАЛИЗАЦИИ И КАЧЕСТВО
# ═══════════════════════════════════════════════════════════════

QUALITY_PRESETS = {
    'ultra_hd': {
        'name': '💎 Ultra HD',
        'prompt': 'ultra HD, 4K resolution, ultra high definition, exceptional clarity'
    },
    '8k': {
        'name': '📷 8K',
        'prompt': '8K resolution, 7680x4320, extreme detail, professional cinema quality'
    },
    '4k': {
        'name': '🎬 4K',
        'prompt': '4K resolution, ultra high definition, 3840x2160, crystal clear'
    },
    'full_hd': {
        'name': '📺 Full HD',
        'prompt': 'Full HD quality, 1920x1080, high definition, crisp and clear'
    },
    'hd': {
        'name': '📱 HD',
        'prompt': 'HD quality, 1280x720, high definition, clear image'
    },
    'professional': {
        'name': '⭐ Профессиональ',
        'prompt': 'professional quality, masterpiece, award winning, studio grade'
    },
    'studio': {
        'name': '🎨 Студийное',
        'prompt': 'studio quality lighting, professional photography, commercial grade'
    },
    'raw': {
        'name': '📸 RAW',
        'prompt': 'RAW format quality, uncompressed, maximum dynamic range, professional'
    },
    'hdr': {
        'name': '🌈 HDR',
        'prompt': 'HDR quality, high dynamic range, rich colors, enhanced contrast'
    },
    'cinematic': {
        'name': '🎞 Кинематограф',
        'prompt': 'cinematic quality, film grade, Hollywood production value, epic detail'
    },
    'ultra_sharp': {
        'name': '⚡ Максимальная резкость',
        'prompt': 'ultra sharp, tack sharp, crystal clear, perfect focus, razor sharp details'
    },
    'hyperrealistic': {
        'name': '✨ Гиперреализм',
        'prompt': 'hyperrealistic, photorealistic perfection, lifelike, indistinguishable from reality'
    }
}

# ═══════════════════════════════════════════════════════════════
# РЕКОМЕНДАЦИИ ПО ПЛАТФОРМАМ
# ═══════════════════════════════════════════════════════════════

RECOMMENDED_FORMATS = {
    'pinterest': '2:3',
    'telegram': '16:9',
    'website': '16:9',
    'vk': '16:9'           # Широкий стандарт
}

# Названия платформ для отображения
PLATFORM_NAMES = {
    'pinterest': 'Pinterest',
    'telegram': 'Telegram',
    'website': 'Website',
    'vk': 'VK'
}


# ═══════════════════════════════════════════════════════════════
# ТЕКСТ НА ИЗОБРАЖЕНИИ
# ═══════════════════════════════════════════════════════════════

TEXT_ON_IMAGE_PRESETS = {
    '0': '🚫 Никогда (0%)',
    '10': '📝 Редко (10%)',
    '20': '📝 Иногда (20%)',
    '30': '📝 Часто (30%)',
    '50': '📝 Половина (50%)',
    '70': '📝 Большинство (70%)',
    '100': '📝 Всегда (100%)'
}

TEXT_STYLES_DESCRIPTION = """
📝 <b>Текст на изображении</b>

Процент показывает, как часто на изображениях будет текст:
• 0% - текст никогда не добавляется
• 10% - каждое 10-е изображение с текстом
• 50% - половина изображений с текстом
• 100% - все изображения с текстом

<b>Стиль текста:</b> журнальные надписи, заголовки, подписи
<i>Пример: "НОВИНКА 2024", "TOP 5", "Exclusive"</i>
"""


# ═══════════════════════════════════════════════════════════════
# КОЛЛАЖ ИЛИ ЦЕЛЬНОЕ ИЗОБРАЖЕНИЕ
# ═══════════════════════════════════════════════════════════════

COLLAGE_PRESETS = {
    '0': '🖼️ Всегда цельное (0%)',
    '10': '🎨 Редко коллаж (10%)',
    '20': '🎨 Иногда коллаж (20%)',
    '30': '🎨 Часто коллаж (30%)',
    '50': '🎨 Половина коллажей (50%)',
    '70': '🎨 Много коллажей (70%)',
    '100': '🎨 Всегда коллаж (100%)'
}

COLLAGE_DESCRIPTION = """
🎨 <b>Коллаж или цельное изображение</b>

Процент показывает, как часто будет создаваться коллаж:
• 0% - всегда цельное изображение
• 10% - каждое 10-е изображение коллаж
• 50% - половина изображений коллажи
• 100% - все изображения коллажи

<b>Коллаж:</b> несколько элементов на одном изображении
<b>Цельное:</b> одна композиция, один объект
"""


print("✅ platform_settings/constants.py загружен")

