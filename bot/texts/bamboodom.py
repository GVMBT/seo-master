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

BAMBOODOM_PUBLISH_BUTTON = "Публикация (JSON)"

# Entry screen (first FSM state)
BAMBOODOM_PUBLISH_ENTRY_TITLE = "ПУБЛИКАЦИЯ В SANDBOX"
BAMBOODOM_PUBLISH_ENTRY_HINT = (
    "Отправьте JSON статьи одним сообщением, либо прикрепите как .json файл (если превышает 4096 символов)."
)
BAMBOODOM_PUBLISH_SANDBOX_NOTE = "Режим: production. Статья сразу публикуется на /blog/<slug>."

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
BAMBOODOM_PUBLISH_MODE_SANDBOX = "production"

# Rate limit / lock
BAMBOODOM_PUBLISH_LOCKED = "Подождите 3 секунды между публикациями."
BAMBOODOM_PUBLISH_PROGRESS = "Отправляю статью…"

# Result screen
BAMBOODOM_PUBLISH_RESULT_TITLE = "РЕЗУЛЬТАТ ПУБЛИКАЦИИ"
BAMBOODOM_PUBLISH_SUCCESS = "Статья опубликована на /blog/<slug>."
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
BAMBOODOM_AI_PUBLISHING_PROGRESS = "Публикую…"
BAMBOODOM_AI_SANDBOX_NOTE = (
    "Первые 5-10 AI-статей идут в sandbox — сторона B проверяет их у себя, после апрува перейдём на production."
)

# Result
BAMBOODOM_AI_RESULT_TITLE = "AI-СТАТЬЯ ОПУБЛИКОВАНА"
BAMBOODOM_AI_RESULT_SUCCESS = "Статья сгенерирована AI и опубликована на /blog."

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
BAMBOODOM_AI_TIMEOUT = "Генерация превысила лимит 10 минут и прервана. Попробуйте перегенерировать."
BAMBOODOM_AI_CMD_CANCEL_NO_TASK = "Сейчас нет активной генерации."


# ---------------------------------------------------------------------------
# API v1.2 defensive layer — warnings/draft_forced surfacing (Session 4B.1.5)
# ---------------------------------------------------------------------------

BAMBOODOM_PUBLISH_DRAFT_FORCED = (
    "Сервер перевёл статью в DRAFT (bot-key не может публиковать сразу). "
    "Откройте админку сайта bamboodom.ru, проверьте статью и вручную "
    "переведите её из черновика в опубликованные."
)
BAMBOODOM_PUBLISH_WARNINGS_HEADER = "Предупреждения сервера ({count}):"
BAMBOODOM_PUBLISH_WARNING_LINE = "— [{code}] {hint}"
BAMBOODOM_PUBLISH_WARNING_ITEMS_MORE = "  …ещё {count} деталей"
BAMBOODOM_PUBLISH_SIZE = "Размер статьи: {kb} КБ"

# Friendly labels for common warning codes (fallback: raw code string)
BAMBOODOM_WARNING_LABELS = {
    "draft_forced": "Статья переведена в черновик",
    "unknown_articles_in_text": "В тексте упомянуты неизвестные артикулы",
    "denylist_matches": "Сработал семантический denylist",
    "seo_title_missing": "meta_title не задан",
    "seo_title_too_long": "meta_title длиннее 60 символов",
    "seo_description_missing": "meta_description не задан",
    "seo_description_too_long": "meta_description длиннее 160 символов",
    "seo_issues": "Есть замечания по SEO-мете",
    "resized": "Картинка была уменьшена",
    "conversion_gd_missing": "Сервер не смог конвертировать картинку",
}
# =====================================================================
# pkg_4D_yandex_recrawl additions to bot/texts/bamboodom.py
# Просто скопировать всё ниже и вставить в КОНЕЦ файла
# bot/texts/bamboodom.py
# =====================================================================

# --- Root entry (4D) ---
BAMBOODOM_ROOT_TITLE = "BAMBOODOM.RU"
BAMBOODOM_ROOT_SUBTITLE = "Раздел Bamboodom"
BAMBOODOM_ROOT_HINT = "Выберите раздел: статьи или администрирование сайта."

