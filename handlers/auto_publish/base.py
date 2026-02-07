# -*- coding: utf-8 -*-
"""
Base Platform Publisher
Базовый абстрактный класс для всех публикаторов платформ
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)


class BasePlatformPublisher(ABC):
    """
    Базовый класс для публикаторов на различных платформах
    
    Все публикаторы должны наследоваться от этого класса и реализовать
    абстрактные методы
    """
    
    def __init__(self, category_id: str, platform_id: str):
        """
        Инициализация публикатора
        
        Args:
            category_id: ID категории для публикации
            platform_id: ID платформы (channel_id, username, url и т.д.)
        """
        self.category_id = category_id
        self.platform_id = platform_id
        self.category = None
        self.user_id = None
        self.platform_data = None
        self.settings = None
        
    def execute(self) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Главный метод выполнения публикации
        
        Выполняет полный цикл публикации:
        1. Загрузка данных категории и платформы
        2. Валидация
        3. Проверка и списание токенов
        4. Публикация
        5. Отправка отчета
        
        Returns:
            tuple: (success: bool, error_msg: str, post_url: str)
        """
        from .utils.token_manager import charge_tokens, refund_tokens
        from .utils.reporter import send_success_report, send_error_report
        from .utils.error_handler import (
            PublishError,
            InsufficientTokensError,
            CategoryNotFoundError
        )
        
        tokens_charged = False
        
        try:
            # 1. Загрузка данных
            logger.info(
                f"📤 [{self.get_platform_name()}] Начало публикации "
                f"category_id={self.category_id}, platform_id={self.platform_id}"
            )
            
            self._load_data()
            
            # 2. КРИТИЧНО: Предварительная валидация БЕЗ списания токенов
            print(f"🔍 Предварительная проверка перед генерацией контента...")
            self.pre_validate()  # Проверка подключения, прав, настроек
            
            # 3. Получение стоимости (после загрузки данных!)
            cost = self.get_cost()
            
            # 4. Проверка баланса БЕЗ списания
            from .utils.token_manager import get_user_balance
            balance = get_user_balance(self.user_id)
            
            if balance < cost:
                print(f"❌ Недостаточно токенов: нужно {cost}, доступно {balance}")
                raise InsufficientTokensError(
                    required=cost,
                    available=balance,
                    platform=self.get_platform_name()
                )
            
            print(f"✅ Все проверки пройдены, начинаем генерацию контента")
            
            # 5. Валидация (дополнительная, если нужна)
            self.validate()
            
            # 6. Списание токенов
            logger.info(f"💰 Списание {cost} токенов с user_id={self.user_id}")
            
            if not charge_tokens(self.user_id, cost):
                raise InsufficientTokensError(
                    required=cost,
                    available=0,
                    platform=self.get_platform_name()
                )
            
            tokens_charged = True
            
            # 7. Публикация (внутри будет генерация контента)
            post_url = self.publish()
            
            # 5. Отправка отчета об успехе
            # ОТКЛЮЧЕНО: Дублирует сообщение из main_menu.py при ручной публикации
            # send_success_report(
            #     user_id=self.user_id,
            #     category_id=self.category_id,
            #     platform_type=self.get_platform_name(),
            #     platform_id=self.platform_id,
            #     post_url=post_url
            # )
            
            logger.info(
                f"✅ [{self.get_platform_name()}] Публикация успешна: {post_url}"
            )
            
            return True, None, post_url
            
        except PublishError as e:
            # Возвращаем токены если были списаны
            if tokens_charged:
                logger.info(f"↩️ Возврат {cost} токенов из-за ошибки")
                refund_tokens(self.user_id, cost)
            
            # Отправляем отчет об ошибке
            send_error_report(
                user_id=self.user_id,
                category_id=self.category_id,
                platform_type=self.get_platform_name(),
                platform_id=self.platform_id,
                error_message=str(e),
                tokens_refunded=tokens_charged
            )
            
            logger.error(f"❌ [{self.get_platform_name()}] Ошибка: {e}")
            return False, str(e), None
            
        except Exception as e:
            # Непредвиденная ошибка
            if tokens_charged:
                logger.info(f"↩️ Возврат {cost} токенов из-за непредвиденной ошибки")
                refund_tokens(self.user_id, cost)
            
            error_msg = f"Непредвиденная ошибка: {e}"
            
            if self.user_id:
                send_error_report(
                    user_id=self.user_id,
                    category_id=self.category_id,
                    platform_type=self.get_platform_name(),
                    platform_id=self.platform_id,
                    error_message=error_msg,
                    tokens_refunded=tokens_charged
                )
            
            logger.error(f"❌ [{self.get_platform_name()}] {error_msg}")
            import traceback
            traceback.print_exc()
            
            return False, error_msg, None
    
    def _load_data(self):
        """
        Загружает данные категории, пользователя и платформы
        
        Raises:
            CategoryNotFoundError: Если категория не найдена
        """
        from database.database import db
        from .utils.error_handler import CategoryNotFoundError
        
        # Загружаем категорию
        self.category = db.get_category(self.category_id)
        if not self.category:
            raise CategoryNotFoundError(self.category_id)
        
        # Конвертируем в dict если нужно
        if not isinstance(self.category, dict):
            self.category = dict(self.category)
        
        # Получаем user_id
        self.user_id = self._get_user_id_from_category()
        
        # Загружаем данные платформы
        self.platform_data = self.get_platform_data()
        
        # Загружаем настройки
        self.settings = self.get_settings()
        
        logger.info(
            f"📊 Данные загружены: user_id={self.user_id}, "
            f"category='{self.category.get('name')}'"
        )
    
    def _get_user_id_from_category(self) -> int:
        """
        Получает user_id из категории
        
        Returns:
            int: ID пользователя
        """
        from database.database import db
        
        bot_id = self.category.get('bot_id')
        if not bot_id:
            raise ValueError("Категория не содержит bot_id")
        
        bot = db.get_bot(bot_id)
        if not bot:
            raise ValueError(f"Бот {bot_id} не найден")
        
        if not isinstance(bot, dict):
            bot = dict(bot)
        
        user_id = bot.get('user_id')
        if not user_id:
            raise ValueError(f"Бот {bot_id} не содержит user_id")
        
        return user_id
    
    @abstractmethod
    def get_platform_name(self) -> str:
        """
        Возвращает название платформы
        
        Returns:
            str: 'website', 'telegram', 'pinterest', 'vk'
        """
        pass
    
    @abstractmethod
    def get_cost(self) -> int:
        """
        Возвращает стоимость публикации в токенах
        
        Returns:
            int: Количество токенов
        """
        pass
    
    @abstractmethod
    def get_platform_data(self) -> Dict[str, Any]:
        """
        Получает данные подключенной платформы из connections
        
        Returns:
            dict: Данные платформы (токены, ID и т.д.)
            
        Raises:
            PlatformNotFoundError: Если платформа не найдена
        """
        pass
    
    @abstractmethod
    def get_settings(self) -> Dict[str, Any]:
        """
        Получает настройки платформы для генерации контента
        
        Returns:
            dict: Настройки (стили, форматы и т.д.)
        """
        pass
    
    @abstractmethod
    def pre_validate(self):
        """
        КРИТИЧНО: Предварительная валидация БЕЗ генерации контента
        
        Проверяет всё что можно проверить ДО списания токенов:
        - Подключение к платформе
        - Права доступа
        - Настройки платформы
        - Наличие обязательных полей
        
        Raises:
            PublishError: Если что-то не так
        """
        # Базовая реализация - переопределяется в каждой платформе
        pass
    
    def validate(self):
        """
        Валидирует данные перед публикацией
        
        Raises:
            ValidationError: Если данные невалидны
        """
        pass
    
    @abstractmethod
    def publish(self) -> str:
        """
        Выполняет публикацию на платформе
        
        Returns:
            str: URL опубликованного поста
            
        Raises:
            PublishError: При любой ошибке публикации
        """
        pass


# Экспортируем базовый класс
__all__ = ['BasePlatformPublisher']
