"""
Обертка для генерации статей с прогресс-баром
"""
import time
from telebot import types
from utils.progress_bars import generate_gradient_progress_bar


class ProgressTracker:
    """Класс для отслеживания и отображения прогресса генерации"""
    
    def __init__(self, bot, chat_id, message_id, total_steps=12):
        """
        Args:
            bot: Экземпляр бота
            chat_id: ID чата
            message_id: ID сообщения для обновления
            total_steps: Общее количество шагов (по умолчанию 12 для 12 кругов)
        """
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.total_steps = total_steps
        self.current_step = 0
        self.current_message = ""
        self.last_update_time = 0
        self.min_update_interval = 1.5  # Минимум 1.5 секунды между обновлениями
        
    def update(self, step_message, force=False):
        """
        Обновить прогресс
        
        Args:
            step_message: Текст текущего шага
            force: Принудительное обновление (игнорировать интервал)
        """
        self.current_step += 1
        self.current_message = step_message
        
        # Рассчитываем прогресс в процентах
        progress = int((self.current_step / self.total_steps) * 100)
        if progress > 100:
            progress = 100
        
        # Проверяем интервал обновления
        current_time = time.time()
        if not force and (current_time - self.last_update_time) < self.min_update_interval:
            return  # Слишком часто, пропускаем
        
        # Генерируем прогресс-бар из 12 кругов
        progress_bar = generate_gradient_progress_bar(progress, total_blocks=12, title="ГЕНЕРАЦИЯ СТАТЬИ")
        
        # Формируем сообщение
        text = (
            f"{progress_bar}\n\n"
            f"📋 *Текущий этап:*\n"
            f"_{step_message}_"
        )
        
        try:
            self.bot.edit_message_text(
                text,
                self.chat_id,
                self.message_id,
                parse_mode='Markdown'
            )
            self.last_update_time = current_time
        except Exception as e:
            # Игнорируем ошибки (например, если сообщение не изменилось)
            pass
    
    def complete(self, success_message="Статья успешно создана!"):
        """
        Завершить прогресс с успехом
        
        Args:
            success_message: Сообщение об успехе
        """
        progress_bar = generate_gradient_progress_bar(100, total_blocks=12, title="ГЕНЕРАЦИЯ ЗАВЕРШЕНА")
        
        text = (
            f"{progress_bar}\n\n"
            f"✅ *{success_message}*"
        )
        
        try:
            self.bot.edit_message_text(
                text,
                self.chat_id,
                self.message_id,
                parse_mode='Markdown'
            )
        except Exception:
            pass
    
    def error(self, error_message="Произошла ошибка"):
        """
        Завершить прогресс с ошибкой
        
        Args:
            error_message: Сообщение об ошибке
        """
        text = (
            f"❌ *ОШИБКА ГЕНЕРАЦИИ*\n\n"
            f"_{error_message}_\n\n"
            f"Токены возвращены на ваш счёт."
        )
        
        try:
            self.bot.edit_message_text(
                text,
                self.chat_id,
                self.message_id,
                parse_mode='Markdown'
            )
        except Exception:
            pass


# Стандартные этапы генерации статьи (12 шагов по ~8.3% каждый)
ARTICLE_GENERATION_STEPS = [
    "🎯 Инициализация параметров...",
    "📊 Анализ ключевых слов и контекста...",
    "🎨 Генерация обложки...",
    "📸 Генерация изображений для статьи...",
    "✍️ Написание введения...",
    "📝 Создание основного контента...",
    "🔍 SEO-оптимизация текста...",
    "🏷️ Создание мета-тегов и Schema.org...",
    "🎯 Добавление Yoast SEO разметки...",
    "🔗 Формирование внутренних ссылок...",
    "✨ Финальное форматирование HTML...",
    "💾 Сохранение и подготовка к публикации..."
]


def generate_article_with_progress(bot, chat_id, message_id, generation_func, *args, **kwargs):
    """
    Обертка для генерации статьи с прогресс-баром
    
    Args:
        bot: Экземпляр бота
        chat_id: ID чата
        message_id: ID сообщения
        generation_func: Функция генерации (должна принимать tracker как первый аргумент)
        *args, **kwargs: Аргументы для функции генерации
    
    Returns:
        Результат функции генерации
    """
    tracker = ProgressTracker(bot, chat_id, message_id, total_steps=len(ARTICLE_GENERATION_STEPS))
    
    try:
        # Передаем tracker в функцию генерации
        result = generation_func(tracker, *args, **kwargs)
        
        if result.get('success'):
            tracker.complete("Статья успешно создана и готова к публикации!")
        else:
            tracker.error(result.get('error', 'Неизвестная ошибка'))
        
        return result
        
    except Exception as e:
        tracker.error(f"Критическая ошибка: {str(e)}")
        return {'success': False, 'error': str(e)}


print("✅ utils/article_progress.py загружен")