# --- «Статьи» подзаголовок (4D) — старый entry-экран теперь так называется ---
BAMBOODOM_ARTICLES_TITLE = "СТАТЬИ"
BAMBOODOM_ARTICLES_SUBTITLE = "Smoke-test, контекст, артикулы и публикация"

# --- «Администрирование» (4D) ---
BAMBOODOM_ADMIN_TITLE = "АДМИНИСТРИРОВАНИЕ"
BAMBOODOM_ADMIN_SUBTITLE = "Управление сайтом bamboodom.ru"
BAMBOODOM_ADMIN_HINT = "Здесь будут собираться действия по сайту в целом."

# --- Переобход в Я.Вебмастер (4D) ---
BAMBOODOM_RECRAWL_TITLE = "ПЕРЕОБХОД В ЯНДЕКС ВЕБМАСТЕР"
BAMBOODOM_RECRAWL_INTRO = (
    "Бот соберёт sitemap.xml сайта bamboodom.ru, найдёт страницы, "
    "которых не было при прошлом запуске, и отправит их в очередь переобхода."
)
BAMBOODOM_RECRAWL_PROGRESS_CRAWL = "Сканирую sitemap.xml и главную страницу…"
BAMBOODOM_RECRAWL_PROGRESS_SEND = "Отправляю URL'ы в Яндекс Вебмастер ({i}/{total})…"
BAMBOODOM_RECRAWL_NO_AUTH = (
    "Не настроен YANDEX_WEBMASTER_TOKEN. Добавьте OAuth-токен с правом "
    "webmaster:hosts в переменные окружения Railway и перезапустите сервис."
)
BAMBOODOM_RECRAWL_HOST_NOT_FOUND = (
    "Сайт bamboodom.ru не найден среди подтверждённых хостов в кабинете "
    "Яндекс Вебмастера. Откройте https://webmaster.yandex.ru/sites/ и "
    "подтвердите права на сайт."
)
BAMBOODOM_RECRAWL_FOUND = "Найдено всего на сайте: {total}\nИз них новых (не было в прошлом запуске): {new}"
BAMBOODOM_RECRAWL_FIRST_RUN = (
    "Это первый запуск. Бот зафиксировал текущие {total} URL'ов как стартовый "
    "снимок и больше ничего не отправил — иначе пришлось бы лить в очередь "
    "весь сайт. На следующем запуске будут отправлены только новые страницы."
)
BAMBOODOM_RECRAWL_NOTHING_NEW = "Новых страниц нет. Очередь Я.Вебмастера не трогаем."
BAMBOODOM_RECRAWL_PREVIEW_HINT = "Если согласны — нажмите «Отправить в Я.Вебмастер»."
BAMBOODOM_RECRAWL_RESULT_TITLE = "ОТПРАВЛЕНО"
BAMBOODOM_RECRAWL_RESULT_LINE_OK = "Успешно отправлено: {count}"
BAMBOODOM_RECRAWL_RESULT_LINE_FAIL = "С ошибками: {count}"
BAMBOODOM_RECRAWL_RESULT_FAIL_HEADER = "Первые ошибки:"
BAMBOODOM_RECRAWL_RESULT_FAIL_LINE = "— {url}: {err}"
BAMBOODOM_RECRAWL_RESULT_FAIL_MORE = "  …ещё {count}"
BAMBOODOM_RECRAWL_PREVIEW_URL_LINE = "— {url}"
BAMBOODOM_RECRAWL_PREVIEW_URL_MORE = "  …ещё {count}"
BAMBOODOM_RECRAWL_AUTH_FAIL = (
    "OAuth-токен Яндекс Вебмастера невалиден или просрочен. "
    "Сгенерируйте новый: https://oauth.yandex.ru/authorize?response_type=token&client_id=<ID>"
)
BAMBOODOM_RECRAWL_QUOTA_FAIL = "Превышена дневная квота переобхода. Попробуйте завтра."
BAMBOODOM_RECRAWL_NETWORK_FAIL = "Не удалось обратиться к API: {detail}"
BAMBOODOM_RECRAWL_CRAWL_FAIL = (
    "Не удалось обойти сайт: {detail}\nПроверьте https://bamboodom.ru/sitemap.xml — возможно, сайт временно недоступен."
)

