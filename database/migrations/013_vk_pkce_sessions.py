# -*- coding: utf-8 -*-
"""
Миграция: Создание таблицы vk_pkce_sessions для хранения PKCE verifiers
"""

def up(cursor):
    """Применить миграцию"""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vk_pkce_sessions (
            telegram_user_id BIGINT PRIMARY KEY,
            code_verifier TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        );
        
        CREATE INDEX IF NOT EXISTS idx_vk_pkce_created 
        ON vk_pkce_sessions(created_at);
        
        -- Автоматическая очистка старых сессий (старше 10 минут)
        CREATE OR REPLACE FUNCTION cleanup_old_vk_pkce_sessions()
        RETURNS void AS $$
        BEGIN
            DELETE FROM vk_pkce_sessions 
            WHERE created_at < NOW() - INTERVAL '10 minutes';
        END;
        $$ LANGUAGE plpgsql;
    """)


def down(cursor):
    """Откатить миграцию"""
    cursor.execute("""
        DROP FUNCTION IF EXISTS cleanup_old_vk_pkce_sessions();
        DROP TABLE IF EXISTS vk_pkce_sessions;
    """)
