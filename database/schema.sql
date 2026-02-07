-- ═══════════════════════════════════════════════════════════════
-- СХЕМА БАЗЫ ДАННЫХ ДЛЯ TELEGRAM BOT CREATOR
-- Версия 1.0
-- ═══════════════════════════════════════════════════════════════

-- 1. ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ
CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    tokens INTEGER DEFAULT 1500,
    language VARCHAR(10) DEFAULT 'ru',
    platform_connections JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_platform_connections ON users USING gin(platform_connections);

COMMENT ON TABLE users IS 'Пользователи Telegram бота';
COMMENT ON COLUMN users.id IS 'Telegram ID пользователя';
COMMENT ON COLUMN users.tokens IS 'Баланс токенов';
COMMENT ON COLUMN users.platform_connections IS 'Подключения к внешним площадкам (сайты, соцсети)';

-- ═══════════════════════════════════════════════════════════════

-- 2. ТАБЛИЦА БОТОВ (ПРОЕКТОВ)
CREATE TABLE IF NOT EXISTS bots (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    company_data JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);

COMMENT ON TABLE bots IS 'Созданные пользователями боты';
COMMENT ON COLUMN bots.company_data IS 'Данные компании в формате JSON (название, город, адрес, и т.д.)';

-- ═══════════════════════════════════════════════════════════════

-- 3. ТАБЛИЦА КАТЕГОРИЙ
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    keywords JSONB DEFAULT '[]',
    media JSONB DEFAULT '[]',
    prices JSONB DEFAULT '{}',
    reviews JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_categories_bot_id ON categories(bot_id);

COMMENT ON TABLE categories IS 'Категории внутри ботов';
COMMENT ON COLUMN categories.keywords IS 'Ключевые фразы категории';
COMMENT ON COLUMN categories.media IS 'Медиа файлы категории';
COMMENT ON COLUMN categories.prices IS 'Прайс-лист категории';
COMMENT ON COLUMN categories.reviews IS 'Отзывы категории';

-- ═══════════════════════════════════════════════════════════════

-- 4. ТАБЛИЦА РАСХОДОВ ТОКЕНОВ
CREATE TABLE IF NOT EXISTS token_expenses (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount INTEGER NOT NULL,
    action VARCHAR(255) NOT NULL,
    bot_id INTEGER,
    category_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE SET NULL,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_token_expenses_user_id ON token_expenses(user_id);
CREATE INDEX IF NOT EXISTS idx_token_expenses_created_at ON token_expenses(created_at DESC);

COMMENT ON TABLE token_expenses IS 'История расходов токенов';
COMMENT ON COLUMN token_expenses.amount IS 'Количество потраченных токенов';
COMMENT ON COLUMN token_expenses.action IS 'Описание действия';

-- ═══════════════════════════════════════════════════════════════

-- ПРОВЕРКА УСПЕШНОСТИ СОЗДАНИЯ ТАБЛИЦ
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'users') THEN
        RAISE NOTICE '✅ Таблица users создана успешно';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'bots') THEN
        RAISE NOTICE '✅ Таблица bots создана успешно';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'categories') THEN
        RAISE NOTICE '✅ Таблица categories создана успешно';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'token_expenses') THEN
        RAISE NOTICE '✅ Таблица token_expenses создана успешно';
    END IF;
END $$;

