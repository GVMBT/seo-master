-- ═══════════════════════════════════════════════════════════════
-- МИГРАЦИЯ: Таблица настроек уведомлений для администратора
-- Версия: 003
-- Дата: 2026-01-26
-- ═══════════════════════════════════════════════════════════════

-- Создаём таблицу настроек уведомлений
CREATE TABLE IF NOT EXISTS notification_settings (
    setting_key VARCHAR(50) PRIMARY KEY,
    setting_value VARCHAR(255) DEFAULT 'on',
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Индексы
CREATE INDEX IF NOT EXISTS idx_notification_settings_enabled 
ON notification_settings(enabled);

-- Комментарии
COMMENT ON TABLE notification_settings IS 'Настройки уведомлений для администратора';
COMMENT ON COLUMN notification_settings.setting_key IS 'Ключ настройки (new_payments, new_users, system_errors, ai_status, low_balance)';
COMMENT ON COLUMN notification_settings.enabled IS 'Включено/выключено уведомление';

-- Вставляем настройки по умолчанию
INSERT INTO notification_settings (setting_key, enabled) VALUES
    ('new_payments', TRUE),
    ('new_users', TRUE),
    ('system_errors', TRUE),
    ('ai_status', TRUE),
    ('low_balance', TRUE)
ON CONFLICT (setting_key) DO NOTHING;

-- Логируем результат
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'notification_settings') THEN
        RAISE NOTICE '✅ Таблица notification_settings создана успешно';
    ELSE
        RAISE NOTICE '❌ Ошибка создания таблицы notification_settings';
    END IF;
END $$;
