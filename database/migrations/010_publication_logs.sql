-- ═══════════════════════════════════════════════════════════════
-- МИГРАЦИЯ: Таблица логов публикаций
-- Версия: 006
-- Дата: 2026-01-26
-- ═══════════════════════════════════════════════════════════════

-- Создаём таблицу логов публикаций
CREATE TABLE IF NOT EXISTS publication_logs (
    id SERIAL PRIMARY KEY,
    category_id INTEGER NOT NULL,
    bot_id INTEGER NOT NULL,
    platform_type VARCHAR(50) NOT NULL,
    platform_id VARCHAR(255) NOT NULL,
    post_type VARCHAR(50) DEFAULT 'article',
    status VARCHAR(20) NOT NULL,
    tokens_spent INTEGER DEFAULT 0,
    error_message TEXT,
    post_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_publication_logs_category 
ON publication_logs(category_id);

CREATE INDEX IF NOT EXISTS idx_publication_logs_platform 
ON publication_logs(platform_type, platform_id);

CREATE INDEX IF NOT EXISTS idx_publication_logs_status 
ON publication_logs(status);

CREATE INDEX IF NOT EXISTS idx_publication_logs_created 
ON publication_logs(created_at);

-- Комментарии
COMMENT ON TABLE publication_logs IS 'Логи публикаций контента на платформы';
COMMENT ON COLUMN publication_logs.category_id IS 'ID категории';
COMMENT ON COLUMN publication_logs.bot_id IS 'ID бота';
COMMENT ON COLUMN publication_logs.platform_type IS 'Тип платформы (website, pinterest, telegram)';
COMMENT ON COLUMN publication_logs.platform_id IS 'ID платформы';
COMMENT ON COLUMN publication_logs.post_type IS 'Тип поста (article, image, video)';
COMMENT ON COLUMN publication_logs.status IS 'Статус (success, error, pending)';
COMMENT ON COLUMN publication_logs.tokens_spent IS 'Потрачено токенов';
COMMENT ON COLUMN publication_logs.error_message IS 'Сообщение об ошибке (если есть)';
COMMENT ON COLUMN publication_logs.post_url IS 'URL опубликованного поста';

-- Логируем результат
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'publication_logs') THEN
        RAISE NOTICE '✅ Таблица publication_logs создана успешно';
    ELSE
        RAISE NOTICE '❌ Ошибка создания таблицы publication_logs';
    END IF;
END $$;
