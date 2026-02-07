-- Миграция: Начальная схема базы данных
-- Создана: 2026-01-24

-- ═══════════════════════════════════════════════════════════════
-- ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS users (
    id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    first_name VARCHAR(255),
    tokens INTEGER DEFAULT 1500,
    language VARCHAR(10) DEFAULT 'ru',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Добавляем колонку last_activity если её нет
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='users' AND column_name='last_activity') THEN
        ALTER TABLE users ADD COLUMN last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_last_activity ON users(last_activity);

-- ═══════════════════════════════════════════════════════════════
-- ТАБЛИЦА БОТОВ (ПРОЕКТОВ)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS bots (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Добавляем колонку company_data если её нет
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='bots' AND column_name='company_data') THEN
        ALTER TABLE bots ADD COLUMN company_data JSONB DEFAULT '{}';
    END IF;
END $$;

-- Добавляем внешний ключ если его нет
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'bots_user_id_fkey' AND table_name = 'bots'
    ) THEN
        ALTER TABLE bots ADD CONSTRAINT bots_user_id_fkey 
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);

-- ═══════════════════════════════════════════════════════════════
-- ТАБЛИЦА КАТЕГОРИЙ
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    bot_id INTEGER NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Добавляем JSONB колонки если их нет
DO $$ 
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='categories' AND column_name='keywords') THEN
        ALTER TABLE categories ADD COLUMN keywords JSONB DEFAULT '[]';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='categories' AND column_name='media') THEN
        ALTER TABLE categories ADD COLUMN media JSONB DEFAULT '[]';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='categories' AND column_name='prices') THEN
        ALTER TABLE categories ADD COLUMN prices JSONB DEFAULT '{}';
    END IF;
    
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                   WHERE table_name='categories' AND column_name='reviews') THEN
        ALTER TABLE categories ADD COLUMN reviews JSONB DEFAULT '[]';
    END IF;
END $$;

-- Добавляем внешний ключ если его нет
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'categories_bot_id_fkey' AND table_name = 'categories'
    ) THEN
        ALTER TABLE categories ADD CONSTRAINT categories_bot_id_fkey 
        FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_categories_bot_id ON categories(bot_id);
