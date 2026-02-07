# -*- coding: utf-8 -*-
"""
Обработчик генерации статей для платформы Website
С настройками: количество слов, изображений, стиль, формат
"""
import logging

logger = logging.getLogger(__name__)

from telebot import types

from loader import bot, db

from utils import escape_html, safe_answer_callback

import random



# Храним параметры статьи для каждой категории (временный кеш)
article_params_storage = {}


def get_image_settings(user_id, category_id):
    """Получить настройки изображений из БД или кеша"""
    key = f"{user_id}_{category_id}"
    
    # Проверяем кеш
    if key in article_params_storage:
        return article_params_storage[key]
    
    # Загружаем из БД (СТАРЫЙ ФОРМАТ - category.settings)
    category = db.get_category(category_id)
    if category:
        import json
        
        category_settings = category.get('settings', {})
        if isinstance(category_settings, str):
            try:
                category_settings = json.loads(category_settings)
            except Exception:
                category_settings = {}
        
        logger.debug(f"DEBUG get_image_settings для user={user_id}, category={category_id}:")
        print(f"   website_word_count: {category_settings.get('website_word_count', 'НЕТ')}")
        print(f"   website_images_count: {category_settings.get('website_images_count', 'НЕТ')}")
        print(f"   website_image_formats: {category_settings.get('website_image_formats', 'НЕТ')}")
        print(f"   website_image_styles: {category_settings.get('website_image_styles', 'НЕТ')}")
        
        # Проверяем есть ли ЛЮБЫЕ настройки в старом формате
        # (достаточно одного поля чтобы считать что настройки есть)
        has_settings = (
            category_settings.get('website_word_count') or
            category_settings.get('website_images_count') or
            category_settings.get('website_image_formats') or
            'website_image_styles' in category_settings  # Проверяем наличие ключа, не значение
        )
        
        print(f"   has_settings: {has_settings}")
        
        if isinstance(category_settings, dict) and has_settings:
            # Преобразуем из старого формата в новый
            images_count = category_settings.get('website_images_count', 3)
            image_settings = {
                'words': category_settings.get('website_word_count', 1500),
                'images': images_count,  # Берем из БД
                'images_count': images_count,  # Дублируем для обратной совместимости
                'style': 'professional',
                'format': 'structured',
                'preview_formats': category_settings.get('website_image_formats', ['16:9']),
                'article_images_formats': category_settings.get('website_formats', ['16:9']),
                'advanced': {
                    'styles': category_settings.get('website_image_styles', []),
                    'cameras': category_settings.get('website_cameras', []),
                    'angles': category_settings.get('website_angles', []),
                    'quality': category_settings.get('website_quality', []),
                    'tones': category_settings.get('website_tones', []),
                    'text_on_image': category_settings.get('website_text_on_image', 0),
                    'collage_mode': category_settings.get('website_collage_percent', 0),
                    'images_count': images_count  # Синхронизируем
                }
            }
            print(f"   🔴 ВОЗВРАЩАЕМ: words={image_settings['words']}, images={image_settings['images']}")
            article_params_storage[key] = image_settings
            return image_settings
    
    # Дефолтные значения
    print(f"   ⚠️ Настройки НЕ найдены в БД, используем дефолтные значения")
    default_settings = {
        'words': 1500,
        'images': 3,
        'images_count': 3,  # Дублируем для обратной совместимости
        'style': 'professional',
        'format': 'structured',
        'preview_formats': ['16:9'],
        'article_images_formats': [],
        'advanced': {
            'styles': [],
            'cameras': [],
            'angles': [],
            'quality': [],
            'tones': [],
            'text_on_image': 0,
            'collage_mode': 0,
            'images_count': 3
        }
    }
    print(f"   🔴 ВОЗВРАЩАЕМ ДЕФОЛТ: words={default_settings['words']}, images={default_settings['images']}")
    article_params_storage[key] = default_settings
    return default_settings


def save_image_settings(user_id, category_id, settings):
    """Сохранить настройки изображений в БД и кеш"""
    key = f"{user_id}_{category_id}"
    article_params_storage[key] = settings
    
    # КРИТИЧНО: Сохраняем в БД в СТАРЫЙ формат (category.settings)
    category = db.get_category(category_id)
    if category:
        import json
        
        # Получаем текущие settings
        category_settings = category.get('settings', {})
        if isinstance(category_settings, str):
            try:
                category_settings = json.loads(category_settings)
            except Exception:
                category_settings = {}
        
        if not isinstance(category_settings, dict):
            category_settings = {}
        
        # Извлекаем данные из settings (новый формат) и сохраняем в старый
        adv_params = settings.get('advanced', {})
        
        # Синхронизируем images и images_count (могут быть в разных местах)
        images_count = adv_params.get('images_count') or settings.get('images', 3)
        
        # Обновляем настройки в старом формате
        category_settings['website_word_count'] = settings.get('words', 1500)  # КОЛИЧЕСТВО СЛОВ
        category_settings['website_image_formats'] = settings.get('preview_formats', ['16:9'])
        category_settings['website_formats'] = settings.get('article_images_formats', ['16:9'])
        category_settings['website_image_styles'] = adv_params.get('styles', [])
        category_settings['website_cameras'] = adv_params.get('cameras', [])
        category_settings['website_angles'] = adv_params.get('angles', [])
        category_settings['website_quality'] = adv_params.get('quality', [])
        category_settings['website_tones'] = adv_params.get('tones', [])
        category_settings['website_text_on_image'] = adv_params.get('text_on_image', 0)
        category_settings['website_collage_percent'] = adv_params.get('collage_mode', 0)
        category_settings['website_images_count'] = images_count  # КОЛИЧЕСТВО ИЗОБРАЖЕНИЙ
        
        logger.debug(f"DEBUG save_image_settings для user={user_id}, category={category_id}:")
        print(f"   Сохраняем website_word_count: {category_settings['website_word_count']}")
        print(f"   Сохраняем website_images_count: {category_settings['website_images_count']}")
        print(f"   Сохраняем website_image_formats: {category_settings['website_image_formats']}")
        print(f"   Сохраняем website_image_styles: {category_settings['website_image_styles']}")
        
        # Сохраняем в БД
        try:
            settings_json = json.dumps(category_settings, ensure_ascii=False)
            
            db.cursor.execute("""
                UPDATE categories
                SET settings = %s::jsonb
                WHERE id = %s
            """, (settings_json, category_id))
            
            db.conn.commit()
            print(f"✅ Настройки изображений сохранены в БД для категории {category_id}")
                
        except Exception as e:
            print(f"❌ Ошибка сохранения настроек в БД: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"❌ Категория {category_id} не найдена!")


@bot.callback_query_handler(func=lambda call: call.data.startswith("platform_ai_post_website_"))
def handle_platform_ai_post_website(call):
    """Сразу генерировать статью без промежуточного меню"""
    parts = call.data.split("_")
    category_id = int(parts[4])
    bot_id = int(parts[5])
    platform_id = "_".join(parts[6:])
    
    user_id = call.from_user.id
    
    # Получаем категорию
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена")
        return
    
    category_name = category.get('name', 'Без названия')
    
    # КРИТИЧНО: Загружаем параметры из БД!
    key = f"{user_id}_{category_id}"
    params = get_image_settings(user_id, category_id)
    
    # ЗАЩИТА: Гарантируем наличие ключей (на случай если get_image_settings вернёт None)
    if not params or not isinstance(params, dict):
        params = {
            'words': 1500,
            'images': 3,
            'images_count': 3
        }
    
    # Гарантируем наличие критичных ключей
    params.setdefault('words', 1500)
    params.setdefault('images', 3)
    params.setdefault('images_count', 3)
    
    print(f"\n{'='*80}")
    print(f"📊 ПАРАМЕТРЫ ДЛЯ РАСЧЕТА СТОИМОСТИ")
    print(f"{'='*80}")
    print(f"   user_id: {user_id}")
    print(f"   category_id: {category_id}")
    print(f"   🔴 words (слова): {params.get('words', 'НЕТ')}")
    print(f"   🔴 images (изображения): {params.get('images', 'НЕТ')}")
    print(f"   🔴 images_count (дубль): {params.get('images_count', 'НЕТ')}")
    print(f"   🔍 Полный params: {params}")
    print(f"{'='*80}\n")
    
    # Рассчитываем ПРИБЛИЗИТЕЛЬНУЮ стоимость
    # Текст: ~250 токенов (среднее потребление Claude API для статьи)
    # Изображение: 30 токенов за штуку
    estimated_text_cost = 250  # Приблизительная стоимость текста
    images = params.get('images', 0)
    
    image_cost = (images + 1) * 30  # +1 за обложку
    estimated_total_cost = estimated_text_cost + image_cost
    
    # Проверяем баланс (нужен хотя бы estimated_cost)
    tokens = db.get_user_tokens(user_id) or 0
    
    if tokens < estimated_total_cost:
        text = (
            f"📝 <b>ГЕНЕРАЦИЯ СТАТЬИ</b>\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            "━━━━━━━━━━━━━━\n\n"
            f"<b>Настройки:</b>\n"
            f"• Объём: БЕЗ ОГРАНИЧЕНИЙ (ИИ решает сам)\n"
            f"• Изображений: {params.get('images', 3)} + обложка\n\n"
            f"💰 <b>Приблизительная стоимость:</b> ~{estimated_total_cost} токенов\n"
            f"💳 Баланс: {tokens:,} токенов\n\n"
            f"❌ Недостаточно токенов!\n"
            f"⚠️ Точная цена будет рассчитана после генерации"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_website_{platform_id}"
            )
        )
        try:
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        bot.answer_callback_query(call.id, "❌ Недостаточно токенов")
        return
    
    # Достаточно токенов - сразу запускаем генерацию
    bot.answer_callback_query(call.id, "⏳ Начинаю генерацию...")
    
    # Перенаправляем на обработчик генерации
    call.data = f"wa_generate_{category_id}_{bot_id}_{platform_id}"
    handle_website_article_generate(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("wa_generate_"))