# --- 4E дашборд + регенерация sitemap ---
BAMBOODOM_RECRAWL_DASHBOARD_TITLE = "ПЕРЕОБХОД В Я.ВЕБМАСТЕР"
BAMBOODOM_RECRAWL_LABEL_BLOG_TOTAL = "Статей блога на сайте"
BAMBOODOM_RECRAWL_LABEL_IN_INDEX = "В поиске Яндекса"
BAMBOODOM_RECRAWL_LABEL_QUEUE = "Отправлено за 30 дней"
BAMBOODOM_RECRAWL_LABEL_NEW = "Новых для отправки"
BAMBOODOM_RECRAWL_LABEL_QUOTA = "Квота сегодня"
BAMBOODOM_RECRAWL_DASHBOARD_PROGRESS = "Собираю статистику…"
BAMBOODOM_RECRAWL_DASHBOARD_HOSTINFO_FAIL = (
    "Не удалось получить инфо о хосте. Возможно, токену не хватает прав webmaster:hostinfo. "
    "Дашборд показывает только данные краулера."
)
BAMBOODOM_REGEN_TITLE = "РЕГЕНЕРАЦИЯ SITEMAP"
BAMBOODOM_REGEN_PROGRESS = "Прошу сервер пересобрать sitemap_blog.xml…"
BAMBOODOM_REGEN_OK = "Готово. В sitemap_blog.xml сейчас {count} статей."
BAMBOODOM_REGEN_CACHED = "Кэш сервера: предыдущий результат от {ts}, {count} статей."
BAMBOODOM_REGEN_FAIL = "Не удалось: {detail}"

# --- 4E_full: общий sitemap (товары + всё) ---
BAMBOODOM_REGEN_FULL_TITLE = "РЕГЕНЕРАЦИЯ SITEMAP (ВЕСЬ САЙТ)"
BAMBOODOM_REGEN_FULL_PROGRESS = "Прошу сервер пересобрать общий sitemap.xml…"
BAMBOODOM_REGEN_FULL_OK = "Готово. В sitemap.xml сейчас {count} URL."
BAMBOODOM_REGEN_FULL_CACHED = "Кэш сервера: {count} URL, регенерация была в {ts}."
BAMBOODOM_REGEN_FULL_BREAKDOWN_HEADER = "По разделам:"
BAMBOODOM_REGEN_FULL_LABELS = {
    "static_pages": "Статические страницы",
    "wpc_textures": "WPC-текстуры",
    "flex_textures": "Flex-текстуры",
    "reiki": "Реечные панели",
    "profiles": "Профили",
    "lighting": "Освещение",
    "blog_articles": "Статьи блога",
    "verification": "Верификация",
}

# --- 4F: Аналитика (Я.Метрика) ---
BAMBOODOM_ANALYTICS_TITLE = "АНАЛИТИКА"
BAMBOODOM_ANALYTICS_SUBTITLE = "Сводки из Яндекс.Метрики"
BAMBOODOM_ANALYTICS_HINT = "Данные обновляются с задержкой ~30 минут."
BAMBOODOM_ANALYTICS_NO_TOKEN = (
    "Не настроен YANDEX_METRIKA_TOKEN. Добавьте OAuth-токен Метрики в переменные окружения Railway."
)
BAMBOODOM_ANALYTICS_NO_COUNTER = "Не настроен YANDEX_METRIKA_COUNTER_ID."
BAMBOODOM_ANALYTICS_PROGRESS = "Запрашиваю данные у Метрики…"
BAMBOODOM_ANALYTICS_AUTH_FAIL = "OAuth-токен Метрики невалиден или нет доступа к счётчику."
BAMBOODOM_ANALYTICS_FAIL = "Не удалось получить данные: {detail}"
BAMBOODOM_SUMMARY_TITLE_YESTERDAY = "СВОДКА — ВЧЕРА"
BAMBOODOM_SUMMARY_TITLE_WEEK = "СВОДКА — ПОСЛЕДНИЕ 7 ДНЕЙ"
BAMBOODOM_SUMMARY_LABEL_VISITS = "Визиты"
BAMBOODOM_SUMMARY_LABEL_USERS = "Посетители"
BAMBOODOM_SUMMARY_LABEL_PAGEVIEWS = "Просмотры страниц"
BAMBOODOM_SUMMARY_LABEL_BOUNCE = "Отказы"
BAMBOODOM_SUMMARY_LABEL_DURATION = "Время на сайте"
BAMBOODOM_SUMMARY_LABEL_PERIOD = "Период"
BAMBOODOM_TOP_PAGES_TITLE = "ТОП СТРАНИЦ ЗА 7 ДНЕЙ"
BAMBOODOM_TOP_PAGES_HINT = "Формат: # путь — просмотры (посетители)"
BAMBOODOM_TOP_PAGES_EMPTY = "Нет данных за период."
BAMBOODOM_SOURCES_TITLE = "ИСТОЧНИКИ ТРАФИКА (7 ДНЕЙ)"
BAMBOODOM_SOURCES_EMPTY = "Нет данных за период."
BAMBOODOM_QUERIES_TITLE = "ПОИСКОВЫЕ ЗАПРОСЫ (ЯНДЕКС, 7 ДНЕЙ)"
BAMBOODOM_QUERIES_HINT = "Только organic-трафик. Часть запросов скрыта Яндексом (политика приватности)."
BAMBOODOM_QUERIES_EMPTY = "Нет данных за период (или все запросы скрыты Яндексом)."

