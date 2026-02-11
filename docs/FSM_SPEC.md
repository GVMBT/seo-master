# SEO Master Bot v2 — FSM-спецификация

> Связанные документы: [ARCHITECTURE.md](ARCHITECTURE.md) (техническая архитектура), [API_CONTRACTS.md](API_CONTRACTS.md) (API-контракты), [EDGE_CASES.md](EDGE_CASES.md) (обработка ошибок), [USER_FLOWS_AND_UI_MAP.md](USER_FLOWS_AND_UI_MAP.md) (экраны и навигация)

Все FSM-мастера используют Aiogram 3 StatesGroup с хранением в Redis (Upstash).

---

## 1. Определения StatesGroup

```python
# routers/projects/create.py
class ProjectCreate(StatesGroup):
    name = State()           # Шаг 1: название проекта
    company_name = State()   # Шаг 2: название компании
    specialization = State() # Шаг 3: специализация
    website_url = State()    # Шаг 4: URL сайта (пропускаемый)

# routers/categories/keywords.py
class KeywordGeneration(StatesGroup):
    products = State()       # Вопрос 1: товары/услуги
    geography = State()      # Вопрос 2: география
    quantity = State()       # Выбор количества (50/100/150/200)
    confirm = State()        # Подтверждение генерации

# routers/publishing/preview.py
class ArticlePublish(StatesGroup):
    confirm_cost = State()   # Подтверждение стоимости
    generating = State()     # Генерация (ожидание)
    preview = State()        # Предпросмотр: [Опубликовать/Перегенерировать/Отмена]
    publishing = State()     # Публикация в процессе (защита от двойного нажатия, E07)
    regenerating = State()   # Перегенерация (ожидание)

# Примечание: ArticlePublish используется ТОЛЬКО для WordPress (с Telegraph-превью).
# Для Telegram/VK/Pinterest используется SocialPostPublish (без Telegraph).

# routers/publishing/scheduler.py
class ScheduleSetup(StatesGroup):
    select_days = State()    # Выбор дней (множественный)
    select_count = State()   # Количество постов/день
    select_times = State()   # Выбор времени

# routers/platforms/connections.py
class ConnectWordPress(StatesGroup):
    url = State()            # URL сайта
    login = State()          # Логин WordPress
    password = State()       # Application Password

class ConnectTelegram(StatesGroup):
    channel = State()        # Ссылка на канал
    token = State()          # Токен бота

class ConnectVK(StatesGroup):
    token = State()          # VK-токен
    select_group = State()   # Выбор группы из списка

class ConnectPinterest(StatesGroup):
    oauth_callback = State() # Ожидание OAuth
    select_board = State()   # Выбор доски

# OAuth flow для Pinterest:
# 1. Бот отправляет кнопку-ссылку на {RAILWAY_PUBLIC_URL}/api/auth/pinterest?user_id={id}&nonce={nonce}
# 2. Сервер перенаправляет на Pinterest OAuth authorize URL
# 3. Pinterest callback → сервер сохраняет token в Redis (key: pinterest_auth:{nonce})
# 4. Сервер отправляет redirect на deep link: tg://resolve?domain=BOT&start=pinterest_auth_{nonce}
# 5. Бот получает /start pinterest_auth_{nonce} → извлекает token из Redis → FSM.select_board

# routers/categories/prices.py
class PriceInput(StatesGroup):
    choose_method = State()  # Текст или Excel?
    text_input = State()     # Ввод текста
    file_upload = State()    # Загрузка Excel

# routers/categories/reviews.py
class ReviewGeneration(StatesGroup):
    quantity = State()       # 3/5/10 отзывов
    confirm = State()        # Подтверждение

# routers/categories/manage.py
class DescriptionGenerate(StatesGroup):
    confirm = State()        # Подтверждение стоимости (20 токенов)
    review = State()         # Просмотр результата: [Сохранить/Перегенерировать/Отмена]

# routers/analysis.py
class CompetitorAnalysis(StatesGroup):
    url = State()            # Ввод URL конкурента
    confirm = State()        # Подтверждение стоимости (50 токенов)

# routers/categories/manage.py
class CategoryCreate(StatesGroup):
    name = State()           # Ввод названия категории (мин. 2 символа)

# routers/projects/create.py
class ProjectEdit(StatesGroup):
    field_value = State()    # Ввод нового значения поля (field_name в state.data)

# routers/publishing/quick.py
class SocialPostPublish(StatesGroup):
    confirm_cost = State()   # Подтверждение стоимости
    generating = State()     # Генерация (ожидание)
    review = State()         # Просмотр: [Опубликовать/Перегенерировать/Отмена]
    publishing = State()     # Публикация в процессе
    regenerating = State()   # Перегенерация (защита от двойного нажатия)

# routers/categories/keywords.py
class KeywordUpload(StatesGroup):
    file_upload = State()    # Загрузка TXT-файла с фразами

# routers/platforms/connections.py — дополнение
# Pinterest OAuth callback endpoint
# ConnectPinterest.oauth_callback: бот отправляет ссылку авторизации,
# пользователь переходит в браузер, после авторизации redirect на:
# {RAILWAY_PUBLIC_URL}/api/auth/pinterest/callback?state={user_id}_{nonce}
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
- Кнопка [Прервать] сохраняет прогресс для проекта (только ProjectCreate)

---

## 3. Валидация ввода на каждом шаге

| FSM | Шаг | Ожидаемый ввод | Валидация | При ошибке |
|-----|-----|----------------|-----------|------------|
| ProjectCreate | name | Текст | 2-100 символов, без спецсимволов | "Введите название от 2 до 100 символов" |
| ProjectCreate | company_name | Текст | 2-200 символов | Аналогично |
| ProjectCreate | specialization | Текст | 5-500 символов | "Опишите подробнее (мин. 5 символов)" |
| ProjectCreate | website_url | Текст или "Пропустить" | URL-формат (http/https) или кнопка [Пропустить] | "Введите корректный URL или нажмите Пропустить" |
| ConnectWordPress | url | Текст | URL с http/https, проверка доступности | "Сайт недоступен. Проверьте URL" |
| ConnectWordPress | login | Текст | 1-100 символов | "Введите логин WordPress" |
| ConnectWordPress | password | Текст | Формат App Password (xxxx xxxx xxxx xxxx) | "Введите Application Password из WordPress" |
| ConnectTelegram | channel | Текст | Формат @channel или t.me/channel | "Введите ссылку на канал (@name или t.me/name)" |
| ConnectTelegram | token | Текст | Формат bot_id:hash (проверка через getMe) | "Токен невалиден. Получите токен у @BotFather" |
| KeywordGeneration | products | Текст | 3-1000 символов | "Опишите товары/услуги подробнее" |
| KeywordGeneration | geography | Текст | 2-200 символов | "Укажите географию работы" |
| KeywordGeneration | quantity | Кнопка | Только 50/100/150/200 | Показать кнопки повторно |
| ScheduleSetup | select_days | Кнопки (множ. выбор) | Мин. 1 день | "Выберите хотя бы один день" |
| PriceInput | text_input | Текст | Формат "Название — Цена" per line, мин. 1 строка | "Формат: Товар — Цена (каждый с новой строки)" |
| DescriptionGenerate | confirm | Кнопка | Только [Да, сгенерировать] / [Отмена] | Показать кнопки повторно |
| CompetitorAnalysis | url | Текст | URL-формат (http/https), проверка доступности | "Введите корректный URL сайта конкурента" |
| CategoryCreate | name | Текст | 2-100 символов, без спецсимволов | "Введите название от 2 до 100 символов" |
| ProjectEdit | field_value | Текст/URL | Зависит от поля (state.data["field_name"]): URL для website_url, email для company_email, phone для company_phone, 2-500 символов для текстовых | "Некорректный формат для поля {field_name}" |
| SocialPostPublish | confirm_cost | Кнопка | Только [Да, сгенерировать] / [Отмена] | Показать кнопки повторно |
| KeywordUpload | file_upload | Документ | .txt файл, UTF-8, макс. 1 МБ, одна фраза на строку, макс. 500 фраз | "Загрузите TXT-файл (UTF-8), одна фраза на строку. Макс. 500 фраз, 1 МБ" |
| PriceInput | file_upload | Документ | .xlsx файл, макс. 1000 строк, 5 МБ. Колонки: A=Название, B=Цена, C=Описание (опц.) | "Загрузите Excel (.xlsx), макс. 1000 строк, 5 МБ" |
| ScheduleSetup | select_days | Кнопки (множ. выбор) | Мин. 1 день выбран | "Выберите хотя бы один день" |
| ScheduleSetup | select_count | Кнопка | 1-5 | Показать кнопки повторно |
| ScheduleSetup | select_times | Кнопки (множ. выбор) | Ровно posts_per_day штук (из предыдущего шага) | "Выберите ровно {n} временных слотов" |
| ConnectTelegram | channel | Текст | Формат @channel, t.me/channel, или -100XXXXXXXXXX (числовой ID) | "Введите @channel, t.me/channel или числовой ID" |

---

## 4. Обработка невалидного ввода

- Фото/видео/стикер вместо текста → "Пожалуйста, отправьте текстовое сообщение"
- Команда /start во время FSM → сброс FSM, переход в главное меню
- Любая другая команда → "Вы в процессе {действие}. Отправьте /cancel для отмены"

---

## 5. Переходы между состояниями (transition diagrams)

**Общая конвенция:** `/cancel` из любого состояния → `CLEAR_STATE` + возврат в меню. Таймаут 30 мин → `CLEAR_STATE` + "Сессия истекла".

### ArticlePublish (WordPress)

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

### SocialPostPublish (Telegram / VK / Pinterest)

```
[Callback: qp:{project}:{cat}:{platform}]
  │
  ▼