def handle_website_article_generate(call):
    """Генерация статьи с выбранными параметрами"""
    parts = call.data.split("_")
    category_id = int(parts[2])
    bot_id = int(parts[3])
    platform_id = parts[4]
    
    user_id = call.from_user.id
    
    # КРИТИЧНО: Загружаем параметры из БД!
    key = f"{user_id}_{category_id}"
    params = get_image_settings(user_id, category_id)
    
    # ЗАЩИТА: Гарантируем наличие ключей
    if not params or not isinstance(params, dict):
        params = {
            'words': 1500,
            'images': 3,
            'images_count': 3
        }
    
    params.setdefault('words', 1500)
    params.setdefault('images', 3)
    params.setdefault('images_count', 3)
    
    print(f"\n📊 ПАРАМЕТРЫ ДЛЯ ГЕНЕРАЦИИ:")
    print(f"   user_id: {user_id}")
    print(f"   category_id: {category_id}")
    print(f"   words: {params.get('words', 'НЕТ')}")
    print(f"   images: {params.get('images', 'НЕТ')}")
    
    # ============================================================
    # ПРОВЕРКА WORDPRESS CREDENTIALS ДО СПИСАНИЯ ТОКЕНОВ
    # ============================================================
    
    print(f"\n{'='*80}")
    print(f"[ЛОВУШКА 0] НАЧАЛО - проверяем connections из users")
    print(f"{'='*80}\n")
    
    # Получаем пользователя
    user = db.get_user(user_id)
    if not user:
        bot.answer_callback_query(call.id, "❌ Пользователь не найден", show_alert=True)
        return
    
    # Получаем connections из users
    connections = user.get('platform_connections', {})
    if isinstance(connections, str):
        try:
            import json
            connections = json.loads(connections)
        except Exception:
            connections = {}
    
    print(f"[ЛОВУШКА 0] connections type = {type(connections)}")
    print(f"[ЛОВУШКА 0] connections keys = {list(connections.keys()) if isinstance(connections, dict) else 'NOT A DICT'}")
    print(f"[ЛОВУШКА 0] connections = {connections}")
    
    # Получаем websites из connections
    websites = connections.get('websites', [])
    print(f"[ЛОВУШКА 0] websites = {websites}")
    print(f"[ЛОВУШКА 0] platform_id искомый = '{platform_id}'")
    
    # Ищем нужный сайт по platform_id (URL)
    website_data = None
    for site in websites:
        site_url = site.get('url', '')
        print(f"[ЛОВУШКА 0] Проверяем site: url='{site_url}'")
        if site_url == platform_id:
            website_data = site
            print(f"[ЛОВУШКА 0] ✅ НАЙДЕН! site_data = {site}")
            break
    
    if not website_data:
        error_msg = (
            "❌ <b>Website не найден в connections!</b>\n\n"
            f"platform_id = {platform_id}\n"
            f"Доступные сайты: {[s.get('url') for s in websites]}\n\n"
            "Переподключите Website в настройках."
        )
        bot.answer_callback_query(call.id, "❌ Website не найден", show_alert=True)
        bot.send_message(call.message.chat.id, error_msg, parse_mode='HTML')
        return
    
    # Извлекаем WordPress credentials из connections
    wp_url = website_data.get('url', '').strip()
    wp_login = website_data.get('username', '').strip()  # В connections это 'username', не 'login'!
    wp_password = website_data.get('password', '').strip()
    
    # Получаем внешние и внутренние ссылки
    external_links_text = website_data.get('external_links', '').strip()
    internal_links_data = website_data.get('internal_links', [])
    
    # Парсим внешние ссылки (через запятую)
    external_links = []
    if external_links_text:
        raw_links = [link.strip() for link in external_links_text.split(',') if link.strip()]
        # Преобразуем в список словарей для совместимости с generate_website_article
        for link in raw_links:
            external_links.append({
                'url': link,
                'title': link  # Используем URL как title
            })
    
    # Парсим внутренние ссылки (список словарей с url, title, priority)
    internal_links = []
    if internal_links_data and isinstance(internal_links_data, list):
        internal_links = internal_links_data
    
    print(f"🔗 Внешние ссылки: {len(external_links)}")
    if external_links:
        for i, link in enumerate(external_links[:3], 1):
            print(f"   {i}. {link.get('url', 'нет')}")
    
    print(f"🔗 Внутренние ссылки: {len(internal_links)}")
    if internal_links:
        for i, link in enumerate(internal_links[:3], 1):
            print(f"   {i}. {link.get('title', 'Без названия')[:50]} - {link.get('priority', 'no priority')}")
    else:
        print("   ⚠️ Внутренние ссылки не найдены! Запустите сбор ссылок в настройках Website.")
    
    print(f"\n{'='*80}")
    print(f"[ЛОВУШКА 0] ФИНАЛЬНАЯ ПРОВЕРКА WordPress credentials из connections")
    print(f"[ЛОВУШКА 0] wp_url = '{wp_url}' (len={len(wp_url)})")
    print(f"[ЛОВУШКА 0] wp_login = '{wp_login}' (len={len(wp_login)})")
    print(f"[ЛОВУШКА 0] wp_password = {'ЕСТЬ' if wp_password else 'ПУСТО'} (len={len(wp_password) if wp_password else 0})")
    print(f"{'='*80}\n")
    
    # Проверяем наличие всех данных
    if not wp_url or not wp_login or not wp_password:
        error_msg = (
            "❌ <b>WordPress не настроен!</b>\n\n"
            "Для генерации статьи необходимо настроить подключение к WordPress:\n"
        )
        
        if not wp_url:
            error_msg += "• ❌ URL сайта не указан\n"
        else:
            error_msg += f"• ✅ URL: {wp_url}\n"
            
        if not wp_login:
            error_msg += "• ❌ Логин не указан\n"
        else:
            error_msg += f"• ✅ Логин: {wp_login}\n"
            
        if not wp_password:
            error_msg += "• ❌ Пароль приложения не указан\n"
        else:
            error_msg += "• ✅ Пароль: установлен\n"
        
        error_msg += "\n📝 Настройте WordPress в настройках бота (Подключения → Website)"
        
        print(f"\n{'='*80}")
        print(f"[ЛОВУШКА 0] ❌ WordPress НЕ НАСТРОЕН - прерываем генерацию")
        print(f"{'='*80}\n")
        
        bot.answer_callback_query(call.id, "❌ WordPress не настроен", show_alert=True)
        bot.send_message(call.message.chat.id, error_msg, parse_mode='HTML')
        return
    
    print(f"\n{'='*80}")
    print(f"[ЛОВУШКА 0] ✅ WordPress НАСТРОЕН - продолжаем генерацию")
    print(f"{'='*80}\n")
    
    # ============================================================
    # КРИТИЧНО: ПРОВЕРЯЕМ РЕАЛЬНОЕ ПОДКЛЮЧЕНИЕ К WORDPRESS
    # ============================================================
    print(f"\n{'='*80}")
    print(f"🔌 ПРОВЕРКА ПОДКЛЮЧЕНИЯ К WORDPRESS")
    print(f"{'='*80}\n")
    
    from handlers.website.wordpress_api import test_wp_connection
    
    connection_result = test_wp_connection(wp_url, wp_login, wp_password)
    
    if not connection_result.get('success'):
        error = connection_result.get('message', 'Неизвестная ошибка')
        error_msg = (
            "❌ <b>Не удалось подключиться к WordPress!</b>\n\n"
            f"<b>Ошибка:</b> {error}\n\n"
            "<b>Проверьте:</b>\n"
            "• Логин и пароль WordPress\n"
            "• Доступность сайта\n"
            "• Права доступа к API\n\n"
            "📝 Настройте подключение в: Подключения → Website"
        )
        
        print(f"❌ ОШИБКА ПОДКЛЮЧЕНИЯ: {error}")
        print(f"{'='*80}\n")
        
        bot.answer_callback_query(call.id, "❌ Ошибка подключения к WordPress", show_alert=True)
        bot.send_message(call.message.chat.id, error_msg, parse_mode='HTML')
        return
    
    print(f"✅ Подключение к WordPress успешно!")
    print(f"   URL: {wp_url}")
    print(f"   Пользователь: {wp_login}")
    print(f"{'='*80}\n")
    
    # Получаем категорию для дополнительной информации
    category = db.get_category(category_id)
    if not category:
        bot.answer_callback_query(call.id, "❌ Категория не найдена", show_alert=True)
        return
    
    # Рассчитываем ПРИБЛИЗИТЕЛЬНУЮ стоимость
    # Текст: ~250 токенов (среднее потребление Claude API)
    # Изображение: 30 токенов за штуку
    estimated_text_cost = 250
    image_cost = (params.get('images', 3) + 1) * 30  # +1 за обложку
    estimated_total_cost = estimated_text_cost + image_cost
    
    # Проверяем баланс
    tokens = db.get_user_tokens(user_id) or 0
    if tokens < estimated_total_cost:
        bot.answer_callback_query(
            call.id,
            f"❌ Недостаточно токенов!\nПриблизительно нужно: ~{estimated_total_cost}, у вас: {tokens}",
            show_alert=True
        )
        return
    
    # НЕ списываем токены сразу! Спишем ПОСЛЕ генерации на основе реального usage
    
    bot.answer_callback_query(call.id, f"🤖 Генерирую статью... (~{estimated_total_cost} токенов)")
    
    # Отправляем GIF с начальным текстом
    gif_url = "https://ecosteni.ru/wp-content/uploads/2026/01/202601191550.gif"
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    
    # Инициализируем прогресс-трекер
    from utils.progress_bars import generate_gradient_progress_bar
    
    # Начальный прогресс-бар (0%)
    progress_bar = generate_gradient_progress_bar(0, total_blocks=12, title="ГЕНЕРАЦИЯ СТАТЬИ")
    
    generation_msg = bot.send_animation(
        call.message.chat.id,
        gif_url,
        caption=(
            f"{progress_bar}\n"
            f"Инициализация параметров...\n\n"
            f"📝 Объём: БЕЗ ОГРАНИЧЕНИЙ (ИИ решает сам)\n"
            f"🖼 Изображений: {params.get('images', 3)} + обложка\n"
            f"🎨 Стиль: {params['style']}\n"
            f"💰 Приблизительно: ~{estimated_total_cost} токенов"
        ),
        parse_mode='HTML'
    )
    
    # Функция обновления прогресса
    extra_info = {}  # Дополнительная информация для отображения
    
    def update_progress(step, total_steps, message):
        progress = int((step / total_steps) * 100)
        progress_bar = generate_gradient_progress_bar(progress, total_blocks=12, title="ГЕНЕРАЦИЯ СТАТЬИ")
        
        caption_parts = [
            progress_bar,
            message,
            "",
            f"📝 Объём: БЕЗ ОГРАНИЧЕНИЙ (ИИ решает)",
            f"🖼 Изображений: {params.get('images', 3)} + обложка",
            f"🎨 Стиль: {params['style']}",
            f"💰 Приблизительно: ~{estimated_total_cost} токенов"
        ]
        
        # Добавляем дополнительную информацию если есть
        if extra_info.get('title'):
            caption_parts.append(f"📌 Заголовок: {extra_info['title'][:50]}...")
        
        if extra_info.get('selected_keyword'):
            # Показываем выбранный ключ и количество всех ключей
            keyword_display = extra_info['selected_keyword'][:60]  # Обрезаем если слишком длинный
            total = extra_info.get('total_keywords', 1)
            
            if len(extra_info['selected_keyword']) > 60:
                keyword_display += '...'
            
            if total > 1:
                caption_parts.append(f"🔑 Ключ: {keyword_display} (1 из {total})")
            else:
                caption_parts.append(f"🔑 Ключ: {keyword_display}")
        
        try:
            bot.edit_message_caption(
                caption="\n".join(caption_parts),
                chat_id=call.message.chat.id,
                message_id=generation_msg.message_id,
                parse_mode='HTML'
            )
        except Exception:
            pass
    
    # ═══════════════════════════════════════════════════════════════
    # ЭТАП 1: СБОР ВСЕЙ ИНФОРМАЦИИ ДЛЯ ГЕНЕРАЦИИ
    # ═══════════════════════════════════════════════════════════════
    
    print("\n" + "="*80)
    print("📊 \033[96mЭТАП 1: СБОР ИНФОРМАЦИИ ДЛЯ ГЕНЕРАЦИИ\033[0m")
    print("="*80)
    
    # Шаг 1: Инициализация (8%)
    update_progress(1, 12, "Сбор информации о категории...")
    
    # Категория уже получена выше при проверке WordPress
    category_name = category.get('name', 'Без названия')
    description = category.get('description', '')
    prices_data = category.get('prices', [])
    
    print(f"\n\033[93m1.1 КАТЕГОРИЯ:\033[0m")
    print(f"   • Название: \033[92m{category_name}\033[0m")
    print(f"   • ID категории: {category_id}")
    print(f"   • Ключи в категории: {list(category.keys())}")
    if description:
        if len(description) > 150:
            print(f"   • Описание: {description[:150]}...")
            print(f"     (полная длина: {len(description)} символов)")
        else:
            print(f"   • Описание: {description}")
    else:
        print(f"   • Описание: \033[91mотсутствует\033[0m")
    
    # Обработка нового формата цен (с headers и rows)
    if isinstance(prices_data, dict):
        prices = prices_data.get('rows', [])
        price_headers = prices_data.get('headers', [])
    elif isinstance(prices_data, list):
        prices = prices_data
        price_headers = []
    else:
        prices = []
        price_headers = []
    
    # Получаем ключевые слова
    keywords = category.get('keywords', [])
    if isinstance(keywords, str):
        import json
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = []
    
    print(f"\n\033[93m1.2 КЛЮЧЕВЫЕ СЛОВА:\033[0m")
    print(f"   • Всего ключевых слов: \033[92m{len(keywords) if keywords else 0}\033[0m")
    if keywords and len(keywords) > 0:
        for i, kw in enumerate(keywords[:5], 1):
            print(f"   {i}. {kw}")
        if len(keywords) > 5:
            print(f"   ... и еще {len(keywords) - 5} ключевых слов")
    
    # Выбираем рандомное ключевое слово как тему статьи
    if keywords and len(keywords) > 0:
        article_keyword = random.choice(keywords)
        print(f"\n   ✅ Выбрано для статьи: \033[92m{article_keyword}\033[0m")
        extra_info['selected_keyword'] = article_keyword
        extra_info['total_keywords'] = len(keywords)
    else:
        article_keyword = category_name
        print(f"\n   ℹ️ Ключевые слова не найдены, используется название категории")
        extra_info['selected_keyword'] = category_name
        extra_info['total_keywords'] = 1
    
    # Выбираем 1-2 случайные фразы из описания
    selected_phrases = []
    if description:
        desc_phrases = [s.strip() for s in description.split(',') if s.strip()]
        if len(desc_phrases) <= 1:
            desc_phrases = [s.strip() for s in description.split('.') if s.strip() and len(s.strip()) > 5]
        
        if desc_phrases:
            num_phrases = random.randint(1, min(2, len(desc_phrases)))
            selected_phrases = random.sample(desc_phrases, num_phrases)
    
    print(f"\n\033[93m1.3 ВЫБРАННЫЕ ФРАЗЫ ИЗ ОПИСАНИЯ:\033[0m")
    if selected_phrases:
        for i, phrase in enumerate(selected_phrases, 1):
            print(f"   {i}. {phrase}")
    else:
        print(f"   • \033[91mФразы не выбраны\033[0m")
    
    # Рандомный выбор цен из прайса (не все позиции, а 3-7 случайных)
    if prices and len(prices) > 0:
        num_prices = min(random.randint(3, 7), len(prices))
        selected_prices = random.sample(prices, num_prices)
    else:
        selected_prices = []
    
    print(f"\n\033[93m1.4 ПРАЙС-ЛИСТ:\033[0m")
    print(f"   • Всего позиций в базе: {len(prices) if prices else 0}")
    print(f"   • Выбрано для статьи: \033[92m{len(selected_prices)}\033[0m")
    
    # DEBUG: показываем структуру первого элемента
    if prices and len(prices) > 0:
        logger.debug("DEBUG первого элемента прайса:")
        print(f"   • Тип: {type(prices[0])}")
        if isinstance(prices[0], dict):
            print(f"   • Ключи: {list(prices[0].keys())}")
            print(f"   • Полные данные: {prices[0]}")
        else:
            print(f"   • Значение: {prices[0]}")
        print()
    
    if selected_prices:
        for i, price in enumerate(selected_prices[:3], 1):
            if isinstance(price, dict):
                # Проверяем русские и английские варианты ключей
                name = (price.get('name') or price.get('title') or price.get('service') or 
                       price.get('item') or price.get('product') or price.get('наименование'))
                price_value = (price.get('price') or price.get('cost') or price.get('value') or 
                              price.get('amount') or price.get('цена'))
                
                if not name:
                    name = '\033[91mБЕЗ НАЗВАНИЯ\033[0m'
                if not price_value:
                    price_value = '\033[91mЦЕНА НЕ УКАЗАНА\033[0m'
                
                print(f"   {i}. {name}: {price_value}")
            else:
                print(f"   {i}. \033[91mНекорректный формат: {type(price)}\033[0m")
        if len(selected_prices) > 3:
            print(f"   ... и еще {len(selected_prices) - 3}")
    
    # Получаем данные бота (компании)
    bot_data = db.get_bot(bot_id)
    company_data = bot_data.get('company_data', {}) if bot_data else {}
    
    print(f"\n\033[93m1.5 ДАННЫЕ КОМПАНИИ:\033[0m")
    
    # DEBUG
    logger.debug("")
    print(f"   • bot_data exists: {bool(bot_data)}")
    if bot_data:
        print(f"   • bot_data keys: {list(bot_data.keys())}")
        print(f"   • company_data type: {type(company_data)}")
        print(f"   • company_data exists: {bool(company_data)}")
        if company_data:
            print(f"   • company_data keys: {list(company_data.keys())}")
            print(f"   • company_data полностью: {company_data}")
    print()
    
    if company_data:
        name = company_data.get('name') or company_data.get('company_name') or company_data.get('title')
        city = company_data.get('city', '')
        address = company_data.get('address', '')
        phone = company_data.get('phone', '')
        email = company_data.get('email', '')
        
        print(f"   • Название: {name if name else '\033[91mНЕ ЗАПОЛНЕНО\033[0m'}")
        print(f"   • Город: {city if city else 'не указан'}")
        print(f"   • Адрес: {address if address else 'не указан'}")
        print(f"   • Телефон: {phone if phone else 'не указан'}")
        print(f"   • Email: {email if email else 'не указан'}")
    else:
        print(f"   • \033[91mДанные компании отсутствуют\033[0m")
    
    # Получаем отзывы
    reviews_data = category.get('reviews', [])
    reviews = reviews_data[:3] if reviews_data else None
    
    # ОТЗЫВЫ ОБЯЗАТЕЛЬНЫ для качественной статьи!
    if not reviews or len(reviews) < 3:
        remaining = 3 - (len(reviews) if reviews else 0)
        
        text = (
            f"⚠️ <b>НУЖНЫ ОТЗЫВЫ ДЛЯ СТАТЬИ</b>\n\n"
            f"📂 Категория: {escape_html(category_name)}\n"
            f"━━━━━━━━━━━━━━\n\n"
            f"<b>Почему отзывы важны:</b>\n"
            f"• Увеличивают доверие к статье\n"
            f"• Улучшают SEO (Schema.org разметка)\n"
            f"• Добавляют социальное доказательство\n"
            f"• Показывают реальный опыт клиентов\n\n"
            f"📊 Сейчас отзывов: <b>{len(reviews) if reviews else 0}</b>\n"
            f"✅ Нужно минимум: <b>3 отзыва</b>\n"
            f"📉 Не хватает: <b>{remaining}</b>\n\n"
            f"💡 <b>Добавьте отзывы:</b>\n"
            f"🤖 Генерация AI — {remaining}шт × 10 токенов = {remaining * 10} токенов\n"
            f"✏️ Вручную — бесплатно"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton(
                f"🤖 СГЕНЕРИРОВАТЬ ({remaining}шт за {remaining * 10} токенов)",
                callback_data=f"gen_reviews_{category_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "✏️ Добавить вручную",
                callback_data=f"category_reviews_{category_id}"
            )
        )
        markup.add(
            types.InlineKeyboardButton(
                "🔙 Назад",
                callback_data=f"platform_menu_{category_id}_{bot_id}_website_{platform_id}"
            )
        )
        
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='HTML'
            )
        except Exception:
            bot.send_message(call.message.chat.id, text, reply_markup=markup, parse_mode='HTML')
        
        safe_answer_callback(bot, call.id)
        return
    
    print(f"\n\033[93m1.6 ОТЗЫВЫ:\033[0m")
    print(f"   • Всего отзывов в базе: {len(reviews_data) if reviews_data else 0}")
    print(f"   • Будет использовано в статье: \033[92m{len(reviews) if reviews else 0}\033[0m")
    if reviews:
        for i, review in enumerate(reviews[:2], 1):
            author = review.get('author', 'Аноним')
            rating = review.get('rating', '?')
            text = review.get('text', '')[:60]
            print(f"   {i}. {author} ({rating}/5): {text}...")
    
    # Внешние и внутренние ссылки (уже получены выше)
    print(f"\n\033[93m1.7 ВНЕШНИЕ ССЫЛКИ:\033[0m")
    print(f"   • Количество: \033[92m{len(external_links)}\033[0m")
    if external_links:
        for i, link in enumerate(external_links[:3], 1):
            url = link.get('url', 'нет') if isinstance(link, dict) else str(link)
            print(f"   {i}. {url}")
    
    print(f"\n\033[93m1.8 ВНУТРЕННИЕ ССЫЛКИ:\033[0m")
    print(f"   • Количество: \033[92m{len(internal_links)}\033[0m")
    if internal_links:
        for i, link in enumerate(internal_links[:3], 1):
            title = link.get('title', 'Без названия')
            priority = link.get('priority', 'no')
            priority_color = '\033[91m' if priority == 'high' else '\033[93m' if priority == 'medium' else '\033[92m'
            print(f"   {i}. [{priority_color}{priority}\033[0m] {title[:50]}")
    
    # Получаем настройки текста и изображений
    try:
        import json
        from handlers.platform_settings import build_image_prompt, get_platform_settings
        from handlers.website.image_advanced_settings import get_user_advanced_params
        
        # Получаем настройки изображений через унифицированную функцию
        platform_image_settings = get_platform_settings(category, 'website')
        
        print(f"\n🔍 Настройки изображений Website:")
        print(f"   Форматы превью: {platform_image_settings.get('formats', [])}")
        logger.debug(f"DEBUG - type(formats): {type(platform_image_settings.get('formats'))}")
        logger.debug(f"DEBUG - len(formats): {len(platform_image_settings.get('formats', []))}")
        logger.debug(f"DEBUG - formats is empty: {not platform_image_settings.get('formats')}")
        print(f"   Стили: {platform_image_settings.get('styles', [])}")
        print(f"   Камеры: {platform_image_settings.get('cameras', [])}")
        print(f"   Ракурсы: {platform_image_settings.get('angles', [])}")
        print(f"   Качество: {platform_image_settings.get('quality', [])}")
        print(f"   Тональность: {platform_image_settings.get('tones', [])}")
        print(f"   Текст: {platform_image_settings.get('text_percent', 0)}%")
        print(f"   Коллаж: {platform_image_settings.get('collage_percent', 0)}%")
        
        # Получаем настройки текста
        category_settings = category.get('settings', {})
        if isinstance(category_settings, str):
            category_settings = json.loads(category_settings)
        
        logger.debug(f"DEBUG: Проверка настроек текста")
        print(f"   category.settings exists: {bool(category_settings)}")
        print(f"   category.settings type: {type(category_settings)}")
        print(f"   category.settings keys: {list(category_settings.keys()) if isinstance(category_settings, dict) else 'not dict'}")
        
        text_styles = category_settings.get('website_text_styles', [])
        word_count = category_settings.get('website_word_count', 1500)
        html_style = category_settings.get('website_html_style', 'creative')
        
        print(f"   website_text_styles: {text_styles}")
        print(f"   website_word_count: {word_count}")
        print(f"   website_html_style: {html_style}")
        
        # Если в params нет настроек - используем из category
        if 'words' not in params or params.get('words', 1500) == 1500:
            params['words'] = word_count
        
        # Если не указан стиль - берем первый из выбранных или дефолтный
        if 'style' not in params or params.get('style') == 'professional':
            if text_styles and len(text_styles) > 0:
                params['style'] = random.choice(text_styles)
            else:
                params['style'] = 'professional'
        
        print(f"\n\033[93m1.9 НАСТРОЙКИ ТЕКСТА:\033[0m")
        print(f"   • Количество слов: \033[92m{params.get('words', 1500)}\033[0m")
        print(f"   • Стиль текста: \033[92m{params['style']}\033[0m")
        print(f"   • HTML стиль: \033[92m{html_style}\033[0m")
        print(f"   • Доступные стили: {', '.join(text_styles) if text_styles else 'не выбраны'}")
        
        print(f"\n\033[93m1.10 НАСТРОЙКИ ИЗОБРАЖЕНИЙ:\033[0m")
        formats = platform_image_settings.get('formats', ['16:9'])
        print(f"   • Форматы: {', '.join(formats)}")
        print(f"   • Стили: {', '.join(platform_image_settings.get('styles', [])) if platform_image_settings.get('styles') else 'не выбраны'}")
        print(f"   • Камеры: {', '.join(platform_image_settings.get('cameras', [])) if platform_image_settings.get('cameras') else 'не выбраны'}")
        print(f"   • Ракурсы: {', '.join(platform_image_settings.get('angles', [])) if platform_image_settings.get('angles') else 'не выбраны'}")
        print(f"   • Качество: {', '.join(platform_image_settings.get('quality', [])) if platform_image_settings.get('quality') else 'не выбрано'}")
        print(f"   • Тональность: {', '.join(platform_image_settings.get('tones', [])) if platform_image_settings.get('tones') else 'не выбрана'}")
        print(f"   • Текст на фото: \033[92m{platform_image_settings.get('text_percent', 0)}%\033[0m")
        print(f"   • Коллаж: \033[92m{platform_image_settings.get('collage_percent', 0)}%\033[0m")
        
        print("\n" + "="*80)
        print("✅ \033[92mСБОР ИНФОРМАЦИИ ЗАВЕРШЕН\033[0m")
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"⚠️ Ошибка получения настроек: {e}")
        import traceback
        traceback.print_exc()
        # Используем дефолтные значения через get_platform_settings
        platform_image_settings = {
            'formats': ['16:9'],
            'styles': [],
            'cameras': [],
            'angles': [],
            'quality': [],
            'tones': [],
            'text_percent': 0,
            'collage_percent': 0
        }
    
    # ═══════════════════════════════════════════════════════════════
    # ЭТАП 2: ГЕНЕРАЦИЯ ТЕКСТА СТАТЬИ
    # ═══════════════════════════════════════════════════════════════
    
    print("\n" + "="*80)
    print("📝 \033[96mЭТАП 2: ГЕНЕРАЦИЯ ТЕКСТА СТАТЬИ\033[0m")
    print("="*80 + "\n")
    
    # Шаг 2: Генерация статьи (17-67%)
    update_progress(2, 12, "Генерация текста статьи...")
    
    try:
        from ai.website_article_generator import generate_website_article
        
        print(f"\n📝 Генерация текста статьи...")
        print(f"   Ключевое слово: {article_keyword}")
        print(f"   Стиль текста: {params['style']}")
        print(f"   HTML стиль: {html_style}")
        print(f"   Целевой объём: {params.get('words', 1500)} слов (±50)")
        print(f"   Диапазон слов: {params.get('words', 1500) - 50} - {params.get('words', 1500) + 50}")
        print(f"   Цены: {len(selected_prices)} позиций")
        print(f"   Отзывы: {len(reviews)} шт")
        print(f"   Внутренние ссылки: {len(internal_links)} шт")
        print(f"   Внешние ссылки: {len(external_links)} шт")
        
        # Генерируем статью
        article_result = generate_website_article(
            keyword=article_keyword,
            category_name=category_name,
            category_description=description,
            company_data=company_data,
            prices=selected_prices,
            reviews=reviews,
            external_links=external_links,
            internal_links=internal_links,
            text_style=params['style'],
            html_style=html_style,
            site_colors=None,
            min_words=None,  # 🆕 Без ограничений - ИИ решает сам
            max_words=None,  # 🆕 Без ограничений - ИИ решает сам
            h2_list=None,
            author_data=None,  # Для preview не нужен автор
            images_count=platform_image_settings.get('images_count'),
            image_formats=platform_image_settings.get('formats', ['16:9']),
            image_styles=platform_image_settings.get('styles', []),
            image_cameras=platform_image_settings.get('cameras', []),
            image_angles=platform_image_settings.get('angles', []),
            image_quality=platform_image_settings.get('quality', []),
            image_tones=platform_image_settings.get('tones', []),
            image_text_percent=platform_image_settings.get('text_percent', 0),
            image_collage_percent=platform_image_settings.get('collage_percent', 0)
        )
        
        if not article_result.get('success'):
            raise Exception(article_result.get('error', 'Ошибка генерации статьи'))
        
        article_html = article_result['html']
        seo_title_raw = article_result.get('seo_title', category_name)
        meta_desc_raw = article_result.get('meta_description', description[:150])
        real_word_count = article_result.get('word_count', 0)
        
        extra_info['title'] = seo_title_raw
        
        print(f"✅ Текст статьи сгенерирован успешно")
        print(f"   • SEO заголовок: {seo_title_raw}")
        print(f"   • Мета-описание: {meta_desc_raw[:80]}...")
        print(f"   • Длина HTML: {len(article_html)} символов")
        print(f"   • Реальное количество слов: {real_word_count}")
        print(f"   • Запрошено слов: {params.get('words', 1500)}")
        
        # Проверяем соответствие объёму
        requested_words = params.get('words')
        if requested_words and real_word_count < requested_words - 50:
            print(f"⚠️ ВНИМАНИЕ! Статья короче запрошенной:")
            print(f"   Запрошено: {requested_words} слов")
            print(f"   Получено: {real_word_count} слов")
            print(f"   Недостача: {requested_words - real_word_count} слов")
        
    except Exception as e:
        print(f"❌ Ошибка генерации статьи: {e}")
        
        try:
            bot.delete_message(call.message.chat.id, generation_msg.message_id)
        except Exception:
            pass
        
        # Возвращаем предварительную стоимость (0, так как ничего не сгенерировано)
        total_cost = 0
        db.update_tokens(user_id, total_cost)
        bot.send_message(call.message.chat.id, f"❌ Ошибка генерации текста: {e}\n\nПопробуйте снова.")
        return
    
    # ═══════════════════════════════════════════════════════════════
    # ЭТАП 3: ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ
    # ═══════════════════════════════════════════════════════════════
    
    print("\n" + "="*80)
    print("🎨 \033[96mЭТАП 3: ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ\033[0m")
    print("="*80 + "\n")
    
    # Генерируем изображения
    try:
        import tempfile
        import os
        
        # ВАЖНО: platform_image_settings уже получены в ЭТАПЕ 1
        # Не дублируем код, используем существующие настройки
        
        print(f"\n🎨 Настройки изображений (из ЭТАПА 1):")
        formats = platform_image_settings.get('formats', ['16:9'])
        print(f"   Форматы: {', '.join(formats)}")
        print(f"   Стили: {platform_image_settings.get('styles', [])}")
        print(f"   Камеры: {platform_image_settings.get('cameras', [])}")
        print(f"   Ракурсы: {platform_image_settings.get('angles', [])}")
        print(f"   Качество: {platform_image_settings.get('quality', [])}")
        print(f"   Тональность: {platform_image_settings.get('tones', [])}")
        print(f"   Текст на фото: {platform_image_settings.get('text_percent', 0)}%")
        print(f"   Коллаж: {platform_image_settings.get('collage_percent', 0)}%")
        
        # Если не указан стиль - берем первый из выбранных или дефолтный
        if 'style' not in params or params['style'] == 'professional':
            if text_styles and len(text_styles) > 0:
                params['style'] = random.choice(text_styles)
            else:
                params['style'] = 'professional'
        
        # Шаг 2: Анализ контекста (17%)
        update_progress(2, 12, "Анализ ключевых слов и контекста...")
        
        # Выбираем 1-2 случайные фразы
        selected_phrases = []
        if description:
            desc_phrases = [s.strip() for s in description.split(',') if s.strip()]
            if len(desc_phrases) <= 1:
                desc_phrases = [s.strip() for s in description.split('.') if s.strip() and len(s.strip()) > 5]
            
            if desc_phrases:
                num_phrases = random.randint(1, min(2, len(desc_phrases)))
                selected_phrases = random.sample(desc_phrases, num_phrases)
        
        # Шаг 3: Генерация обложки (25%)
        update_progress(3, 12, "Генерация обложки...")
        
        # Подготавливаем контекст для изображений
        # ВАЖНО: используем только основное ключевое слово + 1-2 выбранные фразы
        image_context_parts = []
        
        # Добавляем выбранное ключевое слово первым
        image_context_parts.append(article_keyword)
        
        # Добавляем 1-2 ВЫБРАННЫЕ фразы (не всё описание!)
        if selected_phrases:
            image_context_parts.extend(selected_phrases)
        
        # Собираем всё в единый контекст
        full_image_context = ', '.join(image_context_parts)
        
        # Генерируем обложку
        base_prompt = f"{full_image_context}, professional website header image, clean product photography, no UI elements, no website interface, no menus, no logos, no text overlays, pure product shot"
        
        print(f"\n📋 Контекст для изображения обложки:")
        print(f"   • Основное ключевое слово: {article_keyword}")
        print(f"   • Выбранные фразы: {len(selected_phrases)}")
        
        # МИГРАЦИЯ: Используем unified_generator только для ИЗОБРАЖЕНИЯ
        from ai.unified_generator import generate_image_only
        
        # Формируем фразу для генерации - ОБЯЗАТЕЛЬНО включаем ключевое слово статьи!
        # ВАЖНО: article_keyword должен быть ПЕРВЫМ для правильной генерации
        if selected_phrases:
            # Ключевое слово + фразы из описания
            selected_phrase = f"{article_keyword}, {', '.join(selected_phrases[:2])}"
        else:
            # Только ключевое слово
            selected_phrase = article_keyword
        
        print(f"🎨 Генерация обложки (только изображение)")
        print(f"   Category: {category_name}")
        print(f"   Keyword (ОБЯЗАТЕЛЬНО): {article_keyword}")
        print(f"   Full phrase: {selected_phrase[:150]}...")
        
        # Подготавливаем настройки для генерации
        logger.debug(f"DEBUG: Подготовка настроек обложки")
        print(f"   platform_image_settings['formats']: {platform_image_settings.get('formats', 'НЕТ КЛЮЧА')}")
        print(f"   Тип: {type(platform_image_settings.get('formats'))}")
        
        cover_settings = {
            'styles': platform_image_settings.get('styles', []),
            'cameras': platform_image_settings.get('cameras', []),
            'angles': platform_image_settings.get('angles', []),
            'quality': platform_image_settings.get('quality', []),
            'tones': platform_image_settings.get('tones', []),
            'format': platform_image_settings.get('formats', ['16:9'])[0] if platform_image_settings.get('formats') else '16:9',
            'formats': platform_image_settings.get('formats', ['16:9'])
        }
        
        print(f"\n📸 Применяемые настройки изображения:")
        print(f"   🔴 cover_settings['format']: {cover_settings['format']}")
        print(f"   🔴 cover_settings['formats']: {cover_settings['formats']}")
        print(f"   Стили: {cover_settings['styles']} → будет выбран случайный")
        print(f"   Камеры: {cover_settings['cameras']} → будет выбрана случайная")
        print(f"   Ракурсы: {cover_settings['angles']} → будет выбран случайный")
        print(f"   Качество: {cover_settings['quality']} → будет выбрано случайное")
        print(f"   Тональность: {cover_settings['tones']} → будет выбрана случайная")
        print(f"   Формат: {cover_settings['format']}")
        
        # Генерируем ТОЛЬКО изображение обложки (текст УЖЕ есть!)
        result = generate_image_only(
            platform='website',
            category_name=category_name,
            selected_phrase=selected_phrase,
            image_settings=cover_settings
        )
        
        if not result.get('success'):
            raise Exception(result.get('error', 'Ошибка генерации обложки'))
        
        # Сохраняем обложку
        cover_image_bytes = result['image_bytes']
        temp_cover = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
        temp_cover.write(cover_image_bytes)
        temp_cover.close()
        cover_path = temp_cover.name
        
        # Генерируем дополнительные изображения для статьи
        article_images = []
        num_images = params.get('images', 3)  # Количество изображений из параметров
        
        # Шаг 4: Генерация изображений для статьи (33%)
        update_progress(4, 12, f"Генерация {num_images} изображений для статьи...")
        
        print(f"🖼️ Генерирую {num_images} дополнительных изображений для статьи...")
        
        for i in range(num_images):
            try:
                # МИГРАЦИЯ: Варьируем фразу для каждого изображения
                
                # Варьируем контекст в зависимости от номера
                if i == 0:
                    context = "detailed view, professional photography"
                elif i == 1:
                    context = "installation process, professional setting"
                else:
                    context = "finished result, high quality"
                
                # ОБЯЗАТЕЛЬНО добавляем ключевое слово статьи + контекст + случайная фраза
                if selected_phrases:
                    random_phrase = random.choice(selected_phrases)
                    img_phrase = f"{article_keyword}, {context}, {random_phrase}"
                else:
                    img_phrase = f"{article_keyword}, {context}"
                
                print(f"\n📋 Генерация изображения {i+1}/{num_images}")
                print(f"   Category: {category_name}")
                print(f"   Keyword (ОБЯЗАТЕЛЬНО): {article_keyword}")
                print(f"   Full phrase: {img_phrase[:100]}...")
                
                # Подготавливаем настройки для изображения (могут отличаться от обложки)
                article_img_settings = {
                    'styles': platform_image_settings.get('styles', []),
                    'cameras': platform_image_settings.get('cameras', []),
                    'angles': platform_image_settings.get('angles', []),
                    'quality': platform_image_settings.get('quality', []),
                    'tones': platform_image_settings.get('tones', []),
                    'format': platform_image_settings.get('formats', ['16:9'])[0] if platform_image_settings.get('formats') else '16:9',
                    'formats': platform_image_settings.get('formats', ['16:9'])
                }
                
                print(f"\n📸 Применяемые настройки изображения {i+1}:")
                print(f"   Стили: {article_img_settings['styles']}")
                print(f"   Камеры: {article_img_settings['cameras']}")
                print(f"   Ракурсы: {article_img_settings['angles']}")
                print(f"   Качество: {article_img_settings['quality']}")
                print(f"   Тональность: {article_img_settings['tones']}")
                print(f"   Формат: {article_img_settings['format']}")
                
                # МИГРАЦИЯ: Генерируем ТОЛЬКО изображение (текст УЖЕ есть!)
                img_result = generate_image_only(
                    platform='website',
                    category_name=category_name,
                    selected_phrase=img_phrase,
                    image_settings=article_img_settings
                )
                
                if img_result.get('success'):
                    temp_img = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                    temp_img.write(img_result['image_bytes'])
                    temp_img.close()
                    article_images.append(temp_img.name)
                    print(f"✅ Изображение {i+1}/{num_images} сгенерировано")
                else:
                    print(f"⚠️ Ошибка генерации изображения {i+1}: {img_result.get('error')}")
            except Exception as img_err:
                print(f"⚠️ Ошибка при генерации изображения {i+1}: {img_err}")
                # Продолжаем, даже если одно изображение не сгенерировалось
        
        print(f"📊 Итого сгенерировано: обложка + {len(article_images)} изображений для статьи")
        
    except Exception as e:
        print(f"❌ Ошибка генерации изображений: {e}")
        
        # Удаляем GIF
        try:
            bot.delete_message(call.message.chat.id, generation_msg.message_id)
        except Exception:
            pass
        
        db.update_tokens(user_id, total_cost)
        bot.send_message(call.message.chat.id, f"❌ Ошибка создания изображений: {e}\n\nТокены возвращены.")
        return
    
    # Генерируем статью
    try:
        from ai.website_article_generator import generate_website_article
        
        # Шаг 5: Написание введения (42%)
        update_progress(5, 12, "Написание введения...")
        
        # Получаем отзывы из категории (если есть)
        reviews_data = category.get('reviews', [])
        reviews = reviews_data[:3] if reviews_data else None  # Берём первые 3
        
        # Шаг 6: Создание основного контента (50%)
        update_progress(6, 12, "Создание основного контента...")
        
        # Получаем автора из WordPress
        from handlers.website.wordpress_api import get_wordpress_users
        
        wp_users = get_wordpress_users(wp_url, wp_login, wp_password)
        author_data = None
        
        if wp_users:
            # Берем первого пользователя (обычно это владелец сайта)
            first_user = wp_users[0]
            author_data = {
                'id': first_user.get('id'),
                'name': first_user.get('name'),
                'avatar_url': first_user.get('avatar_url'),
                'bio': first_user.get('description', '')
            }
            print(f"✍️ Данные автора получены: {author_data['name']}")
        
        # Генерируем статью с выбранными параметрами
        article_result = generate_website_article(
            keyword=article_keyword,
            category_name=category_name,
            category_description=description,
            company_data=company_data,
            prices=selected_prices,
            reviews=reviews,
            external_links=external_links,
            internal_links=internal_links,
            text_style=params['style'],
            html_style=html_style,
            site_colors=None,  # Опционально: цвета сайта
            min_words=None,  # 🆕 Без ограничений - ИИ решает сам
            max_words=None,  # 🆕 Без ограничений - ИИ решает сам
            h2_list=None,  # AI сам придумает
            author_data=author_data  # Передаем данные автора
        )
        
        # Шаг 7: SEO-оптимизация (58%)
        update_progress(7, 12, "SEO-оптимизация текста...")
        
        # Шаг 8: Создание мета-тегов (67%)
        update_progress(8, 12, "Создание мета-тегов и Schema.org...")
        
        # Шаг 9: Yoast SEO разметка (75%)
        update_progress(9, 12, "Добавление Yoast SEO разметки...")
        
        if not article_result.get('success'):
            raise Exception(article_result.get('error', 'Ошибка генерации статьи'))
        
        article_html = article_result['html']
        seo_title_raw = article_result.get('seo_title', category_name)
        meta_desc_raw = article_result.get('meta_description', description[:150])
        
        # 🆕 РАССЧИТЫВАЕМ РЕАЛЬНУЮ СТОИМОСТЬ на основе usage
        usage = article_result.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        
        # Конвертируем токены Claude → токены бота
        # 100 Claude токенов = 1 токен бота
        actual_text_cost = int((input_tokens + output_tokens) / 100)
        actual_text_cost = max(10, actual_text_cost)  # Минимум 10 токенов
        
        # Полная стоимость с изображениями
        actual_total_cost = actual_text_cost + image_cost
        
        print(f"\n💰 РАСЧЁТ СТОИМОСТИ:")
        print(f"   • Claude input tokens: {input_tokens}")
        print(f"   • Claude output tokens: {output_tokens}")
        print(f"   • Стоимость текста: {actual_text_cost} токенов бота")
        print(f"   • Стоимость изображений: {image_cost} токенов бота")
        print(f"   • ИТОГО: {actual_total_cost} токенов")
        print(f"   • Приблизительная оценка была: {estimated_total_cost} токенов")
        print(f"   • Разница: {actual_total_cost - estimated_total_cost:+d} токенов")
        
        # Списываем реальную стоимость
        if not db.update_tokens(user_id, -actual_total_cost):
            print(f"⚠️ Ошибка списания токенов, но продолжаем публикацию")
        else:
            new_balance = db.get_user_tokens(user_id)
            print(f"✅ Списано {actual_total_cost} токенов. Новый баланс: {new_balance}")
        
        # Добавляем заголовок в extra_info для отображения
        extra_info['title'] = seo_title_raw
        extra_info['tokens_spent'] = actual_total_cost  # Для показа пользователю
        
        # ================================================================
        # ГЕНЕРАЦИЯ SLUG ИЗ SEO-ЗАГОЛОВКА (а не из категории!)
        # ================================================================
        import re
        import unicodedata
        
        def generate_slug(text):
            """Генерирует ЧПУ slug из текста с полной транслитерацией"""
            # Полная транслитерация русских букв
            translit = {
                'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
                'ж': 'zh', 'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm',
                'н': 'n', 'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u',
                'ф': 'f', 'х': 'h', 'ц': 'ts', 'ч': 'ch', 'ш': 'sh', 'щ': 'sch',
                'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu', 'я': 'ya',
                'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo',
                'Ж': 'Zh', 'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M',
                'Н': 'N', 'О': 'O', 'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U',
                'Ф': 'F', 'Х': 'H', 'Ц': 'Ts', 'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Sch',
                'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu', 'Я': 'Ya'
            }
            
            # Убираем спецсимволы и лишние знаки до транслитерации
            text = text.strip()
            # Убираем символы которые не должны быть в URL
            text = re.sub(r'[—–|«»"""\'\`''(){}\\[\\]]', ' ', text)
            # Убираем множественные пробелы
            text = re.sub(r'\s+', ' ', text)
            
            result = ''
            for char in text:
                if char in translit:
                    result += translit[char]
                elif char.isalnum():
                    result += char
                elif char in ' -_':
                    result += '-'
            
            # Приводим к lowercase
            result = result.lower()
            # Убираем множественные дефисы
            result = re.sub(r'-+', '-', result)
            # Убираем дефисы в начале и конце
            result = result.strip('-')
            
            # Обрезаем по последнему слову если превышает лимит
            if len(result) > 80:
                result = result[:80]
                # Обрезаем по последнему дефису чтобы не резать слово
                last_dash = result.rfind('-')
                if last_dash > 40:  # Минимум 40 символов оставляем
                    result = result[:last_dash]
            
            return result
        
        # ВАЖНО: Генерируем slug из КЛЮЧЕВОГО СЛОВА статьи!
        # SEO-заголовок может содержать только цену (например "15-30"), что даёт плохой URL
        # selected_phrase - это фразы из описания, не ключевое слово
        # article_keyword - это ПРАВИЛЬНОЕ ключевое слово для статьи
        
        # Используем article_keyword для создания описательного URL
        slug_base = article_keyword if article_keyword else category_name
        slug = generate_slug(slug_base)
        
        # Обрезаем до разумной длины (40-50 символов)
        if len(slug) > 50:
            slug = slug[:50]
            # Обрезаем по последнему дефису
            last_dash = slug.rfind('-')
            if last_dash > 30:
                slug = slug[:last_dash]
        
        # НЕ добавляем цифровой суффикс - URL должен быть чистым
        # WordPress сам добавит -2, -3 если будут дубли
        
        print(f"🔗 Сгенерирован описательный slug из КЛЮЧЕВОГО СЛОВА: {slug}")
        print(f"   Ключевое слово: '{article_keyword}'")
        print(f"   (НЕ из SEO-заголовка '{seo_title_raw}')")

        
        # Обрезаем по стандарту Yoast SEO
        # SEO заголовок: 50-60 символов (идеал 55-60)
        # ВАЖНО: обрезаем по последнему полному слову, не режем посреди слова
        if len(seo_title_raw) > 60:
            # Обрезаем до 60 символов
            truncated = seo_title_raw[:60]
            
            # Находим последний пробел чтобы не резать слово
            last_space = truncated.rfind(' ')
            
            if last_space > 40:  # Минимум 40 символов должно остаться
                seo_title = truncated[:last_space].rstrip('.,!?;:') + '...'
            else:
                # Если пробел слишком далеко - режем строго по 57 символов + ...
                seo_title = seo_title_raw[:57].rstrip() + '...'
            
            print(f"⚠️ SEO заголовок обрезан: {len(seo_title_raw)} → {len(seo_title)} символов")
            print(f"   Оригинал: {seo_title_raw}")
            print(f"   Обрезан:  {seo_title}")
        else:
            seo_title = seo_title_raw
        
        # Мета-описание: 120-160 символов (идеал 150-160)
        # ВАЖНО: обрезаем по последнему полному слову
        if len(meta_desc_raw) > 160:
            # Обрезаем до 160 символов
            truncated = meta_desc_raw[:160]
            
            # Находим последний пробел
            last_space = truncated.rfind(' ')
            
            if last_space > 140:  # Минимум 140 символов
                meta_desc = truncated[:last_space].rstrip('.,!?;:') + '...'
            else:
                # Если пробел слишком далеко - режем строго по 157 + ...
                meta_desc = meta_desc_raw[:157].rstrip() + '...'
            
            print(f"⚠️ Мета-описание обрезано: {len(meta_desc_raw)} → {len(meta_desc)} символов")
        elif len(meta_desc_raw) < 120:
            # Если слишком короткое - дополняем из описания категории
            meta_desc = meta_desc_raw
            if len(meta_desc) < 120 and description:
                addition = description[:160-len(meta_desc)]
                # Обрезаем дополнение по последнему слову
                if addition and len(meta_desc) + len(addition) > 160:
                    combined = f"{meta_desc} {addition}"[:160]
                    last_space = combined.rfind(' ')
                    if last_space > 140:
                        meta_desc = combined[:last_space].rstrip('.,!?;:')
                    else:
                        meta_desc = combined.rstrip()
                elif addition:
                    meta_desc = f"{meta_desc} {addition}".strip()
            print(f"ℹ️ Мета-описание дополнено: {len(meta_desc_raw)} → {len(meta_desc)} символов")
        else:
            meta_desc = meta_desc_raw
        
        print(f"✅ SEO заголовок: {len(seo_title)} символов - {seo_title}")
        print(f"✅ Мета-описание: {len(meta_desc)} символов - {meta_desc[:50]}...")
        
    except Exception as e:
        print(f"❌ Ошибка генерации статьи: {e}")
        try:
            os.unlink(cover_path)
        except Exception:
            pass
        
        # Удаляем GIF
        try:
            bot.delete_message(call.message.chat.id, generation_msg.message_id)
        except Exception:
            pass
        
        db.update_tokens(user_id, total_cost)
        bot.send_message(call.message.chat.id, f"❌ Ошибка генерации текста: {e}\n\nТокены возвращены.")
        return
    
    # ============================================================
    # ПУБЛИКАЦИЯ НА WORDPRESS (уже проверен выше)
    # ============================================================
    
    # WordPress credentials уже получены и проверены выше
    print(f"\n{'='*60}")
    print(f"[ЛОВУШКА 7] ПУБЛИКАЦИЯ НА WORDPRESS")
    print(f"[ЛОВУШКА 7] wp_url = '{wp_url}'")
    print(f"[ЛОВУШКА 7] wp_login = '{wp_login}'")
    print(f"[ЛОВУШКА 7] wp_password = {'ЕСТЬ' if wp_password else 'ПУСТО'}")
    print(f"{'='*60}\n")
    
    # WordPress уже проверен выше, всегда публикуем
    print(f"\n{'='*60}")
    print(f"✅ WordPress credentials НАЙДЕНЫ")
    print(f"🔗 URL: {wp_url}")
    print(f"👤 Login: {wp_login}")
    print(f"🔑 Password: {'*' * len(wp_password)}")
    print(f"📤 Публикация на WordPress...")
    print(f"{'='*60}\n")
    
    try:
        from handlers.website.wordpress_api import publish_article_to_wordpress
        
        wp_creds = {
            'url': wp_url,
            'username': wp_login,
            'password': wp_password
        }
        
        # Подготавливаем изображения (обложка + изображения для статьи)
        images_paths = []
        if cover_path:
            images_paths.append(cover_path)
        if article_images:
            images_paths.extend(article_images)
        
        print(f"📷 Всего изображений для загрузки: {len(images_paths)} (обложка + {len(article_images)} для статьи)")
        
        # Шаг 10: Формирование внутренних ссылок (83%)
        update_progress(10, 12, "Формирование внутренних ссылок...")
        
        # Шаг 11: Финальное форматирование (92%)
        update_progress(11, 12, "Финальное форматирование HTML...")
        
        # Шаг 12: Публикация (100%)
        update_progress(12, 12, "Сохранение и публикация на сайт...")
        
        # Получаем настройки рубрик и меток из данных сайта
        wp_categories_text = website_data.get('wp_categories', '').strip()
        wp_tags_text = website_data.get('wp_tags', '').strip()
        
        # Получаем или создаем категории WordPress
        from handlers.website.wordpress_api import get_wordpress_categories, create_wordpress_category
        
        wp_categories_list = get_wordpress_categories(wp_url, wp_login, wp_password)
        category_ids = []
        
        # Выбираем ОДНУ наиболее подходящую рубрику
        if wp_categories_text:
            custom_categories = [c.strip() for c in wp_categories_text.split(',') if c.strip()]
            print(f"📂 Доступные рубрики: {custom_categories}")
            
            # Если рубрика одна - используем её
            if len(custom_categories) == 1:
                selected_category = custom_categories[0]
                print(f"✅ Выбрана единственная рубрика: {selected_category}")
            else:
                # Если несколько - выбираем наиболее подходящую по ключевому слову
                selected_category = None
                best_match_score = 0
                
                print(f"🔍 Поиск рубрики для: ключ='{article_keyword}', категория='{category_name}'")
                
                # Нормализуем keyword и category для поиска
                keyword_normalized = article_keyword.lower().strip()
                category_normalized = category_name.lower().strip()
                
                # СПЕЦИАЛЬНАЯ ОБРАБОТКА: WPC панели = Стеновые панели
                if 'wpc' in category_normalized or 'wpc' in keyword_normalized:
                    print(f"🔍 Обнаружено WPC в названии, ищем подходящую рубрику...")
                    
                    # ПРИОРИТЕТ 1: Точное совпадение "WPC"
                    for cat_name in custom_categories:
                        cat_lower = cat_name.lower()
                        if 'wpc' in cat_lower:
                            selected_category = cat_name
                            print(f"✅ Найдена рубрика с WPC: {selected_category}")
                            break
                    
                    # ПРИОРИТЕТ 2: Стеновые панели (если есть WPC в keyword)
                    if not selected_category:
                        for cat_name in custom_categories:
                            cat_lower = cat_name.lower()
                            if 'стеновые панели' in cat_lower or 'стеновых панелей' in cat_lower:
                                selected_category = cat_name
                                print(f"✅ WPC панели → Стеновые панели: {selected_category}")
                                break
                    
                    # ПРИОРИТЕТ 3: Любые стеновые (если есть "стен" в названии)
                    if not selected_category:
                        for cat_name in custom_categories:
                            cat_lower = cat_name.lower()
                            if 'стен' in cat_lower and 'панел' in cat_lower:
                                selected_category = cat_name
                                print(f"✅ WPC панели → {selected_category}")
                                break
                    
                    # ПРИОРИТЕТ 4: Универсальная категория "панели" (если нет ничего подходящего)
                    if not selected_category:
                        for cat_name in custom_categories:
                            cat_lower = cat_name.lower()
                            # Исключаем реечные, 3D и другие специфичные
                            if 'панел' in cat_lower and not any(excl in cat_lower for excl in ['реечн', '3d', 'гибк']):
                                selected_category = cat_name
                                print(f"✅ WPC панели → {selected_category} (общая категория)")
                                break
                
                # ПРИОРИТЕТ 1: Точное совпадение с названием категории бота
                if not selected_category:
                    for cat_name in custom_categories:
                        if cat_name.lower().strip() == category_normalized:
                            selected_category = cat_name
                            print(f"✅ Точное совпадение с категорией бота: {selected_category}")
                            break
                
                # ПРИОРИТЕТ 2: ВСЕ ключевые слова категории есть в рубрике
                if not selected_category:
                    # Получаем ключевые слова категории (длина > 4)
                    category_key_words = set([w for w in category_normalized.split() if len(w) > 4])
                    
                    for cat_name in custom_categories:
                        cat_lower = cat_name.lower().strip()
                        cat_words = set([w for w in cat_lower.split() if len(w) > 4])
                        
                        # ВАЖНО: ВСЕ слова категории должны быть в рубрике
                        if category_key_words and category_key_words.issubset(cat_words):
                            selected_category = cat_name
                            print(f"✅ Все слова категории найдены в рубрике: {selected_category}")
                            print(f"   Слова категории: {category_key_words}")
                            print(f"   Слова рубрики: {cat_words}")
                            break
                
                # ПРИОРИТЕТ 3: Ищем по основным словам (длина > 4 символов)
                if not selected_category:
                    # Берем значимые слова из keyword и category
                    keyword_words = set([w for w in keyword_normalized.split() if len(w) > 4])
                    category_words = set([w for w in category_normalized.split() if len(w) > 4])
                    all_important_words = keyword_words | category_words
                    
                    best_candidate = None
                    
                    for cat_name in custom_categories:
                        cat_lower = cat_name.lower().strip()
                        cat_words = set([w for w in cat_lower.split() if len(w) > 4])
                        
                        # Считаем совпадения по значимым словам
                        common_words = all_important_words & cat_words
                        match_score = len(common_words)
                        
                        # Дополнительные баллы за совпадение по keyword
                        keyword_matches = keyword_words & cat_words
                        match_score += len(keyword_matches) * 2
                        
                        print(f"   '{cat_name}': score={match_score} (совпадения: {common_words})")
                        
                        if match_score > best_match_score:
                            best_match_score = match_score
                            best_candidate = cat_name
                    
                    # ВАЖНО: Только если score >= 1 (минимум 1 совпадающее слово с высоким весом)
                    # Для WPC панелей достаточно найти "панели"
                    if best_candidate and best_match_score >= 1:
                        selected_category = best_candidate
                        print(f"✅ Найдена рубрика по словам (score: {best_match_score}): {selected_category}")
                    else:
                        selected_category = None
                        if best_candidate:
                            print(f"⚠️ Score {best_match_score} недостаточен (нужно >= 1) для рубрики '{best_candidate}'")
                
                # ПРИОРИТЕТ 4: Если ничего не подошло - используем название категории бота
                if not selected_category:
                    selected_category = category_name
                    print(f"ℹ️ Не найдено подходящих рубрик, будет использовано название категории: {selected_category}")
            
            # Ищем или создаем выбранную рубрику
            found = False
            for cat in wp_categories_list:
                if cat['name'].lower() == selected_category.lower():
                    category_ids.append(cat['id'])
                    print(f"✅ Используется рубрика: {cat['name']} (ID: {cat['id']})")
                    found = True
                    break
            
            # Если не нашли - создаем
            if not found:
                print(f"⚠️ Рубрика '{selected_category}' не найдена, создаю...")
                new_cat = create_wordpress_category(wp_url, wp_login, wp_password, selected_category)
                if new_cat and new_cat.get('id'):
                    category_ids.append(new_cat['id'])
                    print(f"✅ Создана рубрика: {selected_category} (ID: {new_cat['id']})")
        else:
            # Используем название категории бота по умолчанию
            print(f"📂 Используем название категории бота: {category_name}")
            found = False
            for cat in wp_categories_list:
                if cat['name'].lower() == category_name.lower():
                    category_ids.append(cat['id'])
                    print(f"✅ Найдена категория WordPress: {cat['name']} (ID: {cat['id']})")
                    found = True
                    break
            
            if not found:
                print(f"⚠️ Категория '{category_name}' не найдена, создаю...")
                new_cat = create_wordpress_category(wp_url, wp_login, wp_password, category_name)
                if new_cat and new_cat.get('id'):
                    category_ids.append(new_cat['id'])
                    print(f"✅ Создана категория: {category_name} (ID: {new_cat['id']})")
        
        # Формируем метки (tags) - НУЖНЫ ID, А НЕ НАЗВАНИЯ!
        tag_names = []
        if wp_tags_text:
            # Используем метки из настроек
            tag_names = [t.strip() for t in wp_tags_text.split(',') if t.strip()]
            print(f"🏷 Используем метки из настроек: {tag_names}")
        else:
            # Используем ключевые слова категории
            keywords = category.get('keywords', [])
            if isinstance(keywords, str):
                import json
                try:
                    keywords = json.loads(keywords)
                except Exception:
                    keywords = []
            
            tag_names = keywords[:5] if keywords else [category_name]
            print(f"🏷 Используем ключевые слова категории: {tag_names}")
        
        # Конвертируем названия меток в ID
        from handlers.website.wordpress_api import get_wordpress_tags, create_wordpress_tag
        
        wp_tags_list = get_wordpress_tags(wp_url, wp_login, wp_password)
        tag_ids = []
        
        for tag_name in tag_names:
            # Ищем существующую метку
            found = False
            for tag in wp_tags_list:
                if tag['name'].lower() == tag_name.lower():
                    tag_ids.append(tag['id'])
                    print(f"✅ Найдена метка: {tag['name']} (ID: {tag['id']})")
                    found = True
                    break
            
            # Если не нашли - создаем
            if not found:
                print(f"⚠️ Метка '{tag_name}' не найдена, создаю...")
                new_tag = create_wordpress_tag(wp_url, wp_login, wp_password, tag_name)
                if new_tag and new_tag.get('id'):
                    tag_ids.append(new_tag['id'])
                    print(f"✅ Создана метка: {tag_name} (ID: {new_tag['id']})")
        
        print(f"🏷 Итоговые ID меток: {tag_ids}")
        
        # Получаем автора из WordPress
        from handlers.website.wordpress_api import get_wordpress_users
        
        wp_users = get_wordpress_users(wp_url, wp_login, wp_password)
        author_id = None
        author_name = None
        author_avatar = None
        author_bio = None
        
        if wp_users:
            # Берем первого пользователя (обычно это владелец сайта)
            first_user = wp_users[0]
            author_id = first_user.get('id')
            author_name = first_user.get('name')
            author_avatar = first_user.get('avatar_url')
            author_bio = first_user.get('description', '')
            print(f"✍️ Автор статьи: {author_name} (ID: {author_id})")
            print(f"   📷 Avatar: {author_avatar}")
            if author_bio:
                print(f"   📝 Bio: {author_bio[:100]}...")
        else:
            print(f"⚠️ Не удалось получить автора из WordPress")
        
        # ПУБЛИКУЕМ!
        result = publish_article_to_wordpress(
            wp_credentials=wp_creds,
            article_html=article_html,
            seo_title=seo_title,
            meta_description=meta_desc,
            images_paths=images_paths,
            status='publish',
            focus_keyword=article_keyword,
            categories=category_ids if category_ids else [],
            tags=tag_ids if tag_ids else [],
            canonical_url=website_data.get('seo_canonical', ''),
            robots_meta=website_data.get('seo_robots', 'index, follow'),
            schema_type=website_data.get('seo_schema_type', 'Article'),
            slug=slug,  # Добавляем slug
            author_id=author_id  # Добавляем автора
        )
        
        # Удаляем временное изображение
        try:
            if cover_path:
                os.unlink(cover_path)
        except Exception:
            pass
        
        # Проверяем результат
        if result.get('success'):
            post_url = result.get('post_url', '')
            
            # УДАЛЯЕМ ИСПОЛЬЗОВАННЫЕ ОТЗЫВЫ ИЗ БАЗЫ
            if reviews and len(reviews) > 0:
                try:
                    # Получаем оставшиеся отзывы (пропускаем первые 3 использованных)
                    remaining_reviews = reviews_data[len(reviews):]
                    
                    # Обновляем категорию
                    import json
                    db.cursor.execute("""
                        UPDATE categories
                        SET reviews = %s::jsonb
                        WHERE id = %s
                    """, (json.dumps(remaining_reviews, ensure_ascii=False), category_id))
                    db.conn.commit()
                    
                    print(f"✅ Удалено использованных отзывов: {len(reviews)}")
                    print(f"   Осталось отзывов в базе: {len(remaining_reviews)}")
                except Exception as e:
                    print(f"⚠️ Ошибка удаления отзывов: {e}")
            
            print(f"\n{'='*60}")
            print(f"✅ ПУБЛИКАЦИЯ УСПЕШНА!")
            print(f"🔗 URL статьи: {post_url}")
            print(f"{'='*60}\n")
            
            # Получаем актуальный баланс
            final_balance = db.get_user_tokens(user_id)
            tokens_spent = extra_info.get('tokens_spent', actual_total_cost)
            
            text = (
                f"✅ <b>СТАТЬЯ ОПУБЛИКОВАНА НА САЙТ!</b>\n\n"
                f"🔗 <b>URL:</b> {post_url}\n\n"
                f"📊 <b>Статистика:</b>\n"
                f"• Символов: {len(article_html):,}\n"
                f"• Слов: {article_result.get('word_count', 0):,}\n"
                f"• Статус: ✅ Опубликовано\n\n"
                f"💰 <b>Списано:</b> {tokens_spent} токенов\n"
                f"   (текст: {actual_text_cost}, изображения: {image_cost})\n"
                f"💳 <b>Баланс:</b> {final_balance:,} токенов\n\n"
                f"🎉 <i>Статья опубликована и доступна на вашем сайте!</i>"
            )
            
            markup = types.InlineKeyboardMarkup()
            markup.row(
                types.InlineKeyboardButton("🌐 Открыть статью", url=post_url)
            )
            # Используем platform_ai_post_website_ который имеет зарегистрированный хэндлер
            markup.row(
                types.InlineKeyboardButton("🔄 Генерировать ещё", callback_data=f"platform_ai_post_website_{category_id}_{bot_id}_{platform_id}"),
                types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_category_website_{category_id}_{bot_id}")
            )
            
            # Удаляем GIF
            try:
                bot.delete_message(call.message.chat.id, generation_msg.message_id)
            except Exception:
                pass
            
            bot.send_message(
                call.message.chat.id,
                text,
                reply_markup=markup,
                parse_mode='HTML'
            )
            
            # Сохраняем статью в storage
            if key not in article_params_storage:
                article_params_storage[key] = {}
            article_params_storage[key]['last_article'] = {
                'html': article_html,
                'seo_title': seo_title,
                'meta_desc': meta_desc,
                'cover_path': None
            }
            
            return
            
        else:
            # Публикация не удалась
            error_msg = result.get('message', 'Неизвестная ошибка')
            print(f"\n{'='*60}")
            print(f"❌ ПУБЛИКАЦИЯ НЕ УДАЛАСЬ")
            print(f"Причина: {error_msg}")
            print(f"{'='*60}\n")
            
            bot.send_message(
                call.message.chat.id,
                f"❌ <b>Не удалось опубликовать статью:</b>\n\n"
                f"<code>{error_msg}</code>\n\n"
                f"Статья сгенерирована, но не опубликована.\n"
                f"Проверьте настройки WordPress.\n\n"
                f"Статья будет показана ниже в чате.",
                parse_mode='HTML'
            )
            # Продолжаем показывать статью в чате
                    
    except Exception as e:
        print(f"❌ ОШИБКА ПУБЛИКАЦИИ: {e}")
        import traceback
        traceback.print_exc()
        
        bot.send_message(
            call.message.chat.id,
            f"❌ <b>Ошибка публикации на WordPress:</b>\n\n"
            f"<code>{str(e)[:500]}</code>\n\n"
            f"Проверьте:\n"
            f"• Логин и пароль WordPress\n"
            f"• Доступность сайта\n"
            f"• Права доступа к API\n\n"
            f"Статья будет показана ниже в чате.",
            parse_mode='HTML'
        )
        # Продолжаем показывать статью в чате
    
    # ============================================================
    # Показываем статью в чате (fallback или если публикация не удалась)
    # ============================================================
    try:
        # Извлекаем H2 заголовки для структуры
        import re
        h2_headers = re.findall(r'<h2[^>]*>(.*?)</h2>', article_html, flags=re.DOTALL | re.IGNORECASE)
        
        # Символы для подписи
        symbols_count = len(article_html)
        words_count = article_result.get('word_count', params.get('words', 1500))
        
        # Если дошли сюда - значит публикация не удалась
        warning_text = "⚠️ <b>Не удалось опубликовать автоматически</b>\n"
        
        text = (
            f"✅ <b>СТАТЬЯ СГЕНЕРИРОВАНА!</b>\n"
            f"🌐 Платформа: сайт\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📊 <b>Статистика:</b>\n"
            f"• Символов: {symbols_count:,}\n"
            f"• Слов: {words_count:,}\n"
            f"• Разделов (H2): {len(h2_headers)}\n\n"
            f"💰 Списано: {total_cost} токенов | Баланс: {new_balance}\n\n"
            f"{warning_text}"
            f"Настройте подключение к WordPress для автоматической публикации."
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("📄 Скачать HTML", callback_data=f"wa_download_html_{category_id}_{user_id}"),
            types.InlineKeyboardButton("📋 Скопировать", callback_data=f"wa_copy_html_{category_id}_{user_id}")
        )
        markup.row(
            types.InlineKeyboardButton("📝 SEO данные", callback_data=f"wa_show_seo_{category_id}_{user_id}")
        )
        markup.row(
            types.InlineKeyboardButton("🔄 Генерировать ещё", callback_data=f"platform_ai_post_website_{category_id}_{bot_id}_{platform_id}"),
            types.InlineKeyboardButton("🔙 Назад", callback_data=f"platform_menu_manage_{category_id}_{bot_id}_website_{platform_id}")
        )
        
        # Удаляем GIF сообщение
        try:
            bot.delete_message(call.message.chat.id, generation_msg.message_id)
        except Exception:
            pass
        
        bot.send_message(
            call.message.chat.id,
            text,
            reply_markup=markup,
            parse_mode='HTML'
        )
        
        # Сохраняем статью
        if key not in article_params_storage:
            article_params_storage[key] = {}
        article_params_storage[key]['last_article'] = {
            'html': article_html,
            'seo_title': seo_title,
            'meta_desc': meta_desc,
            'cover_path': cover_path
        }
        
        # Удаляем обложку
        try:
            os.unlink(cover_path)
        except Exception:
            pass
            
    except Exception as e:
        print(f"❌ Ошибка отправки результата: {e}")
        try:
            os.unlink(cover_path)
        except Exception:
            pass
        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")


print("✅ handlers/website/article_generation.py загружен")