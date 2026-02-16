# SEO Master Bot v2 — FSM-спецификация

> Связанные документы: [ARCHITECTURE.md](ARCHITECTURE.md) (техническая архитектура), [API_CONTRACTS.md](API_CONTRACTS.md) (API-контракты), [EDGE_CASES.md](EDGE_CASES.md) (обработка ошибок), [UX_PIPELINE.md](UX_PIPELINE.md) + [UX_TOOLBOX.md](UX_TOOLBOX.md) (UX-спецификации)

Все FSM-мастера используют Aiogram 3 StatesGroup с хранением в Redis (Upstash).

**Итого: 18 StatesGroup** (ProjectCreateFSM, CategoryCreateFSM, ProjectEditFSM, KeywordGenerationFSM, KeywordUploadFSM, ArticlePublishFSM, SocialPostPublishFSM, ScheduleSetupFSM, ConnectWordPressFSM, ConnectTelegramFSM, ConnectVKFSM, ConnectPinterestFSM, PriceInputFSM, ReviewGenerationFSM, DescriptionGenerateFSM, CompetitorAnalysisFSM, ArticlePipelineFSM, SocialPipelineFSM)

---

## 1. Определения StatesGroup

```python
# routers/projects/create.py
class ProjectCreateFSM(StatesGroup):
    name = State()           # Шаг 1: название проекта
    company_name = State()   # Шаг 2: название компании
    specialization = State() # Шаг 3: специализация
    website_url = State()    # Шаг 4: URL сайта (пропускаемый)

# routers/categories/keywords.py
class KeywordGenerationFSM(StatesGroup):
    products = State()       # Вопрос 1: товары/услуги
    geography = State()      # Вопрос 2: география
    quantity = State()       # Выбор количества (50/100/150/200)
    confirm = State()        # Подтверждение генерации
    # === Data-first pipeline states (UI progress stages, NOT separate API task_types) ===
    # All stages use one task_type="keywords" (keywords_cluster.yaml v3) for AI clustering.
    # fetching/enriching call DataForSEO directly (no OpenRouter).
    fetching = State()       # DataForSEO keyword_suggestions + related (~3с)
    clustering = State()     # AI кластеризация через keywords_cluster.yaml (~10с), task_type="keywords"
    enriching = State()      # DataForSEO enrich_keywords (~2с), no AI call
    results = State()        # Показ результатов: кластеры с объёмами

# routers/publishing/preview.py
class ArticlePublishFSM(StatesGroup):
    confirm_cost = State()   # Подтверждение стоимости
    generating = State()     # Генерация (ожидание)
    preview = State()        # Предпросмотр: [Опубликовать/Перегенерировать/Отмена]
    publishing = State()     # Публикация в процессе (защита от двойного нажатия, E07)
    regenerating = State()   # Перегенерация (ожидание)

# Примечание: ArticlePublishFSM используется ТОЛЬКО для WordPress (с Telegraph-превью).
# Для Telegram/VK/Pinterest используется SocialPostPublishFSM (без Telegraph).

# routers/publishing/scheduler.py
class ScheduleSetupFSM(StatesGroup):
    select_days = State()    # Выбор дней (множественный)
    select_count = State()   # Количество постов/день
    select_times = State()   # Выбор времени

# routers/platforms/connections.py
class ConnectWordPressFSM(StatesGroup):
    url = State()            # URL сайта
    login = State()          # Логин WordPress
    password = State()       # Application Password

class ConnectTelegramFSM(StatesGroup):
    channel = State()        # Ссылка на канал
    token = State()          # Токен бота

class ConnectVKFSM(StatesGroup):
    token = State()          # VK-токен
    select_group = State()   # Выбор группы из списка

class ConnectPinterestFSM(StatesGroup):
    oauth_callback = State() # Ожидание OAuth
    select_board = State()   # Выбор доски

# OAuth flow для Pinterest:
# 1. Бот отправляет кнопку-ссылку на {RAILWAY_PUBLIC_URL}/api/auth/pinterest?user_id={id}&nonce={nonce}
# 2. Сервер перенаправляет на Pinterest OAuth authorize URL
# 3. Pinterest callback → сервер сохраняет token в Redis (key: pinterest_auth:{nonce})
# 4. Сервер отправляет redirect на deep link: tg://resolve?domain=BOT&start=pinterest_auth_{nonce}
# 5. Бот получает /start pinterest_auth_{nonce} → извлекает token из Redis → FSM.select_board

# routers/categories/prices.py
class PriceInputFSM(StatesGroup):
    choose_method = State()  # Текст или Excel?
    text_input = State()     # Ввод текста
    file_upload = State()    # Загрузка Excel

# routers/categories/reviews.py
class ReviewGenerationFSM(StatesGroup):
    quantity = State()       # 3/5/10 отзывов
    confirm_cost = State()   # Подтверждение стоимости (N × 10 токенов, проверка баланса)
    generating = State()     # Генерация (ожидание)
    review = State()         # Просмотр: [Сохранить/Перегенерировать/Отмена]

# routers/categories/manage.py
class DescriptionGenerateFSM(StatesGroup):
    confirm = State()        # Подтверждение стоимости (20 токенов)
    review = State()         # Просмотр результата: [Сохранить/Перегенерировать/Отмена]

# routers/analysis.py
class CompetitorAnalysisFSM(StatesGroup):
    url = State()            # Ввод URL конкурента
    confirm = State()        # Подтверждение стоимости (50 токенов)
    analyzing = State()      # Анализ (ожидание: Firecrawl scrape + AI analysis)
    results = State()        # Просмотр результатов: [Сохранить/К проекту]

# routers/categories/manage.py
class CategoryCreateFSM(StatesGroup):
    name = State()           # Ввод названия категории (мин. 2 символа)

# routers/projects/create.py
class ProjectEditFSM(StatesGroup):
    field_value = State()    # Ввод нового значения поля (field_name в state.data)

# routers/publishing/pipeline/article.py (Goal-Oriented Pipeline: статьи)
class ArticlePipelineFSM(StatesGroup):
    select_project = State()       # Шаг 1: выбор проекта
    create_project_name = State()  # Inline: создание проекта — название
    create_project_company = State()  # Inline: создание проекта — компания
    create_project_spec = State()  # Inline: создание проекта — специализация
    create_project_url = State()   # Inline: создание проекта — URL
    select_wp = State()            # Шаг 2: выбор WP-подключения
    connect_wp_url = State()       # Inline: подключение WP — URL
    connect_wp_login = State()     # Inline: подключение WP — логин
    connect_wp_password = State()  # Inline: подключение WP — пароль
    select_category = State()      # Шаг 3: выбор категории
    create_category_name = State() # Inline: создание категории — название
    readiness_check = State()      # Шаг 4: чеклист готовности
    readiness_keywords_products = State()  # Inline: ключевые фразы — товары
    readiness_keywords_geo = State()       # Inline: ключевые фразы — география
    readiness_keywords_qty = State()       # Inline: ключевые фразы — количество
    readiness_keywords_generating = State() # Inline: генерация ключевиков
    readiness_description = State()        # Inline: описание категории
    configure_images = State()     # Шаг 4d: настройка изображений
    confirm_cost = State()         # Шаг 5: подтверждение стоимости
    generating = State()           # Шаг 6: генерация
    preview = State()              # Шаг 7: предпросмотр (Telegraph)
    publishing = State()           # Шаг 8: публикация
    regenerating = State()         # Перегенерация

# routers/publishing/pipeline/social.py (Goal-Oriented Pipeline: соц. посты)
class SocialPipelineFSM(StatesGroup):
    select_project = State()       # Шаг 1: выбор проекта
    create_project_name = State()  # Inline: создание проекта — название
    create_project_company = State()  # Inline: создание проекта — компания
    create_project_spec = State()  # Inline: создание проекта — специализация
    create_project_url = State()   # Inline: создание проекта — URL
    select_connection = State()    # Шаг 2: выбор подключения (конкретный канал/группа, НЕ платформа)
    connect_tg_token = State()     # Inline: подключение Telegram — токен канала
    connect_tg_verify = State()    # Inline: подключение Telegram — верификация
    connect_vk_token = State()     # Inline: подключение VK — токен
    connect_vk_group = State()     # Inline: подключение VK — выбор группы
    connect_pinterest_oauth = State()  # Inline: подключение Pinterest — OAuth редирект
    connect_pinterest_board = State()  # Inline: подключение Pinterest — выбор доски
    select_category = State()      # Шаг 3: выбор категории
    create_category_name = State() # Inline: создание категории — название
    readiness_check = State()      # Шаг 4: чеклист готовности (сокращённый: ключевики + описание)
    readiness_keywords_products = State()  # Inline: ключевые фразы — товары
    readiness_keywords_geo = State()       # Inline: ключевые фразы — география
    readiness_keywords_qty = State()       # Inline: ключевые фразы — количество
    readiness_keywords_generating = State() # Inline: генерация ключевиков
    readiness_description = State()        # Inline: описание категории
    confirm_cost = State()         # Шаг 5: подтверждение стоимости
    generating = State()           # Шаг 6: генерация
    review = State()               # Шаг 6→7: ревью сгенерированного поста
    publishing = State()           # Шаг 7: публикация → результат + кросс-постинг
    regenerating = State()         # Перегенерация (аналогично ArticlePipeline)
    cross_post_review = State()    # Кросс-постинг: ревью адаптации (E52)
    cross_post_publishing = State() # Кросс-постинг: публикация

# routers/publishing/social.py (вызывается из pipeline и из карточки категории)
class SocialPostPublishFSM(StatesGroup):
    confirm_cost = State()   # Подтверждение стоимости
    generating = State()     # Генерация (ожидание)
    review = State()         # Просмотр: [Опубликовать/Перегенерировать/Отмена]
    publishing = State()     # Публикация в процессе
    regenerating = State()   # Перегенерация (защита от двойного нажатия)

# routers/categories/keywords.py
class KeywordUploadFSM(StatesGroup):
    file_upload = State()    # Загрузка TXT-файла с фразами
    enriching = State()      # DataForSEO enrich_keywords (~3с)
    clustering = State()     # AI кластеризация (~10с)
    results = State()        # Показ результатов кластеров

# routers/platforms/connections.py — дополнение
# Pinterest OAuth callback endpoint
# ConnectPinterestFSM.oauth_callback: бот отправляет ссылку авторизации,
# пользователь переходит в браузер, после авторизации redirect на:
# {RAILWAY_PUBLIC_URL}/api/auth/pinterest/callback?state={user_id}_{nonce}
# state = HMAC-SHA256(user_id + nonce, ENCRYPTION_KEY) — защита от CSRF
# Callback сохраняет токен в Redis и отправляет deep link:
# tg://resolve?domain=BOT_USERNAME&start=pinterest_auth_{nonce}
# При получении /start pinterest_auth_{nonce} → FSM переходит к select_board
```