# --- 4H: Утренний дайджест ---
BAMBOODOM_DIGEST_TITLE = "УТРЕННИЙ ДАЙДЖЕСТ"
BAMBOODOM_DIGEST_HEADER = "Сегодня {today} (данные за {yesterday})"
BAMBOODOM_DIGEST_SECTION_TRAFFIC = "Трафик"
BAMBOODOM_DIGEST_SECTION_BLOG = "Блог"
BAMBOODOM_DIGEST_SECTION_YW = "Я.Вебмастер"
BAMBOODOM_DIGEST_PROGRESS = "Собираю дайджест из всех источников…"

# --- 4I.1: Позиции в Яндексе ---
BAMBOODOM_RANKS_TITLE = "ПОЗИЦИИ В ЯНДЕКСЕ"
BAMBOODOM_RANKS_PROGRESS = "Запрашиваю позиции через DataForSEO… (~10 сек)"
BAMBOODOM_RANKS_NO_HISTORY = "Прогона ещё не было. Жму «Обновить» — стоит ~$0.006."
BAMBOODOM_RANKS_HEAD = "Последний прогон: {date}"
BAMBOODOM_RANKS_LINE_TOP = "  {pos}. {kw}{delta}"
BAMBOODOM_RANKS_LINE_NOTOP = "  —. {kw} (вне топ-100)"
BAMBOODOM_RANKS_LEGEND = "Дельта: ↑ выросли (число позиций), ↓ просели."
BAMBOODOM_RANKS_FAIL = "Не удалось проверить позиции: {detail}"
BAMBOODOM_RANKS_NO_CONFIG = "DATAFORSEO_LOGIN/PASSWORD не настроены."
BAMBOODOM_RANKS_COST = "Стоимость прогона: ~{cents}¢ (US cents)."

# --- 4I.3: Просевшие статьи ---
BAMBOODOM_DECLINING_TITLE = "ПРОСЕВШИЕ СТАТЬИ"
BAMBOODOM_DECLINING_PROGRESS = "Сравниваю трафик неделя-к-неделе…"
BAMBOODOM_DECLINING_EMPTY = "За последнюю неделю просевших статей не найдено."
BAMBOODOM_DECLINING_HEADER = "Сравнение: текущая неделя vs предыдущая. Порог -30%."
BAMBOODOM_DECLINING_LINE = "  {url}\n    {prev} → {now} ({delta})"

# --- 4I.2: Keyword research ---
BAMBOODOM_RESEARCH_TITLE = "ПОДБОР ТЕМ СТАТЕЙ"
BAMBOODOM_RESEARCH_HINT = "Выберите категорию материала — бот найдёт темы с потенциалом."
BAMBOODOM_RESEARCH_PROGRESS = "Запрашиваю Яндекс.Wordstat и фильтрую AI…"
BAMBOODOM_RESEARCH_FAIL = "Не удалось подобрать темы: {detail}"

