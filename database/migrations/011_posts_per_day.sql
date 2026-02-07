-- Миграция 011: Добавление поля posts_per_day в platform_schedules
-- Дата: 2026-01-26

-- Добавляем поле posts_per_day (частота публикаций в день)
ALTER TABLE platform_schedules 
ADD COLUMN IF NOT EXISTS posts_per_day INTEGER DEFAULT 1;

-- Комментарий к полю
COMMENT ON COLUMN platform_schedules.posts_per_day IS 'Количество публикаций в день (1-5)';

-- Проверка: posts_per_day должен быть от 1 до 5
-- Сначала удаляем constraint если он есть, затем создаём заново
DO $$ 
BEGIN
    ALTER TABLE platform_schedules DROP CONSTRAINT IF EXISTS posts_per_day_range;
    ALTER TABLE platform_schedules ADD CONSTRAINT posts_per_day_range CHECK (posts_per_day >= 1 AND posts_per_day <= 5);
END $$;
