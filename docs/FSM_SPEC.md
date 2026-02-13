# SEO Master Bot v2 — FSM-спецификация

> Связанные документы: [ARCHITECTURE.md](ARCHITECTURE.md) (техническая архитектура), [API_CONTRACTS.md](API_CONTRACTS.md) (API-контракты), [EDGE_CASES.md](EDGE_CASES.md) (обработка ошибок), [USER_FLOWS_AND_UI_MAP.md](USER_FLOWS_AND_UI_MAP.md) (экраны и навигация)

Все FSM-мастера используют Aiogram 3 StatesGroup с хранением в Redis (Upstash).

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
    confirm = State()        # Подтверждение

# routers/categories/manage.py
class DescriptionGenerateFSM(StatesGroup):
    confirm = State()        # Подтверждение стоимости (20 токенов)
    review = State()         # Просмотр результата: [Сохранить/Перегенерировать/Отмена]

# routers/analysis.py
class CompetitorAnalysisFSM(StatesGroup):
    url = State()            # Ввод URL конкурента
    confirm = State()        # Подтверждение стоимости (50 токенов)

# routers/categories/manage.py
class CategoryCreateFSM(StatesGroup):
    name = State()           # Ввод названия категории (мин. 2 символа)

# routers/projects/create.py
class ProjectEditFSM(StatesGroup):
    field_value = State()    # Ввод нового значения поля (field_name в state.data)

# routers/publishing/quick.py
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
- При таймауте/перезапуске → превью остаётся в БД, cleanup-задача вернёт токены через 24ч

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
[Callback: quick:cat:{cat_id}:{platform}:{conn_id}]
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

**Пост-обработка загруженных фраз:**
1. Парсирование TXT: одна фраза на строку, валидация (не пусто, ≤100 символов/фраза)
2. DataForSEO `enrich_keywords()` → volume, difficulty, CPC
3. AI кластеризация (keywords_cluster.yaml с raw_keywords = загруженные фразы)
4. Сохранение в `categories.keywords` в кластерном формате
5. При E03 на `enriching` → skip `clustering`, сохранить в legacy-формате (плоский список без volume/difficulty), предупредить: "Данные без объёмов поиска"
6. При AI error на `clustering` → сохранить как один кластер (все фразы, cluster_name = category_name), volume/difficulty из enrichment