---

## 2. Общие правила FSM

- Команда `/cancel` из любого состояния → возврат в предыдущее меню, сброс FSM
- Redis TTL: 24 часа (жёсткое удаление ключа, env: FSM_TTL_SECONDS)
- Таймаут неактивности: 30 мин (env: FSM_INACTIVITY_TIMEOUT) → автосброс FSM, сообщение "Сессия истекла. Начните заново"
- Проверка: middleware сравнивает last_update_time в state.data с текущим временем
- Кнопка [Прервать] сохраняет прогресс для проекта (только ProjectCreateFSM)
- **Конфликт FSM:** Если пользователь начинает новую FSM, находясь в другой — текущая FSM автоматически сбрасывается. Уведомление: "Предыдущий процесс ({old_fsm_name}) прерван. Начинаем {new_fsm_name}." Реализация: в middleware перед `set_state()` проверять `current_state != None`.

### 2.1 Хранение промежуточных данных в FSM

**SocialPostPublishFSM:** Сгенерированный контент (текст + хештеги) хранится в `state.data["generated_content"]` (Redis, TTL = FSM_TTL). Это означает:
- При таймауте 30 мин → контент теряется, токены НЕ возвращаются (для дешёвых соц. постов ~40 токенов — допустимо)
- При Redis TTL 24ч → аналогично
- Для **дорогих** операций (статьи, 320+ токенов) используется `article_previews` в PostgreSQL — устойчиво к перезапуску

