# -*- coding: utf-8 -*-
"""
VK OAuth авторизация - основная логика
"""
import requests
import json
from typing import Optional, Dict, List
from .vk_config import (
    VK_APP_ID, VK_APP_SECRET, VK_REDIRECT_URI, 
    VK_API_VERSION, VK_OAUTH_TOKEN_URL, VK_API_BASE_URL
)


class VKOAuth:
    """Класс для работы с VK OAuth"""
    
    @staticmethod
    def exchange_code_for_token(code: str, code_verifier: str = None, device_id: str = None) -> Optional[Dict]:
        """
        Обменивает authorization code на access token (старый VK OAuth)
        
        Args:
            code: Authorization code от VK
            code_verifier: (не используется в старом OAuth)
            device_id: (не используется в старом OAuth)
            
        Returns:
            dict: {'access_token': '...', 'user_id': 123, 'email': '...'}
            или None если ошибка
        """
        try:
            # Старый OAuth использует GET запрос с простыми параметрами
            response = requests.get(
                VK_OAUTH_TOKEN_URL,
                params={
                    "client_id": VK_APP_ID,
                    "client_secret": VK_APP_SECRET,
                    "redirect_uri": VK_REDIRECT_URI,
                    "code": code
                },
                timeout=10
            )
            
            print(f"📡 VK Token Response: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if 'error' in result:
                    print(f"❌ VK OAuth error: {result.get('error_description', result['error'])}")
                    return None
                
                # Старый OAuth возвращает: {access_token, user_id, email, expires_in}
                # refresh_token не возвращается (токен живёт долго с scope offline)
                return {
                    'access_token': result.get('access_token'),
                    'refresh_token': None,  # Старый OAuth не даёт refresh_token
                    'user_id': str(result.get('user_id')),  # Конвертируем в строку
                    'expires_in': result.get('expires_in', 0),  # 0 = бессрочный с offline scope
                    'email': result.get('email'),
                    'device_id': None
                }
            else:
                print(f"❌ VK OAuth HTTP error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ VK OAuth exception: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def refresh_access_token(refresh_token: str, device_id: str = None) -> Optional[Dict]:
        """
        Обновляет access_token используя refresh_token
        
        Args:
            refresh_token: Refresh token от VK
            device_id: Device ID (опционально)
            
        Returns:
            dict: {
                'access_token': 'новый токен',
                'refresh_token': 'новый refresh_token',
                'expires_in': секунды
            } или None при ошибке
        """
        try:
            print(f"🔄 Обновление VK токена через refresh_token...")
            
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": VK_APP_ID
            }
            
            if device_id:
                data["device_id"] = device_id
            
            headers = {
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            response = requests.post(
                VK_OAUTH_TOKEN_URL,
                data=data,
                headers=headers,
                timeout=10
            )
            
            print(f"📡 VK Refresh Response: {response.status_code}")
            
            if response.status_code == 200:
                result = response.json()
                
                if 'error' in result:
                    print(f"❌ VK Refresh error: {result.get('error_description', result['error'])}")
                    return None
                
                print(f"✅ VK токен успешно обновлён!")
                
                # Возвращаем новые токены
                return {
                    'access_token': result.get('access_token'),
                    'refresh_token': result.get('refresh_token'),
                    'expires_in': result.get('expires_in', 86400),
                    'user_id': result.get('user_id')
                }
            else:
                print(f"❌ VK Refresh HTTP error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ VK Refresh exception: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    @staticmethod
    def get_user_info(access_token: str, user_id: int) -> Optional[Dict]:
        """
        Получает информацию о пользователе VK
        
        Args:
            access_token: Access token пользователя
            user_id: VK user ID
            
        Returns:
            dict: {
                'id': 123,
                'first_name': 'Иван',
                'last_name': 'Иванов',
                'photo_200': 'https://...',
                'email': 'user@example.com'
            }
        """
        try:
            response = requests.get(
                f"{VK_API_BASE_URL}/users.get",
                params={
                    "access_token": access_token,
                    "user_ids": user_id,
                    "fields": "photo_200,photo_max_orig",
                    "v": VK_API_VERSION
                },
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                if 'response' in data and len(data['response']) > 0:
                    return data['response'][0]
                else:
                    print(f"❌ VK API error: {data}")
                    return None
            else:
                print(f"❌ VK API HTTP error: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ VK API exception: {e}")
            return None
    
    @staticmethod
    def get_user_groups(access_token: str) -> List[Dict]:
        """
        Получает список групп где пользователь является администратором или редактором
        
        Args:
            access_token: VK access token
            
        Returns:
            list: [
                {
                    'id': 123456,
                    'name': 'Название группы',
                    'screen_name': 'group_url',
                    'photo_200': 'https://...',
                    'members_count': 1000
                },
                ...
            ]
        """
        try:
            print(f"🔄 Запрос групп где пользователь админ...")
            
            response = requests.get(
                f"{VK_API_BASE_URL}/groups.get",
                params={
                    "access_token": access_token,
                    "filter": "admin,editor",  # Только где админ или редактор
                    "extended": 1,              # С подробной информацией
                    "fields": "members_count",  # Количество участников
                    "v": VK_API_VERSION
                },
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ VK groups API HTTP error: {response.status_code}")
                return []
            
            result = response.json()
            
            if 'error' in result:
                print(f"❌ VK groups API error: {result['error'].get('error_msg', 'Unknown error')}")
                return []
            
            if 'response' not in result or 'items' not in result['response']:
                print(f"⚠️ Нет групп в ответе VK API")
                return []
            
            groups = result['response']['items']
            print(f"✅ Найдено групп: {len(groups)}")
            
            # Форматируем данные
            formatted_groups = []
            for group in groups:
                formatted_groups.append({
                    'id': group.get('id'),
                    'name': group.get('name', 'Без названия'),
                    'screen_name': group.get('screen_name', ''),
                    'photo_200': group.get('photo_200', ''),
                    'members_count': group.get('members_count', 0)
                })
            
            return formatted_groups
            
        except Exception as e:
            print(f"❌ VK groups exception: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    @staticmethod
    def save_vk_connection(db, telegram_user_id: int, vk_data: Dict) -> bool:
        """
        Сохраняет подключение VK к пользователю Telegram
        
        Args:
            db: Database instance
            telegram_user_id: ID пользователя в Telegram
            vk_data: Данные от VK OAuth
            
        Returns:
            bool: True если успешно
        """
        try:
            # Получаем пользователя
            user = db.get_user(telegram_user_id)
            if not user:
                print(f"❌ Пользователь Telegram {telegram_user_id} не найден в БД")
                return False
            
            # Получаем информацию о пользователе VK
            vk_user_info = VKOAuth.get_user_info(
                vk_data['access_token'],
                vk_data['user_id']
            )
            
            if not vk_user_info:
                print(f"❌ Не удалось получить информацию о VK пользователе {vk_data['user_id']}")
                return False
            
            # Сохраняем подключение
            import time
            
            # Вычисляем время истечения токена
            expires_in = vk_data.get('expires_in', 86400)  # по умолчанию 24 часа
            expires_at = int(time.time()) + expires_in
            
            vk_connection = {
                'user_id': vk_data['user_id'],
                'access_token': vk_data['access_token'],
                'refresh_token': vk_data.get('refresh_token'),
                'device_id': vk_data.get('device_id'),  # КРИТИЧНО для обновления!
                'expires_at': expires_at,
                'email': vk_data.get('email'),
                'first_name': vk_user_info.get('first_name'),
                'last_name': vk_user_info.get('last_name'),
                'photo': vk_user_info.get('photo_200'),
                'status': 'active',
                'connected_at': 'now()',
                'group_name': f"{vk_user_info.get('first_name', '')} {vk_user_info.get('last_name', '')}".strip()
            }
            
            # Обновляем platform_connections пользователя
            platform_connections = user.get('platform_connections', {})
            if isinstance(platform_connections, str):
                platform_connections = json.loads(platform_connections)
            
            # VK сохраняем как массив (как и другие платформы)
            vks = platform_connections.get('vks', [])
            if not isinstance(vks, list):
                vks = []
            
            # ============================================
            # ПРОВЕРКА ГЛОБАЛЬНОЙ УНИКАЛЬНОСТИ VK
            # ============================================
            
            vk_user_id = vk_data['user_id']
            
            # Проверяем что этот VK аккаунт не подключен ни у кого
            db.cursor.execute("""
                SELECT u.id, u.username
                FROM users u
                WHERE u.platform_connections::text LIKE %s
            """, (f'%"user_id": "{vk_user_id}"%',))
            
            existing_users = db.cursor.fetchall()
            
            if existing_users:
                for existing_user in existing_users:
                    existing_user_id = existing_user.get('id') if isinstance(existing_user, dict) else existing_user[0]
                    
                    if existing_user_id != telegram_user_id:
                        # VK уже подключен у другого пользователя
                        print(f"❌ VK ID {vk_user_id} уже подключен у другого пользователя (ID: {existing_user_id})")
                        return False
            
            # ============================================
            
            # Проверяем не подключен ли уже этот VK аккаунт у ТЕКУЩЕГО пользователя
            existing_index = None
            for i, existing_vk in enumerate(vks):
                existing_id = existing_vk.get('id') or existing_vk.get('user_id')
                new_id = vk_data.get('id') or vk_data.get('user_id')
                if str(existing_id) == str(new_id):
                    # VK уже подключен у текущего пользователя - запрещаем
                    print(f"❌ VK ID {vk_user_id} уже подключен у пользователя {telegram_user_id}")
                    return False
            
            # VK не подключен - добавляем
            vks.append(vk_connection)
            
            platform_connections['vks'] = vks
            
            # Сохраняем в БД
            db.cursor.execute("""
                UPDATE users
                SET platform_connections = %s::jsonb
                WHERE id = %s
            """, (json.dumps(platform_connections), telegram_user_id))
            
            db.conn.commit()
            
            print(f"✅ VK подключен для пользователя {telegram_user_id}")
            print(f"   VK ID: {vk_data['user_id']}")
            print(f"   VK Name: {vk_user_info.get('first_name')} {vk_user_info.get('last_name')}")
            
            return True
            
        except Exception as e:
            print(f"❌ Ошибка сохранения VK подключения: {e}")
            try:
                db.conn.rollback()
            except Exception:
                pass
            return False
    
    @staticmethod
    def ensure_valid_token(db, telegram_user_id: int, vk_user_id: str) -> Optional[str]:
        """
        Проверяет токен и обновляет если истёк
        
        Args:
            db: Database instance
            telegram_user_id: ID пользователя в Telegram
            vk_user_id: ID пользователя VK (строка)
            
        Returns:
            str: Валидный access_token или None при ошибке
        """
        try:
            import time
            
            # Получаем пользователя
            user = db.get_user(telegram_user_id)
            if not user:
                print(f"❌ Пользователь {telegram_user_id} не найден")
                return None
            
            # Получаем VK подключение из platform_connections
            connections = user.get('platform_connections', {})
            if isinstance(connections, str):
                connections = json.loads(connections)
            
            vks = connections.get('vks', [])
            
            # Если пусто - пробуем из connected_platforms (у некоторых пользователей там)
            if not vks or vks == []:
                print(f"🔄 VK не найдено в platform_connections, проверяю connected_platforms")
                
                # Получаем бота пользователя
                bots = db.get_user_bots(telegram_user_id)
                if bots:
                    for bot in bots:
                        bot_connections = bot.get('connected_platforms', {})
                        if isinstance(bot_connections, str):
                            bot_connections = json.loads(bot_connections)
                        
                        vks_from_bot = bot_connections.get('vks') or bot_connections.get('vk', [])
                        
                        if isinstance(vks_from_bot, str):
                            try:
                                vks_from_bot = json.loads(vks_from_bot)
                            except Exception:
                                pass
                        
                        if vks_from_bot and isinstance(vks_from_bot, list):
                            vks = vks_from_bot
                            print(f"✅ VK найдено в connected_platforms бота {bot.get('id')}")
                            break
            
            print(f"📋 VK подключений найдено: {len(vks)}")
            
            # DEBUG: показываем структуру всех VK подключений
            for idx, vk in enumerate(vks):
                print(f"   🔍 VK[{idx}]: {vk}")
            
            # Находим нужное подключение
            vk_connection = None
            vk_index = None
            
            print(f"🔎 Ищем VK подключение с vk_user_id={vk_user_id}")
            
            for i, vk in enumerate(vks):
                # Ищем по полю 'id' (основное) или 'user_id' (для совместимости со старыми)
                vk_id = vk.get('id') or vk.get('user_id') or vk.get('group_id')
                
                print(f"   Проверяем VK[{i}]: id={vk.get('id')}, user_id={vk.get('user_id')}, group_id={vk.get('group_id')}")
                print(f"   vk_id={vk_id}, сравниваем с {vk_user_id}: {str(vk_id) == str(vk_user_id)}")
                
                if str(vk_id) == str(vk_user_id) or str(vk.get('user_id')) == str(vk_user_id):
                    vk_connection = vk
                    vk_index = i
                    print(f"   ✅ Найдено совпадение!")
                    break
            
            if not vk_connection:
                print(f"❌ VK подключение {vk_user_id} не найдено")
                return None
            
            # Проверяем не истёк ли токен
            expires_at = vk_connection.get('expires_at', 0)
            current_time = int(time.time())
            
            # Если expires_at = 0 - это бессрочный токен
            if expires_at == 0:
                print(f"✅ Бессрочный токен (expires_at=0), проверка не требуется")
                return vk_connection.get('access_token')
            
            # Если токен истекает в течение 5 минут - обновляем
            # НО только если есть refresh_token!
            refresh_token = vk_connection.get('refresh_token')
            
            if current_time >= (expires_at - 300) and refresh_token:
                print(f"🔄 Токен истёк или истекает скоро. Обновляем...")
                
                device_id = vk_connection.get('device_id')  # КРИТИЧНО!
                
                if not device_id:
                    print(f"⚠️ Нет device_id. Попытка обновить без него...")
                
                # Обновляем токен с device_id
                new_tokens = VKOAuth.refresh_access_token(refresh_token, device_id)
                
                if not new_tokens:
                    print(f"❌ Не удалось обновить токен")
                    return None
                
                # Обновляем данные
                vk_connection['access_token'] = new_tokens['access_token']
                vk_connection['refresh_token'] = new_tokens['refresh_token']
                vk_connection['expires_at'] = current_time + new_tokens['expires_in']
                
                # Сохраняем в БД
                vks[vk_index] = vk_connection
                connections['vks'] = vks
                
                db.cursor.execute("""
                    UPDATE users
                    SET platform_connections = %s::jsonb
                    WHERE telegram_id = %s
                """, (json.dumps(connections), telegram_user_id))
                db.conn.commit()
                
                print(f"✅ Токен обновлён! Истекает через {new_tokens['expires_in']} секунд")
                
                return new_tokens['access_token']
            elif current_time >= (expires_at - 300) and not refresh_token:
                # Токен без refresh_token, но уже истёк
                if current_time > expires_at:
                    print(f"❌ Постоянный токен истёк! expires_at={expires_at}, current={current_time}")
                    print(f"❌ Токен просрочен на {current_time - expires_at} секунд")
                    print(f"ℹ️ Нужно переподключить VK для получения нового токена")
                    return None
                else:
                    print(f"ℹ️ Токен без refresh_token (постоянный), но скоро истечёт")
                    print(f"ℹ️ expires_at: {expires_at}, current: {current_time}, осталось: {expires_at - current_time} сек")
                    # Используем существующий токен
            else:
                # Токен валиден
                remaining = expires_at - current_time
                print(f"✅ Токен валиден. Осталось {remaining} секунд")
                return vk_connection['access_token']
                
        except Exception as e:
            print(f"❌ Ошибка ensure_valid_token: {e}")
            import traceback
            traceback.print_exc()
            return None


print("✅ VK OAuth Handler загружен")
