-- Миграция: Добавление колонки settings в categories для настроек платформ
-- Дата: 2026-01-24
-- Обновлено: Поддержка новой системы настроек изображений

-- Добавляем колонку settings если её нет
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'categories' AND column_name = 'settings'
    ) THEN
        ALTER TABLE categories ADD COLUMN settings JSONB DEFAULT '{}'::jsonb;
        RAISE NOTICE 'Колонка settings добавлена в categories';
    ELSE
        RAISE NOTICE 'Колонка settings уже существует';
    END IF;
END$$;

-- Создаем индекс для быстрого доступа
CREATE INDEX IF NOT EXISTS idx_categories_settings ON categories USING GIN (settings);

-- Инициализируем форматы изображений (массивы)
UPDATE categories 
SET settings = jsonb_set(
    COALESCE(settings, '{}'::jsonb),
    '{pinterest_image_formats}',
    '["2:3"]'::jsonb,
    true
)
WHERE settings IS NULL 
   OR NOT (settings ? 'pinterest_image_formats');

UPDATE categories 
SET settings = jsonb_set(
    COALESCE(settings, '{}'::jsonb),
    '{telegram_image_formats}',
    '["16:9"]'::jsonb,
    true
)
WHERE settings IS NULL 
   OR NOT (settings ? 'telegram_image_formats');

UPDATE categories 
SET settings = jsonb_set(
    COALESCE(settings, '{}'::jsonb),
    '{website_image_formats}',
    '["16:9"]'::jsonb,
    true
)
WHERE settings IS NULL 
   OR NOT (settings ? 'website_image_formats');

-- Instagram форматы
UPDATE categories 
SET settings = jsonb_set(
    COALESCE(settings, '{}'::jsonb),
    '{instagram_image_formats}',
    '["1:1"]'::jsonb,
    true
)
WHERE settings IS NULL 
   OR NOT (settings ? 'instagram_image_formats');

-- VK форматы
UPDATE categories 
SET settings = jsonb_set(
    COALESCE(settings, '{}'::jsonb),
    '{vk_image_formats}',
    '["16:9"]'::jsonb,
    true
)
WHERE settings IS NULL 
   OR NOT (settings ? 'vk_image_formats');

-- Инициализируем стили текста (строки)
UPDATE categories
SET settings = jsonb_set(
    settings,
    '{pinterest_text_style}',
    '"sales"'::jsonb,
    true
)
WHERE NOT (settings ? 'pinterest_text_style');

UPDATE categories
SET settings = jsonb_set(
    settings,
    '{telegram_text_style}',
    '"conversational"'::jsonb,
    true
)
WHERE NOT (settings ? 'telegram_text_style');

UPDATE categories
SET settings = jsonb_set(
    settings,
    '{website_text_style}',
    '"informative"'::jsonb,
    true
)
WHERE NOT (settings ? 'website_text_style');

-- Instagram стиль текста
UPDATE categories
SET settings = jsonb_set(
    settings,
    '{instagram_text_style}',
    '"friendly"'::jsonb,
    true
)
WHERE NOT (settings ? 'instagram_text_style');

-- VK стиль текста
UPDATE categories
SET settings = jsonb_set(
    settings,
    '{vk_text_style}',
    '"conversational"'::jsonb,
    true
)
WHERE NOT (settings ? 'vk_text_style');

-- Инициализируем опциональные настройки (пустые массивы)
UPDATE categories
SET settings = settings 
  || jsonb_build_object(
    'pinterest_image_styles', '[]'::jsonb,
    'pinterest_tones', '[]'::jsonb,
    'pinterest_cameras', '[]'::jsonb,
    'telegram_image_styles', '[]'::jsonb,
    'telegram_tones', '[]'::jsonb,
    'telegram_cameras', '[]'::jsonb,
    'website_image_styles', '[]'::jsonb,
    'website_tones', '[]'::jsonb,
    'website_cameras', '[]'::jsonb,
    'instagram_image_styles', '[]'::jsonb,
    'instagram_tones', '[]'::jsonb,
    'instagram_cameras', '[]'::jsonb,
    'vk_image_styles', '[]'::jsonb,
    'vk_tones', '[]'::jsonb,
    'vk_cameras', '[]'::jsonb
  )
WHERE settings IS NOT NULL
  AND NOT (settings ? 'pinterest_image_styles');