> **Принцип:** Redis для дешёвых данных (<50 токенов, потеря допустима), PostgreSQL для дорогих (>100 токенов, нужен refund при сбое). Это намеренное решение — не унифицируем ради простоты.

**ArticlePublishFSM:** Контент НЕ хранится в FSM. Вместо этого:
- `article_previews.id` сохраняется в `state.data["preview_id"]`
- Сам контент — в PostgreSQL (`article_previews.content_html`, `article_previews.images`)
- Изображения: генерация → in-memory → WebP-конвертация → Supabase Storage `content-images` (24ч TTL) → публикация на платформу. `article_previews.images` хранит `[{url, storage_path, width, height}]`
- При таймауте/перезапуске → превью остаётся в БД, cleanup-задача удаляет из Supabase Storage и вернёт токены через 24ч

### 2.1.1 Фичи без FSM (callback-based)

Следующие фичи реализуются через inline-кнопки (callback_data), НЕ через FSM StatesGroup:
- **F16/F41 (Настройки текста/изображений):** toggle-кнопки на экране категории. Нет пользовательского ввода — только выбор из предложенных опций
- **F23 (Медиа-галерея):** загрузка медиа реализуется в рамках существующих FSM (ProjectCreateFSM, CategoryCreateFSM) как опциональный шаг, не отдельный StatesGroup
- **Pipeline (Goal-Oriented):** Заменяет Quick Publish. ArticlePipelineFSM и SocialPipelineFSM реализуют полный flow с inline handlers для sub-flows (через Service Layer). Callback-based навигация до FSM не используется — pipeline сам управляет состояниями

