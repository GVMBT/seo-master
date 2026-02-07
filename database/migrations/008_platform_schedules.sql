-- ═══════════════════════════════════════════════════════════════
-- МИГРАЦИЯ: Таблица расписания публикаций для платформ
-- Версия: 005
-- Дата: 2026-01-26
-- ═══════════════════════════════════════════════════════════════

-- Создаём таблицу расписания публикаций для платформ
CREATE TABLE IF NOT EXISTS platform_schedules (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL,
    platform_type VARCHAR(50) NOT NULL,
    platform_id VARCHAR(255) NOT NULL,
    schedule_days TEXT[] DEFAULT '{}',
    schedule_times TEXT[] DEFAULT '{}',
    post_frequency VARCHAR(20) DEFAULT 'daily',
    enabled BOOLEAN DEFAULT FALSE,
    last_post_time TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category_id, platform_type, platform_id)
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_platform_schedules_category 
ON platform_schedules(category_id);

CREATE INDEX IF NOT EXISTS idx_platform_schedules_platform 
ON platform_schedules(platform_type, platform_id);

CREATE INDEX IF NOT EXISTS idx_platform_schedules_enabled 
ON platform_schedules(enabled);

-- Комментарии
COMMENT ON TABLE platform_schedules IS 'Расписание публикаций для платформ по категориям';
COMMENT ON COLUMN platform_schedules.category_id IS 'ID категории';
COMMENT ON COLUMN platform_schedules.platform_type IS 'Тип платформы (website, pinterest, telegram)';
COMMENT ON COLUMN platform_schedules.platform_id IS 'ID платформы';
COMMENT ON COLUMN platform_schedules.schedule_days IS 'Дни недели для публикаций (mon, tue, wed, thu, fri, sat, sun)';
COMMENT ON COLUMN platform_schedules.schedule_times IS 'Время публикаций (09:00, 12:00, 18:00)';
COMMENT ON COLUMN platform_schedules.post_frequency IS 'Частота публикаций (daily, weekly, monthly)';
COMMENT ON COLUMN platform_schedules.enabled IS 'Включено/выключено';
COMMENT ON COLUMN platform_schedules.last_post_time IS 'Время последней публикации';

-- Логируем результат
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'platform_schedules') THEN
        RAISE NOTICE '✅ Таблица platform_schedules создана успешно';
    ELSE
        RAISE NOTICE '❌ Ошибка создания таблицы platform_schedules';
    END IF;
END $$;
