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


# ---------------------------------------------------------------------------
# AI publish (Session 4A) — AI-generated article submitted to sandbox
# ---------------------------------------------------------------------------

BAMBOODOM_AI_BUTTON = "AI-публикация"

# Entry / material selection
BAMBOODOM_AI_TITLE = "AI-ПУБЛИКАЦИЯ"
BAMBOODOM_AI_CHOOSE_MATERIAL_HINT = "Выберите категорию материала для статьи."
BAMBOODOM_AI_MATERIAL_WPC = "WPC панели"
BAMBOODOM_AI_MATERIAL_FLEX = "Гибкая керамика"
BAMBOODOM_AI_MATERIAL_REIKI = "Реечные панели"
BAMBOODOM_AI_MATERIAL_PROFILES = "Алюминиевые профили"

# Keyword input
BAMBOODOM_AI_KEYWORD_TITLE = "ТЕМА СТАТЬИ"
BAMBOODOM_AI_KEYWORD_PROMPT = (
    "Отправьте тему или ключевое слово одним сообщением.\n\n"
    "Примеры: «как выбрать WPC для ванной», «реечные панели в гостиной», "
    "«монтаж гибкой керамики на колонны»."
)
BAMBOODOM_AI_KEYWORD_EMPTY = "Тема не должна быть пустой. Попробуйте ещё раз."
BAMBOODOM_AI_KEYWORD_TOO_LONG = "Тема слишком длинная (максимум 300 символов)."

# Generating
BAMBOODOM_AI_GENERATING_TITLE = "ГЕНЕРАЦИЯ"
BAMBOODOM_AI_GENERATING_HINT = "Claude пишет статью, это займёт 30-90 секунд. Пожалуйста, подождите."
BAMBOODOM_AI_GENERATING_PROGRESS = "Генерирую статью…"
BAMBOODOM_AI_GENERATION_FAILED = "Не удалось сгенерировать статью: {detail}"

# Preview
BAMBOODOM_AI_PREVIEW_TITLE = "ПРЕДПРОСМОТР (AI)"
BAMBOODOM_AI_PREVIEW_SUMMARY = (
    "— Заголовок: {title}\n— Excerpt: {excerpt}\n— Блоков: {blocks_count}\n— Категория: {material}"
)
BAMBOODOM_AI_PREVIEW_FIRST_PARAGRAPHS = "\n\n<b>Первые абзацы:</b>\n{paragraphs}"
BAMBOODOM_AI_PREVIEW_VALIDATION_WARN = "\n\n⚠ Валидатор нашёл {count} замечаний (auto-retry не помог):"

# Submit / publish
BAMBOODOM_AI_PUBLISHING_PROGRESS = "Публикую в sandbox…"
BAMBOODOM_AI_SANDBOX_NOTE = (
    "Первые 5-10 AI-статей идут в sandbox — сторона B проверяет их у себя, после апрува перейдём на production."
)

# Result
BAMBOODOM_AI_RESULT_TITLE = "AI-СТАТЬЯ ОПУБЛИКОВАНА"
BAMBOODOM_AI_RESULT_SUCCESS = "Статья сгенерирована AI и отправлена в sandbox."

# Cancel
BAMBOODOM_AI_CANCELLED = "Публикация отменена."

# ---------------------------------------------------------------------------
# Generating progress stages (Session 4B.1.4) — live progress bar
# ---------------------------------------------------------------------------

BAMBOODOM_AI_STAGE_INIT = "Инициализация…"
BAMBOODOM_AI_STAGE_CONTEXT = "Загружаю контекст из кеша…"
BAMBOODOM_AI_STAGE_BUILD = "Готовлю промпт с knowledge base…"
BAMBOODOM_AI_STAGE_CALL_PRIMARY = "Пишу статью через Claude Sonnet 4.5 (попытка {attempt})…"
BAMBOODOM_AI_STAGE_CALL_FALLBACK = "Переключаюсь на Claude Opus 4.6…"
BAMBOODOM_AI_STAGE_PARSE = "Разбираю ответ модели (JSON)…"
BAMBOODOM_AI_STAGE_VALIDATE = "Проверяю валидатором (артикулы, запреты, числа)…"
BAMBOODOM_AI_STAGE_LENGTH_RETRY = "Статья короче 1500 слов — расширяю (length retry)…"
BAMBOODOM_AI_STAGE_VALIDATION_RETRY = "Есть замечания валидатора — переделываю (retry)…"
BAMBOODOM_AI_STAGE_DONE = "Готово — открываю превью"

BAMBOODOM_AI_PROGRESS_ELAPSED = "Прошло: {elapsed} сек."
BAMBOODOM_AI_CANCELLED_BY_USER = "Генерация отменена по запросу."
BAMBOODOM_AI_TIMEOUT = "Генерация превысила лимит 5 минут и прервана. Попробуйте перегенерировать."
BAMBOODOM_AI_CMD_CANCEL_NO_TASK = "Сейчас нет активной генерации."