### 2.2 Лимиты перегенерации

| FSM | Бесплатных перегенераций | После лимита | Хранение счётчика |
|-----|-------------------------|-------------|-------------------|
| ArticlePublishFSM | 2 | Новый платный цикл (~320 токенов) | `article_previews.regeneration_count` (PostgreSQL) |
| SocialPostPublishFSM | 2 | Новый платный цикл (~40 токенов) | `state.data["regeneration_count"]` (Redis) |
| DescriptionGenerateFSM | 2 | Новый платный цикл (~20 токенов) | `state.data["regeneration_count"]` (Redis) |

Стоимость перегенерации фиксируется на уровне первой генерации (даже если AI сгенерировал больше/меньше слов).

---

## 3. Валидация ввода на каждом шаге

| FSM | Шаг | Ожидаемый ввод | Валидация | При ошибке |
|-----|-----|----------------|-----------|------------|
| ProjectCreateFSM | name | Текст | 2-100 символов, без спецсимволов | "Введите название от 2 до 100 символов" |
| ProjectCreateFSM | company_name | Текст | 2-200 символов | Аналогично |
| ProjectCreateFSM | specialization | Текст | 5-500 символов | "Опишите подробнее (мин. 5 символов)" |
| ProjectCreateFSM | website_url | Текст или "Пропустить" | URL-формат (http/https) или кнопка [Пропустить] | "Введите корректный URL или нажмите Пропустить" |
| ConnectWordPressFSM | url | Текст | URL с http/https, проверка доступности | "Сайт недоступен. Проверьте URL" |
| ConnectWordPressFSM | login | Текст | 1-100 символов | "Введите логин WordPress" |
| ConnectWordPressFSM | password | Текст | Формат App Password (xxxx xxxx xxxx xxxx) | "Введите Application Password из WordPress" |
| ConnectTelegramFSM | channel | Текст | Формат @channel, t.me/channel, или -100XXXXXXXXXX (числовой ID) | "Введите @channel, t.me/channel или числовой ID" |
| ConnectTelegramFSM | token | Текст | Формат bot_id:hash (проверка через getMe) | "Токен невалиден. Получите токен у @BotFather" |
| KeywordGenerationFSM | products | Текст | 3-1000 символов | "Опишите товары/услуги подробнее" |
| KeywordGenerationFSM | geography | Текст | 2-200 символов | "Укажите географию работы" |
| KeywordGenerationFSM | quantity | Кнопка | Только 50/100/150/200 | Показать кнопки повторно |
| ScheduleSetupFSM | select_days | Кнопки (множ. выбор) | Мин. 1 день | "Выберите хотя бы один день" |
| PriceInputFSM | text_input | Текст | Формат "Название — Цена" per line, мин. 1 строка | "Формат: Товар — Цена (каждый с новой строки)" |
| DescriptionGenerateFSM | confirm | Кнопка | Только [Да, сгенерировать] / [Отмена] | Показать кнопки повторно |
| CompetitorAnalysisFSM | url | Текст | URL-формат (http/https), проверка доступности | "Введите корректный URL сайта конкурента" |
| CategoryCreateFSM | name | Текст | 2-100 символов, без спецсимволов | "Введите название от 2 до 100 символов" |
| ProjectEditFSM | field_value | Текст/URL | Зависит от поля (state.data["field_name"]): URL для website_url, email для company_email, phone для company_phone, 2-500 символов для текстовых | "Некорректный формат для поля {field_name}" |
| SocialPostPublishFSM | confirm_cost | Кнопка | Только [Да, сгенерировать] / [Отмена] | Показать кнопки повторно |
| KeywordUploadFSM | file_upload | Документ | .txt файл, UTF-8, макс. 1 МБ, одна фраза на строку, макс. 500 фраз | "Загрузите TXT-файл (UTF-8), одна фраза на строку. Макс. 500 фраз, 1 МБ" |
| PriceInputFSM | file_upload | Документ | .xlsx файл, макс. 1000 строк, 5 МБ. Колонки: A=Название, B=Цена, C=Описание (опц.) | "Загрузите Excel (.xlsx), макс. 1000 строк, 5 МБ" |
| ScheduleSetupFSM | select_days | Кнопки (множ. выбор) | Мин. 1 день выбран | "Выберите хотя бы один день" |
| ScheduleSetupFSM | select_count | Кнопка | 1-5 | Показать кнопки повторно |
| ScheduleSetupFSM | select_times | Кнопки (множ. выбор) | Ровно posts_per_day штук (из предыдущего шага) | "Выберите ровно {n} временных слотов" |

