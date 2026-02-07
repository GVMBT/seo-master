# -*- coding: utf-8 -*-
"""
Token Manager для автопостинга
Управление токенами пользователей: проверка, списание, возврат
"""
import logging

logger = logging.getLogger(__name__)


def check_balance(user_id: int, cost: int) -> bool:
    """
    Проверяет достаточно ли токенов у пользователя
    
    Args:
        user_id: ID пользователя
        cost: Стоимость операции в токенах
        
    Returns:
        bool: True если достаточно токенов, False если нет
    """
    from database.database import db
    from config import ADMIN_ID
    
    try:
        # Конвертируем ADMIN_ID в int (он загружается как строка из .env)
        admin_id = int(ADMIN_ID) if ADMIN_ID else None
        
        # Проверяем ADMIN_ID (GOD режим)
        if admin_id and user_id == admin_id:
            logger.info(f"👑 ADMIN/GOD режим для user_id={user_id}: безлимит токенов")
            return True
        
        user = db.get_user(user_id)
        if not user:
            logger.error(f"❌ Пользователь {user_id} не найден")
            return False
        
        # Конвертируем в dict если нужно
        if not isinstance(user, dict):
            user = dict(user)
        
        # Дополнительная проверка роли GOD в БД (если есть)
        role = user.get('role', '')
        if role and 'GOD' in role.upper():
            logger.info(f"👑 GOD режим (роль) для user_id={user_id}: безлимит токенов")
            return True
        
        current_balance = user.get('tokens', 0)
        
        if current_balance < cost:
            logger.warning(
                f"⚠️ Недостаточно токенов для user_id={user_id}: "
                f"нужно {cost}, есть {current_balance}"
            )
            return False
        
        logger.info(f"✅ Баланс OK для user_id={user_id}: {current_balance} >= {cost}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки баланса: {e}")
        return False


def charge_tokens(user_id: int, cost: int) -> bool:
    """
    Списывает токены у пользователя
    
    Args:
        user_id: ID пользователя
        cost: Сумма к списанию
        
    Returns:
        bool: True если списание успешно, False если ошибка
    """
    from database.database import db
    from config import ADMIN_ID
    
    try:
        # Конвертируем ADMIN_ID в int (он загружается как строка из .env)
        admin_id = int(ADMIN_ID) if ADMIN_ID else None
        
        # Проверяем ADMIN_ID (GOD режим)
        if admin_id and user_id == admin_id:
            logger.info(f"👑 ADMIN/GOD режим: токены НЕ списываются с user_id={user_id}")
            return True
        
        # Проверяем GOD режим из БД
        user = db.get_user(user_id)
        if user:
            if not isinstance(user, dict):
                user = dict(user)
            
            role = user.get('role', '')
            if role and 'GOD' in role.upper():
                logger.info(f"👑 GOD режим (роль): токены НЕ списываются с user_id={user_id}")
                return True
        
        # Проверяем баланс перед списанием
        if not check_balance(user_id, cost):
            return False
        
        # Списываем токены
        result = db.update_tokens(user_id, -cost)
        
        if result:
            new_balance = db.get_user_tokens(user_id)
            logger.info(
                f"💰 Списано {cost} токенов с user_id={user_id}. "
                f"Новый баланс: {new_balance}"
            )
            return True
        else:
            logger.error(f"❌ Не удалось списать токены с user_id={user_id}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка списания токенов: {e}")
        import traceback
        traceback.print_exc()
        return False


def refund_tokens(user_id: int, amount: int) -> bool:
    """
    Возвращает токены пользователю (при ошибке публикации)
    
    Args:
        user_id: ID пользователя
        amount: Сумма к возврату
        
    Returns:
        bool: True если возврат успешен, False если ошибка
    """
    from database.database import db
    
    try:
        result = db.update_tokens(user_id, amount)
        
        if result:
            new_balance = db.get_user_tokens(user_id)
            logger.info(
                f"↩️ Возвращено {amount} токенов user_id={user_id}. "
                f"Новый баланс: {new_balance}"
            )
            return True
        else:
            logger.error(f"❌ Не удалось вернуть токены user_id={user_id}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Ошибка возврата токенов: {e}")
        import traceback
        traceback.print_exc()
        return False


def get_user_balance(user_id: int) -> int:
    """
    Получает текущий баланс пользователя
    
    Args:
        user_id: ID пользователя
        
    Returns:
        int: Количество токенов (0 если ошибка)
    """
    from database.database import db
    
    try:
        tokens = db.get_user_tokens(user_id)
        return tokens if tokens is not None else 0
    except Exception as e:
        logger.error(f"❌ Ошибка получения баланса: {e}")
        return 0


# Экспортируем функции
__all__ = [
    'check_balance',
    'charge_tokens', 
    'refund_tokens',
    'get_user_balance'
]
