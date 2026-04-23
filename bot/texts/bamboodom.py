"""User-facing strings for the Bamboodom admin section (Session 1)."""

# Section title (used on entry + smoke-test screens)
BAMBOODOM_TITLE = "BAMBOODOM.RU"

# Entry screen
BAMBOODOM_ENTRY_NAME = "Магазин отделочных материалов (API v1.1)"
BAMBOODOM_STATUS_ENABLED = "Включён"
BAMBOODOM_STATUS_DISABLED = "Выключен"
BAMBOODOM_STATUS_KEY_MISSING = "Включён, ключ не задан"
BAMBOODOM_LAST_OK_NONE = "не выполнялся"
BAMBOODOM_LAST_FAIL_NONE = "—"
BAMBOODOM_ENTRY_HINT = "Проверьте связь с API или перейдите в настройки."

# Smoke-test screen
BAMBOODOM_SMOKE_TITLE = "SMOKE-TEST"
BAMBOODOM_SMOKE_PROGRESS = "Выполняю smoke-test…"
BAMBOODOM_SMOKE_OK = "Ключ принят, API отвечает."
BAMBOODOM_SMOKE_KEY_MISSING = (
    "Ключ API не настроен. Добавьте BAMBOODOM_BLOG_KEY в окружение Railway и перезапустите сервис."
)
BAMBOODOM_SMOKE_KEY_INVALID = "Ключ отклонён сервером (401). Проверьте BAMBOODOM_BLOG_KEY."
BAMBOODOM_SMOKE_RATE_LIMIT = "Rate limit 429. Повторите через {retry_after} сек."
BAMBOODOM_SMOKE_NETWORK = "Сеть недоступна или сервер не ответил: {detail}"
BAMBOODOM_SMOKE_SERVER = "Ошибка сервера bamboodom.ru: {detail}"
BAMBOODOM_SMOKE_UNEXPECTED = "Непредвиденная ошибка: {detail}"
BAMBOODOM_SMOKE_HINT = "Нажмите «Повторить» для новой попытки."

# Settings stub (Сессия 2 наполнит)
BAMBOODOM_SETTINGS_TITLE = "НАСТРОЙКИ BAMBOODOM"
BAMBOODOM_SETTINGS_STUB = "Здесь появятся параметры подключения и кеша в следующей сессии."

# Labels / field names
BAMBOODOM_LABEL_STATUS = "Статус"
BAMBOODOM_LABEL_API_BASE = "API base"
BAMBOODOM_LABEL_VERSION = "Версия"
BAMBOODOM_LABEL_ENDPOINTS = "Endpoints"
BAMBOODOM_LABEL_WRITABLE = "Запись"
BAMBOODOM_LABEL_IMAGE_DIR = "Папка картинок"
BAMBOODOM_LABEL_LAST_OK = "Последний успех"
BAMBOODOM_LABEL_LAST_FAIL = "Последний фейл"