# --- 4I.4: Авторасписание дайджеста ---
BAMBOODOM_SCHEDULE_TITLE = "АВТОРАСПИСАНИЕ ДАЙДЖЕСТА"
BAMBOODOM_SCHEDULE_ACTIVE = "✅ Автодайджест включён. Будет приходить ежедневно в 07:00 МСК."
BAMBOODOM_SCHEDULE_INACTIVE = "Автодайджест выключен. Можно включить — будет приходить в 07:00 МСК."
BAMBOODOM_SCHEDULE_ID = "QStash schedule_id: {sid}"
BAMBOODOM_SCHEDULE_URL = "Webhook: {url}"
BAMBOODOM_SCHEDULE_NO_PUBLIC_URL = (
    "RAILWAY_PUBLIC_URL не настроен в env — QStash не сможет вызвать webhook. "
    "Добавьте в Railway переменную RAILWAY_PUBLIC_URL=<полный_URL_сервиса>."
)
BAMBOODOM_SCHEDULE_CREATED = "✅ Расписание создано: {sid}"
BAMBOODOM_SCHEDULE_DELETED = "❌ Расписание удалено."
BAMBOODOM_SCHEDULE_FAIL = "Не удалось: {detail}"

# --- 4G: Google Search Console ---
BAMBOODOM_GSC_TITLE = "GOOGLE SEARCH CONSOLE"
BAMBOODOM_GSC_NOT_AUTH = (
    "GSC не подключён. Откройте {auth_url} → авторизуйтесь под "
    "designservice3@gmail.com → дайте доступ webmasters.readonly. "
    "Сторона B должна предварительно добавить ваш email как пользователя в GSC property bamboodom.ru."
)
BAMBOODOM_GSC_NO_CONFIG = "GOOGLE_OAUTH_CLIENT_ID/SECRET не настроены."
BAMBOODOM_GSC_PROGRESS = "Запрашиваю Google Search Console…"
BAMBOODOM_GSC_FAIL = "GSC ошибка: {detail}"
BAMBOODOM_GSC_TOTAL_TITLE = "ИТОГИ GSC ЗА 28 ДНЕЙ"
BAMBOODOM_GSC_LABEL_CLICKS = "Клики"
BAMBOODOM_GSC_LABEL_IMPRESSIONS = "Показы"
BAMBOODOM_GSC_LABEL_CTR = "CTR"
BAMBOODOM_GSC_LABEL_POS = "Средняя позиция"
BAMBOODOM_GSC_QUERIES_TITLE = "ТОП ЗАПРОСОВ В GOOGLE (28 ДНЕЙ)"
BAMBOODOM_GSC_PAGES_TITLE = "ТОП СТРАНИЦ В GOOGLE (28 ДНЕЙ)"
BAMBOODOM_GSC_QUERIES_LINE = "{i}. {q} — {clicks}/{impr} (поз. {pos:.1f})"
BAMBOODOM_GSC_EMPTY = "Нет данных за период."
BAMBOODOM_GSC_HINT_AUTH = "Нажмите «🔑 Авторизовать GSC» чтобы подключить Google."

# --- 4N: Промоут sandbox→production ---
BAMBOODOM_PROMOTE_TITLE = "ПРОМОУТ SANDBOX→PRODUCTION"
BAMBOODOM_PROMOTE_PROMPT = (
    "Введите slug sandbox-статьи которую нужно перевести в production.\n"
    "Slug — последняя часть URL после ?slug=, например:\n"
    "gibkaya-keramika-dlya-krylca-5-oshibok-pri-vybore-materiala"
)
BAMBOODOM_PROMOTE_PROGRESS = "Промоут через blog_promote_from_sandbox…"
BAMBOODOM_PROMOTE_OK = "✅ Готово. Статья {slug} в production: {url}"
BAMBOODOM_PROMOTE_FAIL = "❌ Не удалось: {detail}"
BAMBOODOM_PROMOTE_INVALID = "Slug пустой или содержит недопустимые символы."
BAMBOODOM_PROMOTE_HINT = "Только буквы, цифры и дефис. Без https:// и без &sandbox=1."
