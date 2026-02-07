# -*- coding: utf-8 -*-
"""
Планировщик автоматических рассылок
Запускает проверку и отправку уведомлений по расписанию
"""
import threading
import time
import logging
from datetime import datetime
from handlers.auto_notifications import check_and_send_notifications

logger = logging.getLogger(__name__)


class NotificationScheduler:
    """Планировщик для автоматических уведомлений"""
    
    def __init__(self):
        self.is_running = False
        self.thread = None
        logger.info("📅 NotificationScheduler инициализирован")
    
    def start(self):
        """Запускает планировщик в отдельном потоке"""
        if self.is_running:
            logger.warning("⚠️ Планировщик уже запущен")
            return
        
        self.is_running = True
        self.thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.thread.start()
        logger.info("✅ Планировщик автоматических уведомлений запущен")
    
    def stop(self):
        """Останавливает планировщик"""
        self.is_running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("🛑 Планировщик автоматических уведомлений остановлен")
    
    def _get_schedule_from_db(self):
        """
        Получает расписание из базы данных
        
        Returns:
            dict: Расписание по времени
        """
        try:
            from database.database import db
            cursor = db.conn.cursor()
            cursor.execute("""
                SELECT schedule_type, schedule_time, enabled, frequency
                FROM schedule_settings
                WHERE enabled = TRUE
            """)
            
            schedule = {}
            rows = cursor.fetchall()
            
            for row in rows:
                schedule_type, schedule_time, enabled, frequency = row
                time_str = str(schedule_time)[:5]  # HH:MM
                
                if time_str not in schedule:
                    schedule[time_str] = []
                
                schedule[time_str].append({
                    'type': schedule_type,
                    'frequency': frequency
                })
            
            cursor.close()
            return schedule
            
        except Exception as e:
            logger.error(f"Ошибка получения расписания из БД: {e}")
            # Откатываем транзакцию при ошибке
            try:
                from database.database import db
                db.conn.rollback()
            except Exception:
                pass
            # Возвращаем дефолтное расписание
            return {
                '10:00': [
                    {'type': 'low_balance', 'frequency': 'daily'}
                ]
            }
    
    def _run_scheduler(self):
        """Основной цикл планировщика"""
        logger.info("🔄 Планировщик начал работу")
        
        # Запускаем первую проверку через 1 минуту после старта
        time.sleep(60)
        
        last_check_minute = -1
        
        while self.is_running:
            try:
                current_time = datetime.now()
                hour = current_time.hour
                minute = current_time.minute
                
                # Проверяем только раз в минуту
                if minute == last_check_minute:
                    time.sleep(10)
                    continue
                
                last_check_minute = minute
                
                # Получаем расписание из БД
                schedule = self._get_schedule_from_db()
                current_time_str = f"{hour:02d}:{minute:02d}"
                
                # Проверяем, есть ли задачи на это время
                if current_time_str in schedule:
                    tasks = schedule[current_time_str]
                    logger.info(f"⏰ Запуск задач в {current_time_str}: {[t['type'] for t in tasks]}")
                    
                    for task in tasks:
                        try:
                            # Запускаем проверку уведомлений
                            check_and_send_notifications()
                            logger.info(f"✅ Выполнена задача: {task['type']}")
                        except Exception as e:
                            logger.error(f"❌ Ошибка выполнения задачи {task['type']}: {e}")
                    
                    # Ждём 2 минуты, чтобы не запускать дважды
                    time.sleep(120)
                    last_check_minute = -1  # Сбрасываем для следующей проверки
                else:
                    # Ждём 30 секунд перед следующей проверкой
                    time.sleep(30)
                    
            except Exception as e:
                logger.error(f"❌ Ошибка в планировщике уведомлений: {e}")
                time.sleep(60)  # Ждём минуту перед следующей попыткой
        
        logger.info("🏁 Планировщик завершил работу")


# Глобальный экземпляр планировщика
notification_scheduler = NotificationScheduler()


def start_notification_scheduler():
    """Запускает планировщик автоматических уведомлений"""
    notification_scheduler.start()


def stop_notification_scheduler():
    """Останавливает планировщик автоматических уведомлений"""
    notification_scheduler.stop()


print("✅ handlers/notification_scheduler.py загружен")
