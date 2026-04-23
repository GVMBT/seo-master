"""User-facing strings for the Bamboodom admin section."""

# Section title (used on entry + smoke-test / context / codes screens)
BAMBOODOM_TITLE = "BAMBOODOM.RU"

# Entry screen
BAMBOODOM_ENTRY_NAME = "Магазин отделочных материалов (API v1.1)"
BAMBOODOM_STATUS_ENABLED = "Включён"
BAMBOODOM_STATUS_DISABLED = "Выключен"
BAMBOODOM_STATUS_KEY_MISSING = "Включён, ключ не задан"
BAMBOODOM_LAST_OK_NONE = "не выполнялся"
BAMBOODOM_LAST_FAIL_NONE = "—"
BAMBOODOM_ENTRY_HINT = "Проверьте связь, контекст сайта и список артикулов."

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

# Context screen
BAMBOODOM_CONTEXT_TITLE = "КОНТЕКСТ САЙТА"
BAMBOODOM_CONTEXT_PROGRESS = "Загружаю контекст…"
BAMBOODOM_CONTEXT_REFRESH_DONE = "Обновлено"
BAMBOODOM_CONTEXT_REFRESH_UNCHANGED = "Данные не изменились"
BAMBOODOM_CONTEXT_STALE_BANNER = "Не удалось обновить: {detail}\nПоказаны данные из кеша (возраст: {age})."
BAMBOODOM_CONTEXT_NO_DATA = "Данные контекста не получены. Проверьте подключение и нажмите «Повторить»."
BAMBOODOM_CONTEXT_SECTION_COMPANY = "Компания"
BAMBOODOM_CONTEXT_SECTION_MATERIALS = "Материалы"
BAMBOODOM_CONTEXT_SECTION_CONTEXTS = "Контексты"
BAMBOODOM_CONTEXT_SECTION_FORBIDDEN = "Запрещённые формулировки"
BAMBOODOM_CONTEXT_HINT = "Обновляется автоматически раз в час."

# Codes screen
BAMBOODOM_CODES_TITLE = "АРТИКУЛЫ"
BAMBOODOM_CODES_PROGRESS = "Загружаю артикулы…"
BAMBOODOM_CODES_NO_DATA = "Список артикулов не получен. Проверьте подключение и нажмите «Повторить»."
BAMBOODOM_CODES_HINT = "Обновляется автоматически раз в час."

# Shared footer labels
BAMBOODOM_LABEL_STATUS = "Статус"
BAMBOODOM_LABEL_API_BASE = "API base"
BAMBOODOM_LABEL_VERSION = "Версия"
BAMBOODOM_LABEL_ENDPOINTS = "Endpoints"
BAMBOODOM_LABEL_WRITABLE = "Запись"
BAMBOODOM_LABEL_IMAGE_DIR = "Папка картинок"
BAMBOODOM_LABEL_LAST_OK = "Последний успех"
BAMBOODOM_LABEL_LAST_FAIL = "Последний фейл"
BAMBOODOM_LABEL_UPDATED_AT = "Обновлено"
BAMBOODOM_LABEL_CACHE_KEY = "cache_key"
BAMBOODOM_LABEL_TOTAL = "Итого"
BAMBOODOM_LABEL_DOMAIN = "Домен"
BAMBOODOM_LABEL_LOCATION = "Локация"
BAMBOODOM_LABEL_TAGLINE = "Слоган"

# Settings stub (Сессия 4)
BAMBOODOM_SETTINGS_TITLE = "НАСТРОЙКИ BAMBOODOM"
BAMBOODOM_SETTINGS_STUB = "Здесь появятся настройки AI-генерации и расписания в следующей сессии."

# Priority ordering for endpoints in smoke-test display (public, user-facing).
# Order matters: these 6 are shown first; the rest are "…+N ещё".
BAMBOODOM_SMOKE_PRIORITY_ENDPOINTS = (
    "blog_context",
    "blog_article_codes",
    "blog_article_info",
    "blog_publish",
    "blog_upload_image",
    "blog_get",
)
BAMBOODOM_SMOKE_ENDPOINTS_MORE = "…+{count} ещё"


# ---------------------------------------------------------------------------
# Publish (Session 3A) — manual sandbox publishing via FSM
# ---------------------------------------------------------------------------

