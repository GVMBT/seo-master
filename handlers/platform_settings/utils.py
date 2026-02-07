"""
Утилиты для работы с настройками изображений платформ
"""
import json
import random
from .constants import IMAGE_STYLES, TONE_PRESETS, CAMERA_PRESETS, ANGLE_PRESETS, QUALITY_PRESETS, RECOMMENDED_FORMATS


def get_platform_settings(category, platform_type):
    """
    Получить настройки изображений для платформы
    
    Args:
        category: dict - данные категории из БД
        platform_type: str - тип платформы (pinterest/telegram/website)
        
    Returns:
        dict: {
            'formats': ['2:3', '16:9'],
            'styles': ['photorealistic', 'anime'],
            'tones': ['golden_hour'],
            'cameras': ['canon_r5'],
            'angles': ['macro', 'aerial'],
            'quality': ['8k', 'hyperrealistic']
        }
    """
    # Конвертируем RealDictRow в dict
    if not isinstance(category, dict):
        category = dict(category)
    
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    # Ключи для настроек
    formats_key = f'{platform_type}_image_formats'
    styles_key = f'{platform_type}_image_styles'
    tones_key = f'{platform_type}_tones'
    cameras_key = f'{platform_type}_cameras'
    angles_key = f'{platform_type}_angles'
    quality_key = f'{platform_type}_quality'
    
    # Получаем значения
    formats = settings.get(formats_key, [RECOMMENDED_FORMATS.get(platform_type, '16:9')])
    styles = settings.get(styles_key, [])
    tones = settings.get(tones_key, [])
    cameras = settings.get(cameras_key, ['gopro'])  # По умолчанию GoPro
    angles = settings.get(angles_key, ['eye_level'])  # По умолчанию на уровне глаз
    quality = settings.get(quality_key, ['ultra_hd'])  # По умолчанию Ultra HD
    
    # Новые настройки
    text_percent = settings.get(f'{platform_type}_text_percent', '0')
    collage_percent = settings.get(f'{platform_type}_collage_percent', '0')
    html_style = settings.get(f'{platform_type}_html_style', 'news')
    
    # Форматы всегда должны быть
    if not formats or len(formats) == 0:
        formats = [RECOMMENDED_FORMATS.get(platform_type, '16:9')]
    
    print(f"📖 Прочитаны настройки для platform={platform_type}:")
    print(f"   Formats: {formats}")
    print(f"   Styles: {styles}")
    print(f"   Tones: {tones}")
    
    return {
        'formats': formats,
        'styles': styles,
        'tones': tones,
        'cameras': cameras,
        'angles': angles,
        'quality': quality,
        'text_percent': text_percent,
        'collage_percent': collage_percent,
        'html_style': html_style
    }


def get_text_style_settings(category, platform_type):
    """
    Получить настройки стиля текста для платформы
    
    Args:
        category: dict - данные категории из БД
        platform_type: str - тип платформы (pinterest/telegram/website/vk)
        
    Returns:
        str: случайный стиль текста из настроек пользователя
    """
    # Конвертируем RealDictRow в dict
    if not isinstance(category, dict):
        category = dict(category)
    
    settings = category.get('settings', {})
    if isinstance(settings, str):
        settings = json.loads(settings)
    
    # Получаем список стилей текста
    text_styles_key = f'{platform_type}_text_styles'
    text_styles = settings.get(text_styles_key, [])
    
    # Если список не является списком (обратная совместимость)
    if not isinstance(text_styles, list):
        text_styles = [text_styles] if text_styles else []
    
    # Если стили не заданы - используем дефолтный
    if not text_styles:
        text_styles = ['engaging']
    
    # Выбираем случайный стиль
    selected_style = random.choice(text_styles)
    
    print(f"📝 Выбран стиль текста для {platform_type}: {selected_style} (из {len(text_styles)} доступных)")
    
    return selected_style


