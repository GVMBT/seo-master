-- Миграция: Добавление колонки platform_connections
-- Создана: 2026-01-24

-- Добавление колонки для хранения подключений к площадкам
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='platform_connections') THEN
        ALTER TABLE users ADD COLUMN platform_connections JSONB DEFAULT '{}';
        
        -- Создаем индекс для быстрого поиска
        CREATE INDEX idx_users_platform_connections ON users USING GIN (platform_connections);
        
        RAISE NOTICE 'Колонка platform_connections добавлена';
    ELSE
        RAISE NOTICE 'Колонка platform_connections уже существует';
    END IF;
END $$;