---

## 4. Обработка невалидного ввода

- Фото/видео/стикер вместо текста → "Пожалуйста, отправьте текстовое сообщение"
- Команда /start во время FSM → сброс FSM, переход в главное меню
- Любая другая команда → "Вы в процессе {действие}. Отправьте /cancel для отмены"

---

## 5. Переходы между состояниями (transition diagrams)

**Общая конвенция:** `/cancel` из любого состояния → `CLEAR_STATE` + возврат в меню. Таймаут 30 мин → `CLEAR_STATE` + "Сессия истекла".

### ArticlePublishFSM (WordPress)

```
[Кнопка "Опубликовать" в категории]
  │
  ▼
confirm_cost ──[Да, сгенерировать]──► generating ──[AI завершил]──► preview
  │                                      │                           │
  [Отмена]                              [Ошибка AI]                 ├──[Опубликовать]──► publishing ──► CLEAR_STATE + лог
  │                                      │                           │                      │
  ▼                                      ▼                           [Перегенерировать]    [Ошибка]──► preview + сообщение
CLEAR_STATE                     CLEAR_STATE + возврат токенов        │
                                                                     ▼
                                                                  regenerating ──[AI завершил]──► preview
                                                                     │
                                                                    [Ошибка AI]──► preview + сообщение
```