confirm_cost ──[Да]──► generating ──[OK]──► review
  │                       │                  │
  [Отмена]              [Ошибка]            ├──[Опубликовать]──► publishing ──► CLEAR_STATE
  ▼                       ▼                  ├──[Перегенерировать]──► regenerating ──[OK]──► review
CLEAR_STATE         CLEAR_STATE              [Отмена]──► CLEAR_STATE
                    + возврат токенов
```

### ProjectCreate (быстрый старт)

```
name ──[валидный текст]──► company_name ──[валидный текст]──► specialization ──[валидный текст]──► website_url ──[URL или Пропустить]──► CLEAR_STATE + сохранение
  │                           │                                  │                                   │
  [невалидный]               [невалидный]                      [невалидный]                        [невалидный URL]
  └── повтор запроса          └── повтор запроса                └── повтор запроса                   └── повтор запроса
```

### ScheduleSetup

```
select_days ──[мин. 1 день]──► select_count ──[1-5]──► select_times ──[ровно N слотов]──► CLEAR_STATE + сохранение + создание QStash
```

### ConnectWordPress / ConnectTelegram / ConnectVK

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

### ConnectPinterest (OAuth)

```
oauth_callback ──[отправка ссылки авторизации]──► (ожидание /start pinterest_auth_{nonce}) ──► select_board ──► CLEAR_STATE + сохранение
```
