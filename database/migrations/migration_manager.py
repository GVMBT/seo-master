"""
Менеджер миграций базы данных
"""
import os
from datetime import datetime
from config import DATABASE_URL

# Совместимость с psycopg2 и psycopg3
try:
    import psycopg as psycopg_module
    PSYCOPG_VERSION = 3
except ImportError:
    import psycopg2 as psycopg_module
    PSYCOPG_VERSION = 2


class MigrationManager:
    def __init__(self):
        """Инициализация менеджера миграций"""
        self.conn = psycopg_module.connect(DATABASE_URL)
        self.cursor = self.conn.cursor()
        self.migrations_dir = os.path.dirname(__file__)
        
        # Создаем таблицу для отслеживания миграций
        self._create_migrations_table()
    
    def _create_migrations_table(self):
        """Создать таблицу для отслеживания выполненных миграций"""
        try:
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    id SERIAL PRIMARY KEY,
                    migration_name VARCHAR(255) UNIQUE NOT NULL,
                    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            self.conn.commit()
            print("✅ Таблица schema_migrations готова")
        except Exception as e:
            self.conn.rollback()
            print(f"❌ Ошибка создания таблицы миграций: {e}")
    
    def get_executed_migrations(self):
        """Получить список выполненных миграций"""
        try:
            self.cursor.execute(
                "SELECT migration_name FROM schema_migrations ORDER BY id"
            )
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            self.conn.rollback()
            print(f"❌ Ошибка получения миграций: {e}")
            return []
    
    def get_pending_migrations(self):
        """Получить список невыполненных миграций"""
        # Получаем все файлы миграций
        migration_files = []
        all_files = os.listdir(self.migrations_dir)
        
        # Фильтруем и сортируем по номеру миграции
        sql_files = [f for f in all_files if f.endswith('.sql') and f[0].isdigit()]
        migration_files = sorted(sql_files, key=lambda x: int(x.split('_')[0]))
        
        # Получаем выполненные миграции
        executed = self.get_executed_migrations()
        
        # Возвращаем разницу
        pending = [m for m in migration_files if m not in executed]
        return pending
    
    def execute_migration(self, migration_file):
        """Выполнить одну миграцию"""
        migration_path = os.path.join(self.migrations_dir, migration_file)
        
        try:
            print(f"🔄 Выполняю миграцию: {migration_file}")
            
            # Читаем SQL из файла
            with open(migration_path, 'r', encoding='utf-8') as f:
                sql = f.read()
            
            # Выполняем SQL
            self.cursor.execute(sql)
            
            # Записываем в таблицу миграций
            self.cursor.execute(
                "INSERT INTO schema_migrations (migration_name) VALUES (%s)",
                (migration_file,)
            )
            
            self.conn.commit()
            print(f"✅ Миграция {migration_file} выполнена успешно")
            return True
            
        except Exception as e:
            self.conn.rollback()
            print(f"❌ Ошибка выполнения миграции {migration_file}: {e}")
            return False
    
    def run_migrations(self):
        """Выполнить все невыполненные миграции"""
        pending = self.get_pending_migrations()
        
        if not pending:
            print("✅ Все миграции уже выполнены")
            return True
        
        print(f"📋 Найдено миграций для выполнения: {len(pending)}")
        
        for migration in pending:
            if not self.execute_migration(migration):
                print(f"❌ Остановлено на миграции: {migration}")
                return False
        
        print("✅ Все миграции выполнены успешно")
        return True
    
    def create_migration(self, name, sql_content):
        """Создать новый файл миграции"""
        # Генерируем имя файла с timestamp
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        filename = f"{timestamp}_{name}.sql"
        filepath = os.path.join(self.migrations_dir, filename)
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"-- Миграция: {name}\n")
                f.write(f"-- Создана: {datetime.now()}\n\n")
                f.write(sql_content)
            
            print(f"✅ Создана миграция: {filename}")
            return filename
            
        except Exception as e:
            print(f"❌ Ошибка создания миграции: {e}")
            return None
    
    def status(self):
        """Показать статус миграций"""
        executed = self.get_executed_migrations()
        pending = self.get_pending_migrations()
        
        print("\n" + "="*50)
        print("📊 СТАТУС МИГРАЦИЙ")
        print("="*50)
        
        print(f"\n✅ Выполнено: {len(executed)}")
        for migration in executed:
            print(f"   • {migration}")
        
        if pending:
            print(f"\n⏳ Ожидают выполнения: {len(pending)}")
            for migration in pending:
                print(f"   • {migration}")
        else:
            print(f"\n⏳ Ожидают выполнения: 0")
        
        print("\n" + "="*50 + "\n")
    
    def __del__(self):
        """Закрыть соединение"""
        try:
            if hasattr(self, 'cursor') and self.cursor:
                self.cursor.close()
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
        except Exception:
            pass


print("✅ database/migrations/migration_manager.py загружен")