### SocialPostPublishFSM (Telegram / VK / Pinterest)

```
[Callback: pipeline:social:{conn_id}:confirm или из карточки категории]
  │
  ▼
confirm_cost ──[Да]──► generating ──[OK]──► review
  │                       │                  │
  [Отмена]              [Ошибка]            ├──[Опубликовать]──► publishing ──► CLEAR_STATE
  ▼                       ▼                  ├──[Перегенерировать]──► regenerating ──[OK]──► review
CLEAR_STATE         CLEAR_STATE              [Отмена]──► CLEAR_STATE
                    + возврат токенов
```

### ProjectCreateFSM (быстрый старт)

```
name ──[валидный текст]──► company_name ──[валидный текст]──► specialization ──[валидный текст]──► website_url ──[URL или Пропустить]──► CLEAR_STATE + сохранение
  │                           │                                  │                                   │
  [невалидный]               [невалидный]                      [невалидный]                        [невалидный URL]
  └── повтор запроса          └── повтор запроса                └── повтор запроса                   └── повтор запроса
```

### ScheduleSetupFSM

```
select_days ──[мин. 1 день]──► select_count ──[1-5]──► select_times ──[ровно N слотов]──► CLEAR_STATE + сохранение + создание QStash
```

### ConnectWordPressFSM / ConnectTelegramFSM / ConnectVKFSM

```
# WordPress:
url ──[валидный URL]──► login ──[текст]──► password ──[App Password]──► validate_connection ──[OK]──► CLEAR_STATE + сохранение
                                                                          │
                                                                         [Fail]──► CLEAR_STATE + "Не удалось подключиться"

# Telegram:
channel ──[@channel]──► token ──[bot_id:hash, getMe OK]──► validate (бот = админ канала) ──► CLEAR_STATE + сохранение

# VK:
token ──[VK token]──► select_group ──[выбор одной группы]──► CLEAR_STATE + сохранение
```

### ConnectPinterestFSM (OAuth)

```
oauth_callback ──[отправка ссылки авторизации]──► (ожидание /start pinterest_auth_{nonce}) ──► select_board ──► CLEAR_STATE + сохранение
```

### KeywordGenerationFSM (data-first pipeline)

```
products ──[валидный текст]──► geography ──[валидный текст]──► quantity ──[кнопка 50/100/150/200]──► confirm
  │                                │                                                                   │
  [невалидный]                    [невалидный]                                                    ├──[Да, генерировать]
  └── повтор                       └── повтор                                                      │       │
                                                                                                   │       ▼
                                                                                                   │   fetching ──► "Получаю реальные фразы..."
                                                                                                   │       │
                                                                                                   │  [DataForSEO OK, ~3с]     [E03: DataForSEO недоступен]
                                                                                                   │       │                          │
                                                                                                   │       ▼                          ▼
                                                                                                   │   clustering ──► "Группирую по интенту..."
                                                                                                   │       │                   results (legacy, без кластеров)
                                                                                                   │  [AI OK, ~10с]                   │
                                                                                                   │       ▼                          ▼
                                                                                                   │   enriching ──► "Обогащаю данными..."   CLEAR_STATE
                                                                                                   │       │
                                                                                                   │  [DataForSEO OK, ~2с]
                                                                                                   │       ▼
                                                                                                   │   results ──► "15 кластеров (100 фраз)"
                                                                                                   │       │
                                                                                                   │       ▼
                                                                                                   │   CLEAR_STATE + сохранение в categories.keywords
                                                                                                   │
                                                                                                   [Отмена]──► CLEAR_STATE
```

