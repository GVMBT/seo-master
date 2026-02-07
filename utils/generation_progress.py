"""
Модуль для отображения прогресса генерации контента с GIF
"""
from loader import bot
from utils.progress_bars import generate_gradient_progress_bar


class GenerationProgress:
    """Класс для отображения прогресса генерации с GIF и прогресс-баром"""
    
    def __init__(self, chat_id, platform_type="", total_steps=5):
        """
        Args:
            chat_id: ID чата для отправки сообщения
            platform_type: Тип платформы (pinterest, telegram, vk, website)
            total_steps: Общее количество шагов генерации
        """
        self.chat_id = chat_id
        self.platform_type = platform_type.upper() if platform_type else "КОНТЕНТА"
        self.total_steps = total_steps
        self.current_step = 0
        self.message_id = None
        self.gif_url = "https://ecosteni.ru/wp-content/uploads/2026/01/202601191550.gif"
        
        # Названия платформ для заголовка
        self.platform_titles = {
            'PINTEREST': 'ПИНА',
            'TELEGRAM': 'ПОСТА',
            'VK': 'ПОСТА',
            'WEBSITE': 'СТАТЬИ'
        }
    
    def start(self, initial_message="Инициализация..."):
        """
        Начать отображение прогресса
        
        Args:
            initial_message: Начальное сообщение
            
        Returns:
            message_id: ID отправленного сообщения
        """
        platform_title = self.platform_titles.get(self.platform_type, 'КОНТЕНТА')
        progress_bar = generate_gradient_progress_bar(0, total_blocks=12, title=f"ГЕНЕРАЦИЯ {platform_title}")
        
        try:
            msg = bot.send_animation(
                self.chat_id,
                self.gif_url,
                caption=(
                    f"{progress_bar}\n"
                    f"{initial_message}"
                ),
                parse_mode='HTML'
            )
            self.message_id = msg.message_id
            return self.message_id
        except Exception as e:
            print(f"❌ Ошибка отправки GIF: {e}")
            # Fallback - отправляем обычное сообщение
            msg = bot.send_message(
                self.chat_id,
                f"{progress_bar}\n{initial_message}",
                parse_mode='HTML'
            )
            self.message_id = msg.message_id
            return self.message_id
    
    def update(self, step, message, extra_info=""):
        """
        Обновить прогресс
        
        Args:
            step: Текущий шаг (от 1 до total_steps)
            message: Сообщение о текущем действии
            extra_info: Дополнительная информация (опционально)
        """
        if not self.message_id:
            print("⚠️ Нельзя обновить прогресс - сначала вызовите start()")
            return
        
        self.current_step = step
        progress = int((step / self.total_steps) * 100)
        platform_title = self.platform_titles.get(self.platform_type, 'КОНТЕНТА')
        progress_bar = generate_gradient_progress_bar(progress, total_blocks=12, title=f"ГЕНЕРАЦИЯ {platform_title}")
        
        caption = f"{progress_bar}\n{message}"
        if extra_info:
            caption += f"\n\n{extra_info}"
        
        try:
            bot.edit_message_caption(
                caption=caption,
                chat_id=self.chat_id,
                message_id=self.message_id,
                parse_mode='HTML'
            )
        except Exception as e:
            # Игнорируем ошибки обновления (например, если прошло >48 часов)
            print(f"⚠️ Не удалось обновить прогресс: {e}")
    
    def finish(self, delete=True):
        """
        Завершить отображение прогресса
        
        Args:
            delete: Удалить ли сообщение с прогрессом (по умолчанию True)
        """
        if not self.message_id:
            return
        
        if delete:
            try:
                bot.delete_message(self.chat_id, self.message_id)
            except Exception as e:
                print(f"⚠️ Не удалось удалить сообщение с прогрессом: {e}")
        
        self.message_id = None
        self.current_step = 0


# Упрощённая функция для быстрого использования
def show_generation_progress(chat_id, platform_type="", total_steps=5):
    """
    Упрощённая функция для создания и запуска прогресс-бара
    
    Returns:
        GenerationProgress: Объект для управления прогрессом
        
    Example:
        progress = show_generation_progress(chat_id, "pinterest", total_steps=4)
        progress.start("Начинаю генерацию...")
        
        progress.update(1, "Генерирую текст...")
        # ... код генерации текста ...
        
        progress.update(2, "Создаю изображение...")
        # ... код генерации изображения ...
        
        progress.update(3, "Публикую...")
        # ... код публикации ...
        
        progress.finish()  # Удалит сообщение
    """
    progress = GenerationProgress(chat_id, platform_type, total_steps)
    return progress


print("✅ utils/generation_progress.py загружен")
