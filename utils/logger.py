"""
Централизованная система логирования
"""
import os

# Режим тихого запуска (без лишних ✅)
QUIET_MODE = os.getenv('QUIET_MODE', 'true').lower() == 'true'

def log_success(message: str):
    """Логировать успех (только если не тихий режим)"""
    if not QUIET_MODE:
        print(f"✅ {message}")

def log_info(message: str):
    """Логировать информацию"""
    print(f"ℹ️  {message}")

def log_warning(message: str):
    """Логировать предупреждение"""
    print(f"⚠️  {message}")

def log_error(message: str):
    """Логировать ошибку"""
    print(f"❌ {message}")

def log_critical(message: str):
    """Логировать критичное"""
    print(f"🔴 {message}")