**Progress messages:** На каждом шаге pipeline бот отправляет (или editMessageText) сообщение с текущим статусом:
- `fetching`: "Получаю реальные поисковые фразы из Google... (3 сек)"
- `clustering`: "Группирую фразы по поисковому интенту... (10 сек)"
- `enriching`: "Обогащаю данные: объём, сложность, CPC... (2 сек)"
- `results`: показать кластеры (compact формат, см. USER_FLOWS)

**E03 Fallback:** Если DataForSEO недоступен на шаге `fetching` → AI генерирует фразы "из головы" (legacy keywords.yaml v2), без кластеризации. Предупредить: "Данные без реальных объёмов поиска".

### KeywordUploadFSM (загрузка своих фраз)

```
file_upload ──[TXT файл OK]──► enriching ──[DataForSEO OK]──► clustering ──[AI OK]──► results ──► CLEAR_STATE
  │                               │                               │
  [невалидный файл]             [E03]──► results (legacy)       [Error]──► results (без кластеров)
  └── повтор запроса                      └── CLEAR_STATE                    └── CLEAR_STATE
```

### CompetitorAnalysisFSM

```
[Кнопка "Анализ конкурента" в проекте]
  │
  ▼
url ──[валидный URL]──► confirm ──[Да, анализировать (50 токенов)]──► analyzing ──[OK]──► results
  │                        │                                             │                │
  [невалидный URL]        [Отмена]                                     [E31/ошибка]      ├──[Сохранить]──► CLEAR_STATE + лог
  └── повтор запроса       ▼                                             ▼                [К проекту]──► CLEAR_STATE
                        CLEAR_STATE                              CLEAR_STATE
                                                                 + возврат токенов
```

**Pipeline:** Firecrawl /scrape → AI анализ (task_type="competitor_analysis") → структурированный результат (позиционирование, преимущества, рекомендации).
**E31:** Если Firecrawl недоступен → возврат токенов, "Анализ конкурентов недоступен. Попробуйте позже."
**E38:** Если баланс < 50 → "Недостаточно токенов. Нужно 50, у вас {balance}. [Пополнить]"

**Пост-обработка загруженных фраз:**
1. Парсирование TXT: одна фраза на строку, валидация (не пусто, ≤100 символов/фраза)
2. DataForSEO `enrich_keywords()` → volume, difficulty, CPC
3. AI кластеризация (keywords_cluster.yaml с raw_keywords = загруженные фразы)
4. Сохранение в `categories.keywords` в кластерном формате
5. При E03 на `enriching` → skip `clustering`, сохранить в legacy-формате (плоский список без volume/difficulty), предупредить: "Данные без объёмов поиска"
6. При AI error на `clustering` → сохранить как один кластер (все фразы, cluster_name = category_name), volume/difficulty из enrichment

### ArticlePipelineFSM (Goal-Oriented Pipeline: статьи)

> Подробное описание: [UX_PIPELINE.md](UX_PIPELINE.md) §4.1, §12, §13

```
[CTA "Написать статью" на Dashboard]
  │
  ▼
select_project ──[выбрал проект]──► select_wp ──[выбрал WP]──► select_category ──[выбрал]──► readiness_check
  │                                    │                          │                              │
  [Нет проектов]                      [Нет WP]                  [Нет категорий]                ├──[Всё готово]──► confirm_cost
  │                                    │                          │                              │
  ▼                                    ▼                          ▼                              [Нет ключевиков]
create_project_name                connect_wp_url             create_category_name                │
  │                                    │                          │                              ▼
  ▼                                    ▼                          ▼                          readiness_keywords_products
create_project_company             connect_wp_login            readiness_check                   │
  │                                    │                                                        ▼
  ▼                                    ▼                                                    readiness_keywords_geo
create_project_spec                connect_wp_password                                          │
  │                                    │                                                        ▼
  ▼                                    ▼                                                    readiness_keywords_qty
create_project_url ──► select_wp   validate ──► select_category                                 │
                                                                                                ▼
                                                                                            readiness_keywords_generating
                                                                                                │
                                                                                                ▼
                                                                                            readiness_check (обновлён)

confirm_cost ──[Да]──► generating ──[OK]──► preview
  │                       │                   │
  [Отмена]              [Ошибка]             ├──[Опубликовать]──► publishing ──► CLEAR_STATE + лог
  ▼                       ▼                   ├──[Перегенерировать]──► regenerating ──► preview
CLEAR_STATE         CLEAR_STATE              [Отмена — вернуть токены]──► CLEAR_STATE + refund
                    + возврат токенов
```

