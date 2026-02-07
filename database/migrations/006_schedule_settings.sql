-- ═══════════════════════════════════════════════════════════════
-- МИГРАЦИЯ: Таблица расписания автоматических рассылок
-- Версия: 004
-- Дата: 2026-01-26
-- ═══════════════════════════════════════════════════════════════

-- Создаём таблицу расписания рассылок
CREATE TABLE IF NOT EXISTS schedule_settings (
    schedule_type VARCHAR(50) PRIMARY KEY,
    enabled BOOLEAN DEFAULT TRUE,
    schedule_time TIME DEFAULT '10:00:00',
    frequency VARCHAR(20) DEFAULT 'daily',
    last_run TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_schedule_settings_enabled 
ON schedule_settings(enabled);

CREATE INDEX IF NOT EXISTS idx_schedule_settings_time 
ON schedule_settings(schedule_time);

-- Комментарии
COMMENT ON TABLE schedule_settings IS 'Расписание автоматических рассылок';
COMMENT ON COLUMN schedule_settings.schedule_type IS 'Тип рассылки (welcome, low_balance, weekly_news, reactivation)';
COMMENT ON COLUMN schedule_settings.enabled IS 'Включено/выключено';
COMMENT ON COLUMN schedule_settings.schedule_time IS 'Время отправки';
COMMENT ON COLUMN schedule_settings.frequency IS 'Частота (immediate, daily, weekly, monthly)';
COMMENT ON COLUMN schedule_settings.last_run IS 'Время последнего запуска';

-- Вставляем настройки по умолчанию
INSERT INTO schedule_settings (schedule_type, enabled, schedule_time, frequency) VALUES
    ('welcome', TRUE, '09:00:00', 'immediate'),
    ('low_balance', TRUE, '10:00:00', 'daily'),
    ('weekly_news', FALSE, '10:00:00', 'weekly'),
    ('reactivation', TRUE, '11:00:00', 'weekly')
ON CONFLICT (schedule_type) DO NOTHING;

-- Логируем результат
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'schedule_settings') THEN
        RAISE NOTICE '✅ Таблица schedule_settings создана успешно';
    ELSE
        RAISE NOTICE '❌ Ошибка создания таблицы schedule_settings';
    END IF;
END $$;