BAMBOODOM_PUBLISH_BUTTON = "Публикация в sandbox"

# Entry screen (first FSM state)
BAMBOODOM_PUBLISH_ENTRY_TITLE = "ПУБЛИКАЦИЯ В SANDBOX"
BAMBOODOM_PUBLISH_ENTRY_HINT = (
    "Отправьте JSON статьи одним сообщением, либо прикрепите как .json файл (если превышает 4096 символов)."
)
BAMBOODOM_PUBLISH_SANDBOX_NOTE = "Режим: sandbox. Статьи живут 7 дней и не видны на публичном /blog.html."

# Example JSON: uses TK001A (stable WPC article) + draft:false (instant preview in sandbox).
BAMBOODOM_PUBLISH_EXAMPLE_JSON = """{
  "title": "Sandbox test — название статьи",
  "excerpt": "Короткое описание 1-2 предложения ← правьте",
  "draft": false,
  "blocks": [
    {"type": "h2", "text": "Заголовок раздела"},
    {"type": "p", "text": "Первый абзац. Разрешены inline-теги: <b>жирный</b>, <i>курсив</i>."},
    {"type": "product", "article": "TK001A"},
    {"type": "callout", "style": "info", "title": "Полезно знать",
     "text": "Текст выноски."}
  ]
}"""

# Errors
BAMBOODOM_PUBLISH_JSON_PARSE_ERROR = "Неверный JSON: {detail}\n\nПроверьте кавычки и скобки, отправьте ещё раз."
BAMBOODOM_PUBLISH_MISSING_FIELDS = "В JSON отсутствуют обязательные поля: {fields}."
BAMBOODOM_PUBLISH_TEXT_TOO_LONG = (
    "Сообщение слишком длинное ({length} симв.). Отправьте JSON как .json файл (прикрепите документ к сообщению)."
)
BAMBOODOM_PUBLISH_FILE_TOO_LARGE = "Файл слишком большой ({size} байт). Лимит 100 KB."
BAMBOODOM_PUBLISH_FILE_READ_ERROR = "Не удалось прочитать файл: {detail}"

# Confirm state
BAMBOODOM_PUBLISH_CONFIRM_TITLE = "ПРЕДПРОСМОТР"
BAMBOODOM_PUBLISH_CONFIRM_TEXT = (
    "Перед отправкой проверьте:\n— Заголовок: {title}\n— Excerpt: {excerpt}\n— Блоков: {blocks_count}\n— Режим: {mode}"
)
BAMBOODOM_PUBLISH_MODE_SANDBOX = "sandbox (7 дней)"

# Rate limit / lock
BAMBOODOM_PUBLISH_LOCKED = "Подождите 3 секунды между публикациями."
BAMBOODOM_PUBLISH_PROGRESS = "Отправляю статью…"

# Result screen
BAMBOODOM_PUBLISH_RESULT_TITLE = "РЕЗУЛЬТАТ ПУБЛИКАЦИИ"
BAMBOODOM_PUBLISH_SUCCESS = "Статья отправлена в sandbox."
BAMBOODOM_PUBLISH_BADGE_SANDBOX = "SANDBOX · автоудаление через 7 дней"
BAMBOODOM_PUBLISH_ACTION_CREATED = "создана"
BAMBOODOM_PUBLISH_ACTION_UPDATED = "обновлена"
BAMBOODOM_PUBLISH_BLOCKS_DROPPED = "Блоков отфильтровано сервером: {count}"
BAMBOODOM_PUBLISH_HINT = "Откройте ссылку для предпросмотра."
BAMBOODOM_PUBLISH_CANCELLED = "Публикация отменена."

# History screen
BAMBOODOM_HISTORY_BUTTON = "История"
BAMBOODOM_HISTORY_TITLE = "ИСТОРИЯ ПУБЛИКАЦИЙ"
BAMBOODOM_HISTORY_EMPTY = "Публикаций пока не было."
BAMBOODOM_HISTORY_HINT = "Хранится до 10 последних записей, максимум 7 дней."

# URL prefix for sandbox preview — use response.url from server if available,
# only fall back to this when URL is missing for some reason.
BAMBOODOM_URL_HOST = "https://bamboodom.ru"
