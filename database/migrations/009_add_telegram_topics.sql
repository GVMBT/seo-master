-- Добавление колонки для хранения топиков Telegram
-- Версия: 006

ALTER TABLE categories 
ADD COLUMN IF NOT EXISTS telegram_topics JSONB DEFAULT '[]'::jsonb;

COMMENT ON COLUMN categories.telegram_topics IS 'Топики Telegram канала/группы для публикаций (массив объектов {topic_id, topic_name})';

-- Индекс для быстрого поиска по топикам
CREATE INDEX IF NOT EXISTS idx_categories_telegram_topics ON categories USING gin(telegram_topics);
