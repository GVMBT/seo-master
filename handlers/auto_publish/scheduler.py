# -*- coding: utf-8 -*-
"""
Auto Publish Scheduler
Главный планировщик автоматических публикаций на основе APScheduler
"""
import logging
import threading
from datetime import datetime
from typing import Dict, Any

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    print("⚠️ APScheduler не установлен. Используйте: pip install apscheduler")

logger = logging.getLogger(__name__)

# Маппинг дней недели
DAY_MAPPING = {
    'mon': 'mon',
    'tue': 'tue', 
    'wed': 'wed',
    'thu': 'thu',
    'fri': 'fri',
    'sat': 'sat',
    'sun': 'sun'
}


class AutoPublishScheduler:
    """
    Планировщик автоматических публикаций на основе APScheduler
    
    Использует cron-триггеры для точного запуска в нужное время
    без постоянных проверок в цикле
    """
    
    def __init__(self):
        if not HAS_APSCHEDULER:
            raise ImportError(
                "APScheduler не установлен. Установите: pip install apscheduler"
            )
        
        self.scheduler = BackgroundScheduler()
        self.jobs = {}  # Словарь для отслеживания задач
        logger.info("📅 AutoPublishScheduler инициализирован (APScheduler)")
    
    def start(self):
        """
        Запускает планировщик и регистрирует все задачи
        """
        print("🔄 Загрузка расписаний из БД...")
        
        # Загружаем все активные расписания
        self._load_schedules()
        
        # Запускаем планировщик
        self.scheduler.start()
        
        print(f"✅ Планировщик запущен, зарегистрировано задач: {len(self.jobs)}")
        logger.info(f"✅ APScheduler запущен с {len(self.jobs)} задачами")
    
    def stop(self):
        """
        Останавливает планировщик
        """
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            print("🛑 Планировщик остановлен")
            logger.info("🛑 APScheduler остановлен")
    
    def reload_schedules(self):
        """
        Перезагружает расписания из БД
        
        Вызывается при изменении настроек расписания
        """
        print("🔄 Перезагрузка расписаний...")
        
        # Удаляем все существующие задачи
        for job_id in list(self.jobs.keys()):
            try:
                self.scheduler.remove_job(job_id)
                del self.jobs[job_id]
            except Exception:
                pass
        
        # Загружаем заново
        self._load_schedules()
        
        print(f"✅ Расписания перезагружены: {len(self.jobs)} задач")
        logger.info(f"✅ Расписания перезагружены: {len(self.jobs)} задач")
    
    def _load_schedules(self):
        """
        Загружает расписания из БД и создаёт cron-задачи
        """
        from database.database import db
        
        try:
            print("🔍 Запрашиваю активные расписания из БД...")
            schedules = db.get_active_schedules()
            
            print(f"📊 БД вернула: {type(schedules)}, длина: {len(schedules) if schedules else 0}")
            
            if not schedules:
                print("⚠️ Активных расписаний не найдено в БД")
                print("💡 Проверьте:")
                print("   1. Есть ли расписания в таблице platform_schedules")
                print("   2. Установлено ли enabled = TRUE")
                print("   3. Есть ли связанные категории и боты")
                return
            
            print(f"📋 Найдено активных расписаний: {len(schedules)}")
            
            for idx, schedule in enumerate(schedules, 1):
                try:
                    print(f"\n📝 Обработка расписания {idx}/{len(schedules)}...")
                    
                    # Конвертируем в dict если нужно
                    if not isinstance(schedule, dict):
                        schedule = dict(schedule)
                    
                    schedule_id = schedule.get('id')
                    category_id = schedule.get('category_id')
                    platform_type = schedule.get('platform_type')
                    platform_id = schedule.get('platform_id')
                    
                    print(f"   ID: {schedule_id}, Категория: {category_id}, Платформа: {platform_type}")
                    
                    schedule_days = schedule.get('schedule_days', [])
                    schedule_times = schedule.get('schedule_times', [])
                    
                    print(f"   Дни (тип: {type(schedule_days)}): {schedule_days}")
                    print(f"   Времена (тип: {type(schedule_times)}): {schedule_times}")
                    
                    # Парсим JSON если нужно
                    if isinstance(schedule_days, str):
                        import json
                        schedule_days = json.loads(schedule_days)
                        print(f"   Дни после парсинга: {schedule_days}")
                    
                    if isinstance(schedule_times, str):
                        import json
                        schedule_times = json.loads(schedule_times)
                        print(f"   Времена после парсинга: {schedule_times}")
                    
                    # Проверка что массивы не пустые
                    if not schedule_days or not schedule_times:
                        print(f"   ⚠️ Пропускаем: пустые дни или времена")
                        continue
                    
                    # Создаём задачу для каждого времени
                    for time_str in schedule_times:
                        try:
                            print(f"   🕐 Создаём задачу для времени: {time_str}")
                            hour, minute = map(int, time_str.split(':'))
                            print(f"      Час: {hour}, Минута: {minute}")
                            
                            # Конвертируем дни в формат APScheduler
                            cron_days = ','.join([DAY_MAPPING.get(day, day) for day in schedule_days])
                            print(f"      Cron дни: {cron_days}")
                            
                            # Уникальный ID для задачи
                            job_id = f"schedule_{schedule_id}_{time_str.replace(':', '')}"
                            print(f"      Job ID: {job_id}")
                            
                            # Создаём cron триггер
                            trigger = CronTrigger(
                                day_of_week=cron_days,
                                hour=hour,
                                minute=minute
                            )
                            print(f"      ✅ Триггер создан")
                            
                            # Добавляем задачу
                            job = self.scheduler.add_job(
                                func=self._execute_publication,
                                trigger=trigger,
                                args=[schedule],
                                id=job_id,
                                name=f"{platform_type} - {schedule.get('category_name', 'Unknown')} - {time_str}",
                                replace_existing=True
                            )
                            print(f"      ✅ Задача добавлена в scheduler")
                            
                            self.jobs[job_id] = {
                                'schedule_id': schedule_id,
                                'category_id': category_id,
                                'platform_type': platform_type,
                                'time': time_str,
                                'days': schedule_days
                            }
                            
                            print(f"  ✅ {platform_type} - {time_str} ({cron_days})")
                            
                        except Exception as e:
                            print(f"  ❌ Ошибка создания задачи для времени {time_str}: {e}")
                            import traceback
                            traceback.print_exc()
                            continue
                    
                except Exception as e:
                    logger.error(f"❌ Ошибка обработки расписания {schedule.get('id')}: {e}")
                    print(f"❌ Ошибка обработки расписания {schedule.get('id')}: {e}")
                    import traceback
                    traceback.print_exc()
                    continue
                    
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки расписаний: {e}")
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА загрузки расписаний: {e}")
            import traceback
            traceback.print_exc()
    def _execute_publication(self, schedule: Dict[str, Any]):
        """
        Выполняет публикацию согласно расписанию
        
        Args:
            schedule: Данные расписания
        """
        category_id = schedule.get('category_id')
        platform_type = schedule.get('platform_type')
        platform_id = schedule.get('platform_id')
        user_id = schedule.get('user_id')  # Получаем user_id из расписания
        
        if not all([category_id, platform_type, platform_id]):
            print("❌ Неполные данные расписания")
            logger.error("❌ Неполные данные расписания")
            return
        
        # ВАЖНО: Конвертируем category_id в строку для БД
        category_id = str(category_id)
        
        # ВАЖНО: Используем print чтобы видеть в консоли
        print("="*70)
        print(f"🚀 АВТОПУБЛИКАЦИЯ ЗАПУЩЕНА!")
        print(f"   Время: {datetime.now().strftime('%H:%M:%S')}")
        print(f"   Категория ID: {category_id}")
        print(f"   Платформа: {platform_type}")
        print(f"   Platform ID: {platform_id}")
        print(f"   User ID: {user_id}")  # Показываем user_id
        print("="*70)
        
        logger.info(
            f"🚀 Запуск публикации: "
            f"category_id={category_id}, "
            f"platform={platform_type}, "
            f"platform_id={platform_id}"
        )
        
        # Выбираем соответствующий Publisher
        publisher = self._get_publisher(platform_type, category_id, platform_id, user_id=user_id)
        
        if not publisher:
            print(f"❌ Не удалось создать publisher для {platform_type}")
            logger.error(f"❌ Не удалось создать publisher для {platform_type}")
            return
        
        print(f"✅ Publisher создан для {platform_type}")
        
        # Запускаем публикацию в отдельном потоке
        # чтобы не блокировать основной цикл планировщика
        thread = threading.Thread(
            target=self._publish_in_thread,
            args=(publisher, category_id, platform_type, platform_id),
            daemon=True
        )
        thread.start()
        print(f"🔄 Поток публикации запущен")
    
    def _get_publisher(self, platform_type: str, category_id: str, platform_id: str, user_id: int = None):
        """
        Создает экземпляр Publisher для платформы
        
        Args:
            platform_type: Тип платформы
            category_id: ID категории
            platform_id: ID платформы
            user_id: ID пользователя (владельца бота)
            
        Returns:
            BasePlatformPublisher или None
        """
        try:
            if platform_type == 'website':
                from .platforms.website import WebsitePublisher
                return WebsitePublisher(category_id, platform_id)
            
            elif platform_type == 'telegram':
                from .platforms.telegram import TelegramPublisher
                return TelegramPublisher(category_id, platform_id)
            
            elif platform_type == 'pinterest':
                from .platforms.pinterest import PinterestPublisher
                return PinterestPublisher(category_id, platform_id, user_id=user_id)
            
            elif platform_type == 'vk':
                from .platforms.vk import VKPublisher
                return VKPublisher(category_id, platform_id)
            
            else:
                logger.error(f"❌ Неизвестный тип платформы: {platform_type}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка создания publisher: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _publish_in_thread(self, publisher, category_id: str, platform_type: str, platform_id: str):
        """
        Выполняет публикацию в отдельном потоке
        
        Args:
            publisher: Экземпляр Publisher
            category_id: ID категории
            platform_type: Тип платформы
            platform_id: ID платформы
        """
        try:
            print(f"📤 [{platform_type}] Начало публикации (category={category_id}, platform={platform_id})")
            
            logger.info(
                f"📤 [{platform_type}] Начало публикации "
                f"(category={category_id}, platform={platform_id})"
            )
            
            # Выполняем публикацию
            # execute() сам обрабатывает все ошибки, списание/возврат токенов
            # и отправку отчетов
            print(f"🔄 Вызываю publisher.execute()...")
            success, error, post_url = publisher.execute()
            
            print(f"📊 Результат: success={success}, error={error}, url={post_url}")
            
            if success:
                print(f"✅ [{platform_type}] Публикация успешна: {post_url}")
                logger.info(
                    f"✅ [{platform_type}] Публикация успешна: {post_url}"
                )
            else:
                print(f"❌ [{platform_type}] Публикация не удалась: {error}")
                logger.error(
                    f"❌ [{platform_type}] Публикация не удалась: {error}"
                )
                
        except Exception as e:
            print(f"❌ [{platform_type}] КРИТИЧЕСКАЯ ОШИБКА: {e}")
            logger.error(
                f"❌ [{platform_type}] Непредвиденная ошибка публикации: {e}"
            )
            import traceback
            print("="*70)
            traceback.print_exc()
            print("="*70)
            traceback.print_exc()


# Создаем глобальный экземпляр планировщика
auto_publish_scheduler = AutoPublishScheduler()


# Экспортируем
__all__ = [
    'AutoPublishScheduler',
    'auto_publish_scheduler'
]
