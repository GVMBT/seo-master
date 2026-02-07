# -*- coding: utf-8 -*-
"""
Прямая публикация в VK (без показа в чате)
Аналогично Pinterest - генерация и публикация в один клик
"""
import logging

logger = logging.getLogger(__name__)

from loader import bot, db

from telebot import types

from utils import escape_html

import requests

import tempfile

import os

import random

import json



def publish_vk_directly(call, user_id, bot_id, platform_id, category_id, cost):
    """
    Прямая публикация в VK с генерацией изображения
    
    Args:
        call: callback query
        user_id: ID пользователя Telegram
        bot_id: ID бота (категории)
        platform_id: VK user_id (строка или словарь с 'id')
        category_id: ID категории
        cost: Стоимость (50 токенов)
    """
    # Если platform_id - это словарь, извлекаем 'id'
    if isinstance(platform_id, dict):
        vk_user_id = platform_id.get('id') or platform_id.get('user_id') or platform_id.get('group_id')
        print(f"🔧 platform_id был словарь, извлекли id: {vk_user_id}")
    else:
        vk_user_id = platform_id
    
    # Инициализируем прогресс-бар
    from utils.generation_progress import show_generation_progress
    progress = show_generation_progress(call.message.chat.id, "vk", total_steps=10)
    
    # ШАГ 1/10
    progress.start("🔧 Инициализация системы...")
    
    try:
        # КРИТИЧНО: ПРОВЕРКА ТОКЕНА ДО ГЕНЕРАЦИИ И СПИСАНИЯ
        progress.update(1, "🔐 Проверка прав на публикацию...", "Валидация доступа")
        
        # Получаем VK подключение
        user = db.get_user(user_id)
        platform_conns = user.get('platform_connections', {})
        if isinstance(platform_conns, str):
            platform_conns = json.loads(platform_conns)
        
        vks = platform_conns.get('vks', [])
        vk_connection = None
        for vk in vks:
            if str(vk.get('id')) == str(vk_user_id):
                vk_connection = vk
                break
        
        if not vk_connection:
            progress.finish()
            bot.send_message(call.message.chat.id, f"❌ VK подключение {vk_user_id} не найдено")
            return
        
        access_token = vk_connection.get('access_token')
        vk_type = vk_connection.get('type', 'user')
        
        if not access_token:
            progress.finish()
            bot.send_message(call.message.chat.id, "❌ Токен доступа VK не найден")
            return
        
        owner_id = int(vk_user_id)
        
        # КРИТИЧНО: Для токена группы проверяем права через groups.getTokenPermissions
        if vk_type == 'group':
            check_response = requests.get(
                "https://api.vk.com/method/groups.getTokenPermissions",
                params={
                    "access_token": access_token,
                    "v": "5.199"
                },
                timeout=10
            )
            
            check_result = check_response.json()
            
            if 'error' in check_result:
                progress.finish()
                error_msg = check_result['error'].get('error_msg', 'Unknown error')
                error_code = check_result['error'].get('error_code', 0)
                
                bot.send_message(
                    call.message.chat.id,
                    f"❌ Ошибка проверки прав токена: {error_msg}\n\n"
                    "Токен группы недействителен или не имеет нужных прав."
                )
                return
            
            # Проверяем права
            if 'response' in check_result:
                permissions = check_result['response']
                mask = permissions.get('mask', 0)
                
                # Права на публикацию: wall (8192) + photos (4)
                WALL_PERMISSION = 8192
                PHOTOS_PERMISSION = 4
                
                has_wall = (mask & WALL_PERMISSION) > 0
                has_photos = (mask & PHOTOS_PERMISSION) > 0
                
                print(f"🔍 Права токена: mask={mask}, wall={has_wall}, photos={has_photos}")
                
                if not has_wall:
                    progress.finish()
                    bot.send_message(
                        call.message.chat.id,
                        "❌ У токена нет прав на публикацию на стене!\n\n"
                        "Как исправить:\n"
                        "1. Зайдите в VK → Управление группой\n"
                        "2. Дополнительно → Работа с API\n"
                        "3. УДАЛИТЕ старый ключ\n"
                        "4. Создайте НОВЫЙ ключ\n"
                        "5. При создании ОБЯЗАТЕЛЬНО поставьте галочку:\n"
                        "   ✅ Разрешить приложению доступ к стене сообщества\n"
                        "6. Подключите новый токен в боте"
                    )
                    return
        else:
            # Для личного токена
            check_response = requests.get(
                "https://api.vk.com/method/users.get",
                params={"access_token": access_token, "v": "5.199"},
                timeout=10
            )
            
            check_result = check_response.json()
            
            if 'error' in check_result:
                progress.finish()
                error_code = check_result['error'].get('error_code', 0)
                error_msg = check_result['error'].get('error_msg', 'Unknown error')
                
                print(f"❌ Ошибка проверки личного токена: {error_code} - {error_msg}")
                
                # Разные сообщения в зависимости от ошибки
                if error_code == 5:  # User authorization failed
                    message = (
                        "❌ Токен VK недействителен или истёк!\n\n"
                        "Как исправить:\n"
                        "1. Переподключите VK в разделе 'Мои подключения'\n"
                        "2. Разрешите ВСЕ права при подключении"
                    )
                elif error_code == 15:  # Access denied
                    message = (
                        "❌ Доступ запрещён!\n\n"
                        "Токену не хватает прав для публикации.\n"
                        "Переподключите VK с полными правами."
                    )
                else:
                    message = f"❌ Ошибка VK API: {error_msg}\n\nКод ошибки: {error_code}"
                
                bot.send_message(call.message.chat.id, message)
                return
        
        print(f"✅ VK токен валиден и имеет права на публикацию")
        
        # ШАГ 2/10: Загрузка категории
        progress.update(2, "📂 Загружаю категорию...", f"Получение настроек")
        
        category = db.get_category(category_id)
        if not category:
            progress.finish()
            db.update_tokens(user_id, cost)  # Возвращаем токены
            bot.send_message(call.message.chat.id, "❌ Ошибка: категория не найдена")
            return
        
        category_name = category.get('name', 'Без названия')
        description = category.get('description', '')
        keywords = category.get('keywords', [])
        
        # ШАГ 3/10: Загрузка настроек платформы
        progress.update(3, "⚙️ Настройка генератора...", f"Конфигурация VK")
        
        from handlers.platform_settings.utils import get_platform_settings, build_image_prompt
        platform_image_settings = get_platform_settings(category, 'vk')
        
        print(f"📋 Загружены настройки VK:")
        print(f"   Форматы: {platform_image_settings.get('formats', [])}")
        print(f"   Стили: {platform_image_settings.get('styles', [])}")
        print(f"   Тональности: {platform_image_settings.get('tones', [])}")
        print(f"   Камеры: {platform_image_settings.get('cameras', [])}")
        print(f"   Ракурсы: {platform_image_settings.get('angles', [])}")
        print(f"   Качество: {platform_image_settings.get('quality', [])}")
        print(f"   Коллаж: {platform_image_settings.get('collage_percent', 0)}%")
        
        # ШАГ 4/10: Выбор контента
        progress.update(4, "🎯 Выбираю контент...", f"📝 {category_name}")
        
        from ai.unified_generator import generate_for_platform
        
        # Выбираем фразу из описания
        selected_phrase = ''
        if description:
            phrases = [s.strip() for s in description.split(',') if s.strip()]
            if phrases:
                selected_phrase = random.choice(phrases)
                print(f"📝 Выбрана фраза: {selected_phrase[:80]}...")
        
        # ШАГ 5/10: Генерация текста
        progress.update(5, "✍️ Генерирую текст...", f"Claude создаёт описание")
        
        # ШАГ 6/10: Генерация изображения
        progress.update(6, "🎨 Генерирую изображение...", f"Nano Banana Pro создаёт картинку")
        
        # Генерируем контент через unified_generator
        result = generate_for_platform(
            platform='vk',
            category_name=category_name,
            selected_phrase=selected_phrase,
            style='conversational'  # Стиль текста для VK
        )
        
        if not result['success']:
            progress.finish()
            db.update_tokens(user_id, cost)
            bot.send_message(call.message.chat.id, f"❌ Ошибка генерации: {result.get('error')}")
            return
        
        # Получаем сгенерированные данные
        text = result['text']
        image_bytes = result['image_bytes']
        
        print(f"✅ Контент сгенерирован: текст {len(text)} символов, изображение {len(image_bytes)} байт")
        
        # ШАГ 7/10: Сохранение изображения
        progress.update(7, "🖼️ Сохраняю изображение...", f"Подготовка к загрузке")
        
        # Сохраняем изображение во временный файл
        fd, image_path = tempfile.mkstemp(suffix='.jpg', prefix='vk_post_')
        with os.fdopen(fd, 'wb') as f:
            f.write(image_bytes)
        
        # ШАГ 8/10: Форматирование текста
        progress.update(8, "💾 Форматирую текст...", f"✅ {len(text.split())} слов")
        
        post_text = text
        
        print(f"📝 Текст поста: {post_text[:200]}...")
        
        # Проверяем наличие хэштегов, если нет - добавляем из keywords
        if '#' not in post_text and keywords:
            # Берем 3-5 случайных ключевых слов и добавляем как хэштеги
            selected_keywords = random.sample(keywords, min(5, len(keywords)))
            hashtags = ' '.join([f"#{kw.replace(' ', '').replace('-', '')}" for kw in selected_keywords])
            post_text = f"{post_text}\n\n{hashtags}"
            print(f"📝 Добавлены хэштеги: {hashtags}")
        
        # ШАГ 9/10: Авторизация VK  
        progress.update(9, "🔐 Подключаюсь к VK...", "Авторизация VK API")
        
        # Получаем валидный токен (автоматически обновит если истёк)
        from handlers.vk_integration.vk_oauth import VKOAuth
        
        access_token = VKOAuth.ensure_valid_token(db, user_id, vk_user_id)
        
        if not access_token:
            progress.finish()
            db.update_tokens(user_id, cost)
            try:
                os.unlink(image_path)
            except Exception:
                pass
            bot.send_message(
                call.message.chat.id,
                "❌ VK не подключен или токен истёк\n\n"
                "Переподключите VK через 'МОИ ПОДКЛЮЧЕНИЯ'\n\n"
                "Токены возвращены."
            )
            return
        
        # Получаем VK подключение (личная страница или группа)
        user = db.get_user(user_id)
        connections = user.get('platform_connections', {})
        vks = connections.get('vks', [])
        
        vk_connection = None
        
        print(f"🔎 Ищем VK подключение с platform_id={platform_id}")
        
        # Ищем подключение по platform_id
        # platform_id может быть:
        # - user_id для личной страницы (положительный)
        # - group_id для группы (отрицательный)
        # - id подключения (может совпадать с group_id)
        
        for i, vk in enumerate(vks):
            vk_id = str(vk.get('id', ''))
            vk_user_id = str(vk.get('user_id', ''))
            vk_group_id = vk.get('group_id')
            vk_type = vk.get('type', 'user')
            
            print(f"   Проверяем VK[{i}]: id={vk_id}, user_id={vk_user_id}, group_id={vk_group_id}, type={vk_type}")
            
            # Сначала проверяем по id (основной идентификатор)
            if vk_id == str(platform_id):
                print(f"   ✅ Найдено совпадение по id!")
                vk_connection = vk
                break
            
            # Затем проверяем по group_id (если есть)
            if vk_group_id and str(vk_group_id) == str(platform_id):
                print(f"   ✅ Найдено совпадение по group_id!")
                vk_connection = vk
                break
            
            # Наконец проверяем по user_id (для личных страниц)
            if vk_user_id == str(platform_id):
                print(f"   ✅ Найдено совпадение по user_id!")
                vk_connection = vk
                break
        
        if not vk_connection:
            progress.finish()
            db.update_tokens(user_id, cost)
            try:
                os.unlink(image_path)
            except Exception:
                pass
            bot.send_message(call.message.chat.id, "❌ VK не подключен\n\nТокены возвращены.")
            return
        
        # ШАГ 10/10: Публикация в VK
        progress.update(10, "📤 Публикую в VK...", "Загрузка изображения и поста")
        
        # Тип токена
        vk_type = vk_connection.get("type", "user")
        photo_attachment = None
        
        # Загружаем изображение в VK
        # ВАЖНО: Для публикации в группу используем group_id параметр
        try:
            upload_params = {
                "access_token": access_token,
                "v": "5.199"
            }
            
            # Если публикуем в группу, добавляем group_id
            if owner_id < 0:  # Отрицательный ID = группа
                upload_params["group_id"] = abs(owner_id)
            
            upload_server_response = requests.get(
                "https://api.vk.com/method/photos.getWallUploadServer",
                params=upload_params,
                timeout=10
            )
            
            upload_server_data = upload_server_response.json()
            
            if 'error' in upload_server_data:
                error_msg = upload_server_data['error'].get('error_msg', 'VK API error')
                error_code = upload_server_data['error'].get('error_code', 0)
                
                if error_code == 203:  # Access denied
                    raise Exception("Нет прав на загрузку фото. Используйте личный токен администратора группы.")
                else:
                    raise Exception(f"{error_msg} (код {error_code})")
            
            upload_url = upload_server_data['response']['upload_url']
            
            # Шаг 2: Загружаем фото
            with open(image_path, 'rb') as photo_file:
                upload_response = requests.post(
                    upload_url,
                    files={'photo': photo_file},
                    timeout=30
                )
            
            upload_result = upload_response.json()
            
            # Шаг 3: Сохраняем фото на стене
            save_params = {
                "access_token": access_token,
                "v": "5.199",
                "photo": upload_result['photo'],
                "server": upload_result['server'],
                "hash": upload_result['hash']
            }
            
            # Для группы добавляем group_id
            if owner_id < 0:
                save_params["group_id"] = abs(owner_id)
            
            save_response = requests.get(
                "https://api.vk.com/method/photos.saveWallPhoto",
                params=save_params,
                timeout=10
            )
            
            save_result = save_response.json()
            
            if 'error' in save_result:
                raise Exception(save_result['error'].get('error_msg', 'VK save error'))
            
            photo_data = save_result['response'][0]
            photo_attachment = f"photo{photo_data['owner_id']}_{photo_data['id']}"
            print(f"✅ Фото загружено: {photo_attachment}")
        
        except Exception as photo_error:
            print(f"⚠️ Ошибка загрузки фото: {photo_error}")
            photo_attachment = None
            
            # Показываем подсказку если это проблема прав
            if "203" in str(photo_error) or "Access denied" in str(photo_error):
                bot.send_message(
                    call.message.chat.id,
                    "⚠️ Не удалось загрузить фото в группу.\n\n"
                    "💡 Решение:\n"
                    "1. Используйте личный токен администратора группы\n"
                    "2. Подключите VK через OAuth (Мои подключения → VK → Подключить)\n"
                    "3. Выберите 'От имени пользователя' при подключении\n\n"
                    "Публикую только текст..."
                )
        
        # Продолжаем публикацию (вне блока try-except!)
        # ВАЖНО: Определяем куда публиковать (на личную страницу или в группу)
        # Если есть group_id - публикуем в группу, иначе - на личную страницу
        target_group_id = vk_connection.get('group_id')
        
        # Приводим к int для правильного сравнения
        if target_group_id:
            try:
                target_group_id = int(target_group_id)
            except (ValueError, TypeError):
                target_group_id = None
        
        if target_group_id and target_group_id < 0:
            # Публикуем в группу
            owner_id = target_group_id  # Отрицательный ID группы
            from_group = 1  # От имени группы
            print(f"📝 Публикуем в группу: owner_id={owner_id}")
        else:
            # Публикуем на личную страницу
            user_id_raw = vk_connection.get('user_id') or vk_user_id
            try:
                owner_id = int(user_id_raw)
            except (ValueError, TypeError):
                owner_id = int(vk_user_id)
            from_group = 0  # От имени пользователя
            print(f"👤 Публикуем на личную страницу: owner_id={owner_id}")
        
        # Шаг 4: Публикуем пост
        logger.debug(f" post_text длина={len(post_text)}")
        logger.debug(f" post_text[:200]={post_text[:200] if post_text else 'ПУСТО!'}")
        
        post_params = {
            "access_token": access_token,
            "v": "5.199",
            "owner_id": owner_id,  # ВСЕГДА указываем owner_id
            "from_group": from_group,  # 1 = от имени группы, 0 = от имени пользователя
            "message": post_text
        }
        
        # Добавляем фото если загрузилось
        if photo_attachment:
            post_params["attachments"] = photo_attachment
        
        post_response = requests.post(
            "https://api.vk.com/method/wall.post",
            data=post_params,
            timeout=10
        )
        
        post_result_vk = post_response.json()
        
        if 'error' in post_result_vk:
            raise Exception(post_result_vk['error'].get('error_msg', 'VK post error'))
        
        post_id = post_result_vk['response']['post_id']
        post_url = f"https://vk.com/wall{owner_id}_{post_id}"
        
        # Успех!
        progress.finish()
        
        # Получаем обновленный баланс
        from datetime import datetime
        user = db.get_user(user_id)
        new_balance = user.get('balance', 0)
        
        # Удаляем временный файл
        try:
            os.unlink(image_path)
        except Exception:
            pass
        
        # Определяем тип VK страницы для platform_detail
        if owner_id < 0:
            # Группа - показываем название
            platform_detail = vk_connection.get('group_name', 'VK Группа')
        else:
            # Личная страница
            platform_detail = "Личная страница"
        
        # Используем универсальное сообщение успеха
        from utils.success_message import send_unified_success_message
        
        send_unified_success_message(
            bot=bot,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            platform_type='vk',
            category_name=category_name,
            cost=cost,
            new_balance=new_balance,
            word_count=len(text.split()) if text else 0,
            post_url=post_url,
            platform_detail=platform_detail,
            category_id=category_id,
            bot_id=bot_id,
            platform_id=vk_user_id
        )
        
    except Exception as e:
        progress.finish()
        db.update_tokens(user_id, cost)
        
        try:
            os.unlink(image_path)
        except Exception:
            pass
        
        print(f"❌ Ошибка публикации в VK: {e}")
        bot.send_message(
            call.message.chat.id,
            f"❌ Ошибка публикации в VK: {e}\n\nТокены возвращены."
        )
    
    except Exception as e:
        progress.finish()
        db.update_tokens(user_id, cost)
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
        bot.send_message(
            call.message.chat.id,
            f"❌ Критическая ошибка: {e}\n\nТокены возвращены."
        )


print("✅ handlers/platform_category/vk_direct_publish.py загружен")
