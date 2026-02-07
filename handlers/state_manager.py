# -*- coding: utf-8 -*-
"""
Менеджер состояний пользователей для обработки многошаговых действий
"""

# Хранилище состояний {user_id: {'state': str, 'data': dict}}
user_states = {}


def set_user_state(user_id, state, data=None):
    """
    Устанавливает состояние пользователя
    
    Args:
        user_id: ID пользователя
        state: Название состояния (например, 'waiting_wp_categories')
        data: Дополнительные данные (dict)
    """
    user_states[user_id] = {
        'state': state,
        'data': data or {}
    }


def get_user_state(user_id):
    """
    Получает состояние пользователя
    
    Args:
        user_id: ID пользователя
        
    Returns:
        dict: {'state': str, 'data': dict} или None
    """
    return user_states.get(user_id)


def clear_user_state(user_id):
    """
    Очищает состояние пользователя
    
    Args:
        user_id: ID пользователя
    """
    if user_id in user_states:
        del user_states[user_id]


print("✅ handlers/state_manager.py загружен")