def save_platform_settings(db, category_id, platform_type, formats=None, styles=None, tones=None, cameras=None, angles=None, quality=None, text_percent=None, collage_percent=None):
    """
    Сохранить настройки изображений в БД
    
    📝 Инструкция:
    Функция принимает настройки изображений и сохраняет их в БД.
    Только переданные параметры будут обновлены, остальные останутся без изменений.
    
    Args:
        db: database instance
        category_id: int
        platform_type: str
        formats: list - список форматов
        styles: list - список стилей
        tones: list - список тональностей
        cameras: list - список камер
        angles: list - список ракурсов
        quality: list - список уровней качества
        text_percent: str - процент изображений с текстом ('0'-'100')
        collage_percent: str - процент коллажей ('0'-'100')
        
    Returns:
        bool: True если успешно
    """
    try:
        # Откатываем любую незавершенную транзакцию
        try:
            db.conn.rollback()
        except Exception:
            pass
        
        # Получаем текущие настройки
        category = db.get_category(category_id)
        if not category:
            return False
        
        # Конвертируем RealDictRow в dict
        if not isinstance(category, dict):
            category = dict(category)
        
        settings = category.get('settings', {})
        if isinstance(settings, str):
            settings = json.loads(settings)
        
        # Обновляем только переданные параметры
        if formats is not None:
            settings[f'{platform_type}_image_formats'] = formats
        if styles is not None:
            settings[f'{platform_type}_image_styles'] = styles
        if tones is not None:
            settings[f'{platform_type}_tones'] = tones
        if cameras is not None:
            settings[f'{platform_type}_cameras'] = cameras
        if angles is not None:
            settings[f'{platform_type}_angles'] = angles
        if quality is not None:
            settings[f'{platform_type}_quality'] = quality
        if text_percent is not None:
            settings[f'{platform_type}_text_percent'] = text_percent
        if collage_percent is not None:
            settings[f'{platform_type}_collage_percent'] = collage_percent
        
        # Сохраняем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(settings), category_id))
        rows_updated = db.cursor.rowcount
        db.conn.commit()
        
        print(f"✅ Сохранены настройки для категории {category_id} (обновлено строк: {rows_updated}):")
        print(f"   Platform: {platform_type}")
        if formats is not None:
            print(f"   Formats: {formats}")
        if styles is not None:
            print(f"   Styles: {styles}")
        if tones is not None:
            print(f"   Tones: {tones}")
        if cameras is not None:
            print(f"   Cameras: {cameras}")
        if angles is not None:
            print(f"   Angles: {angles}")
        if quality is not None:
            print(f"   Quality: {quality}")
        
        # Проверяем что данные действительно сохранились
        if rows_updated == 0:
            print(f"⚠️ WARNING: Ни одна строка не обновлена! category_id={category_id} не существует?")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения настроек: {e}")
        try:
            db.conn.rollback()
        except Exception:
            pass
        return False


def save_platform_settings_simple(category, platform_type, settings_dict):
    """
    Упрощенная функция сохранения настроек
    Принимает готовый словарь settings и сохраняет его в категорию
    
    Args:
        category: dict/RealDictRow - объект категории из БД
        platform_type: str - website/telegram/pinterest
        settings_dict: dict - словарь с настройками {'cameras': [...], 'angles': [...], etc}
    
    Returns:
        bool: True если успешно
    """
    try:
        from loader import db
        
        # Конвертируем RealDictRow в dict
        if not isinstance(category, dict):
            category = dict(category)
        
        category_id = category['id']
        
        # Получаем текущие настройки категории
        current_settings = category.get('settings', {})
        if isinstance(current_settings, str):
            current_settings = json.loads(current_settings)
        
        # Обновляем настройки для платформы
        for key, value in settings_dict.items():
            setting_key = f'{platform_type}_{key}'
            current_settings[setting_key] = value
        
        # Сохраняем в БД
        db.cursor.execute("""
            UPDATE categories
            SET settings = %s::jsonb
            WHERE id = %s
        """, (json.dumps(current_settings), category_id))
        db.conn.commit()
        
        return True
    except Exception as e:
        print(f"❌ Ошибка сохранения настроек: {e}")
        import traceback
        traceback.print_exc()
        try:
            db.conn.rollback()
        except Exception:
            pass
        return False


