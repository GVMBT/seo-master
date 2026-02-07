"""
Миграция: Таблица логов публикаций
Дата: 2026-02-02
"""

def up(conn):
    """Создаёт таблицу publication_logs"""
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS publication_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            bot_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            platform_type VARCHAR(50) NOT NULL,
            platform_id VARCHAR(255),
            post_url TEXT,
            word_count INTEGER DEFAULT 0,
            tokens_spent INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'success',
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Индексы для быстрого поиска
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_publication_logs_user_id 
        ON publication_logs(user_id);
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_publication_logs_bot_id 
        ON publication_logs(bot_id);
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_publication_logs_created_at 
        ON publication_logs(created_at);
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_publication_logs_platform_type 
        ON publication_logs(platform_type);
    """)
    
    conn.commit()
    cursor.close()
    print("✅ Таблица publication_logs создана")


def down(conn):
    """Удаляет таблицу publication_logs"""
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS publication_logs;")
    conn.commit()
    cursor.close()
    print("✅ Таблица publication_logs удалена")