**Inline handlers:** Pipeline НЕ вызывает существующие FSM (ProjectCreateFSM, ConnectWordPressFSM, etc.) как sub-flows. Вместо этого реализует inline states внутри ArticlePipelineFSM, переиспользуя Service Layer (ProjectRepository, ConnectionService, KeywordService).

**Checkpoint:** Redis ключ `pipeline:{user_id}:state` (TTL 24ч) сохраняет прогресс между сессиями. При возврате на Dashboard — предложение продолжить (E49).

**Exit protection:** На шагах 4-7 кнопка [Назад] требует подтверждения: "Вы уверены? Прогресс сохранится." (E49).

### SocialPipelineFSM (Goal-Oriented Pipeline: соц. посты, 27 состояний)

> Подробное описание: [UX_PIPELINE.md](UX_PIPELINE.md) §5.1, §11

```
[CTA "Опубликовать пост" на Dashboard]
  │
  ▼
select_project ──[выбрал]──► select_connection ──[подключение]──► select_category ──[выбрал]──► readiness_check
  │                              │                                  │                            │
  [Нет проектов]                [Нет подключений]                 [Нет категорий]              [Готово]
  ▼                              ▼                                  ▼                            ▼
create_project_name          [Подключить TG] → connect_tg_token  create_category_name        confirm_cost ──[Да]──► generating ──[OK]──► review
  → _company → _spec           → connect_tg_verify                 → select_category            │                       │                │
  → _url → select_project    [Подключить VK] → connect_vk_token   (автовозврат)                [Отмена]              [Ошибка]          ├──[Опубликовать]──► publishing ──► CLEAR_STATE + результат
  (автовозврат)                → connect_vk_group                                              ▼                       ▼                ├──[Перегенерировать]──► regenerating ──► review
                             [Подключить Pin] → connect_pinterest                           CLEAR_STATE          CLEAR_STATE            [Отмена]──► CLEAR_STATE + refund
                               _oauth → _board                                                                   + refund
                             (автовозврат в pipeline)                                                                                   (на экране результата)
                                                                                                                                        ├──[Кросс-пост для VK]──► cross_post_review
  readiness_check sub-flows (inline, сокращённый чеклист):                                                                              └──[Ещё пост] / [Главное меню]
  ├── readiness_keywords_products → _geo → _qty → _generating → readiness_check
  └── readiness_description → readiness_check

cross_post_review ──[Подтвердить]──► cross_post_publishing ──► CLEAR_STATE + лог
  │                                      │
  [Отмена]                             [Ошибка] ──► CLEAR_STATE + refund cross-post токенов
  ▼                                    (оригинальный пост уже опубликован — E52)
CLEAR_STATE
```

**Inline handlers:** Аналогично ArticlePipelineFSM — SocialPipeline НЕ вызывает существующие FSM (ConnectTelegramFSM, ConnectVKFSM, etc.) как sub-flows. Реализует inline states внутри SocialPipelineFSM, переиспользуя Service Layer (ConnectionService, KeywordService, CategoryRepository).

**Кросс-постинг:** После публикации оригинального поста — предложение адаптировать для других подключённых платформ. AI-адаптация: `task_type="cross_post"`, стоимость `ceil(adapted_word_count / 100) * 10` токенов, images = 0. Обязательный ревью перед публикацией (E52).