def build_image_prompt(base_prompt, platform_settings, use_first_format=False):
    """
    Построить промпт для генерации изображения
    
    📝 Инструкция:
    1. Базовый промпт передаётся первым аргументом
    2. platform_settings содержит все настройки из get_platform_settings()
    3. Функция автоматически добавляет:
       - Случайный формат изображения (или первый если use_first_format=True)
       - Стиль (если выбран)
       - Тональность (если выбрана)
       - Камеру (если выбрана)
       - Ракурс (если выбран)
       - Качество (если выбрано)
       - Текст на изображении (по проценту)
       - Коллаж (по проценту)
    
    Args:
        base_prompt: str - базовый промпт (название + описание)
        platform_settings: dict - настройки из get_platform_settings()
        use_first_format: bool - использовать первый формат вместо случайного (для обложки)
        
    Returns:
        tuple: (prompt, format)
    """
    print("\n" + "="*80)
    print("🎨 \033[95mПРОМПТ ДЛЯ ГЕНЕРАЦИИ ИЗОБРАЖЕНИЯ (NANO BANANA PRO)\033[0m")
    print("="*80)
    
    print("\n\033[93m1. БАЗОВЫЙ ПРОМПТ:\033[0m")
    print(f"   {base_prompt}")
    
    prompt = base_prompt
    
    # Выбираем формат
    if use_first_format and platform_settings['formats']:
        image_format = platform_settings['formats'][0]  # Первый формат для обложки
    else:
        image_format = random.choice(platform_settings['formats'])  # Случайный для остальных
    
    print(f"\n\033[93m2. ФОРМАТ ИЗОБРАЖЕНИЯ:\033[0m")
    print(f"   • Выбран: \033[92m{image_format}\033[0m")
    print(f"   • Тип выбора: {'Первый (обложка)' if use_first_format else 'Случайный'}")
    print(f"   • Доступные форматы: {', '.join(platform_settings['formats'])}")
    
    # Добавляем стиль если выбран
    selected_style = None
    if platform_settings['styles']:
        selected_style = random.choice(platform_settings['styles'])
        style_prompt = IMAGE_STYLES.get(selected_style, {}).get('prompt', '')
        if style_prompt:
            prompt += f". {style_prompt}"
    
    print(f"\n\033[93m3. СТИЛЬ ИЗОБРАЖЕНИЯ:\033[0m")
    if selected_style:
        style_name = IMAGE_STYLES.get(selected_style, {}).get('name', selected_style)
        print(f"   • Выбран: \033[92m{style_name}\033[0m")
        print(f"   • Промпт: {IMAGE_STYLES.get(selected_style, {}).get('prompt', '')}")
        print(f"   • Доступные: {len(platform_settings['styles'])} стилей")
    else:
        print("   • Стиль не выбран (любой)")
    
    # Добавляем тональность если выбрана
    selected_tone = None
    if platform_settings['tones']:
        selected_tone = random.choice(platform_settings['tones'])
        tone_prompt = TONE_PRESETS.get(selected_tone, {}).get('prompt', '')
        if tone_prompt:
            prompt += f". {tone_prompt}"
    
    print(f"\n\033[93m4. ТОНАЛЬНОСТЬ:\033[0m")
    if selected_tone:
        tone_name = TONE_PRESETS.get(selected_tone, {}).get('name', selected_tone)
        print(f"   • Выбрана: \033[92m{tone_name}\033[0m")
        print(f"   • Промпт: {TONE_PRESETS.get(selected_tone, {}).get('prompt', '')}")
        print(f"   • Доступные: {len(platform_settings['tones'])} тональностей")
    else:
        print("   • Тональность не выбрана (любая)")
    
    # Добавляем камеру если выбрана
    selected_camera = None
    if platform_settings['cameras']:
        selected_camera = random.choice(platform_settings['cameras'])
        camera_prompt = CAMERA_PRESETS.get(selected_camera, {}).get('prompt', '')
        if camera_prompt:
            prompt += f". {camera_prompt}"
    
    print(f"\n\033[93m5. КАМЕРА:\033[0m")
    if selected_camera:
        camera_name = CAMERA_PRESETS.get(selected_camera, {}).get('name', selected_camera)
        print(f"   • Выбрана: \033[92m{camera_name}\033[0m")
        print(f"   • Промпт: {CAMERA_PRESETS.get(selected_camera, {}).get('prompt', '')}")
        print(f"   • Доступные: {len(platform_settings['cameras'])} камер")
    else:
        print("   • Камера не выбрана (любая)")
    
    # Добавляем ракурс если выбран
    selected_angle = None
    if platform_settings['angles']:
        selected_angle = random.choice(platform_settings['angles'])
        angle_prompt = ANGLE_PRESETS.get(selected_angle, {}).get('prompt', '')
        if angle_prompt:
            prompt += f". {angle_prompt}"
    
    print(f"\n\033[93m6. РАКУРС:\033[0m")
    if selected_angle:
        angle_name = ANGLE_PRESETS.get(selected_angle, {}).get('name', selected_angle)
        print(f"   • Выбран: \033[92m{angle_name}\033[0m")
        print(f"   • Промпт: {ANGLE_PRESETS.get(selected_angle, {}).get('prompt', '')}")
        print(f"   • Доступные: {len(platform_settings['angles'])} ракурсов")
    else:
        print("   • Ракурс не выбран (любой)")
    
    # Добавляем качество - ВСЕ выбранные параметры применяются одновременно
    if platform_settings.get('quality'):
        quality_prompts = []
        for quality_code in platform_settings['quality']:
            quality_prompt = QUALITY_PRESETS.get(quality_code, {}).get('prompt', '')
            if quality_prompt:
                quality_prompts.append(quality_prompt)
        
        if quality_prompts:
            # Объединяем все промпты качества
            prompt += f". {', '.join(quality_prompts)}"
    
    print(f"\n\033[93m7. КАЧЕСТВО:\033[0m")
    if platform_settings.get('quality'):
        quality_names = [QUALITY_PRESETS.get(q, {}).get('name', q) for q in platform_settings['quality']]
        print(f"   • Выбраны ВСЕ ({len(platform_settings['quality'])}): \033[92m{', '.join(quality_names)}\033[0m")
        print(f"   • ⚠️ Все параметры применяются одновременно!")
    else:
        print("   • Качество не выбрано (стандартное)")
    
    # ═══════════════════════════════════════════════════════════════
    # ТЕКСТ НА ИЗОБРАЖЕНИИ
    # ═══════════════════════════════════════════════════════════════
    text_percent_str = platform_settings.get('text_percent', '0')
    
    # Обработка специального значения 'random'
    if text_percent_str == 'random':
        text_percent = random.randint(0, 100)
        text_percent_display = 'random'
    else:
        try:
            text_percent = int(text_percent_str)
            text_percent_display = f"{text_percent}"
        except (ValueError, TypeError):
            text_percent = 0
            text_percent_display = "0"
    
    text_added = False
    if text_percent > 0:
        # Генерируем случайное число от 1 до 100
        chance = random.randint(1, 100)
        # Если число <= text_percent, добавляем текст
        if chance <= text_percent:
            prompt += ". Russian text overlay, elegant typography, magazine style, 8-12 words"
            text_added = True
    else:
        # Явный запрет текста при 0%
        prompt += ". No text, no letters, no words, no typography, clean image without any text overlays"
    
    print(f"\n\033[93m8. ТЕКСТ НА ИЗОБРАЖЕНИИ:\033[0m")
    print(f"   • Вероятность: \033[92m{text_percent_display}%\033[0m")
    if text_percent_str == 'random':
        print(f"   • Фактическое значение: {text_percent}%")
    print(f"   • Результат: {'✅ Текст добавлен' if text_added else '❌ Текст ЗАПРЕЩЕН'}")
    
    # ═══════════════════════════════════════════════════════════════
    # КОЛЛАЖ ИЛИ ЦЕЛЬНОЕ ИЗОБРАЖЕНИЕ
    # ═══════════════════════════════════════════════════════════════
    collage_percent = int(platform_settings.get('collage_percent', '0'))
    is_collage = False
    if collage_percent > 0:
        # Генерируем случайное число от 1 до 100
        chance = random.randint(1, 100)
        # Если число <= collage_percent, делаем коллаж
        if chance <= collage_percent:
            prompt += ". Create a stylish collage with multiple elements arranged artistically on the image"
            is_collage = True
        else:
            prompt += ". Create a cohesive single composition with one main subject"
    else:
        # 0% = всегда цельное
        prompt += ". Create a cohesive single composition with one main subject"
    
    print(f"\n\033[93m9. ТИП КОМПОЗИЦИИ:\033[0m")
    print(f"   • Вероятность коллажа: \033[92m{collage_percent}%\033[0m")
    print(f"   • Результат: {'🎨 Коллаж' if is_collage else '🖼 Цельное изображение'}")
    
    print(f"\n\033[93m10. ИТОГОВЫЙ ПРОМПТ:\033[0m")
    print(f"   {prompt}")
    
    print("\n" + "="*80)
    print("\033[95mОТПРАВКА ЗАПРОСА В NANO BANANA PRO API...\033[0m")
    print("="*80 + "\n")
    
    return prompt, image_format


print("✅ platform_settings/utils.py загружен")