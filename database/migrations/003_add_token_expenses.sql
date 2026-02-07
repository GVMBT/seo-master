-- Миграция: Таблица расходов токенов
-- Создана: 2026-01-24

-- Создание таблицы для отслеживания расходов токенов
CREATE TABLE IF NOT EXISTS token_expenses (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    amount INTEGER NOT NULL,
    operation_type VARCHAR(50) NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Индексы для быстрого поиска
CREATE INDEX IF NOT EXISTS idx_token_expenses_user_id ON token_expenses(user_id);
CREATE INDEX IF NOT EXISTS idx_token_expenses_created_at ON token_expenses(created_at);
CREATE INDEX IF NOT EXISTS idx_token_expenses_operation_type ON token_expenses(operation_type);

-- Комментарии
COMMENT ON TABLE token_expenses IS 'История расходов токенов пользователей';
COMMENT ON COLUMN token_expenses.operation_type IS 'Тип операции: text_generation, image_generation, keyword_generation, etc';
