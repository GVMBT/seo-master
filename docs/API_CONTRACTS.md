# SEO Master Bot v2 — API-контракты и интеграции

> Связанные документы: [PRD.md](PRD.md) (продуктовые требования), [ARCHITECTURE.md](ARCHITECTURE.md) (техническая архитектура), [FSM_SPEC.md](FSM_SPEC.md) (FSM-состояния), [EDGE_CASES.md](EDGE_CASES.md) (обработка ошибок), [USER_FLOWS_AND_UI_MAP.md](USER_FLOWS_AND_UI_MAP.md) (экраны и навигация)

---

## 1. QStash webhook контракт и идемпотентность

### 1.1 Эндпоинты

| Эндпоинт | Метод | Вызывающий | Назначение |
|----------|-------|-----------|------------|
| `/api/publish` | POST | QStash (по расписанию) | Автопубликация контента |
| `/api/cleanup` | POST | QStash (ежедневно) | Очистка expired превью, старых логов |
| `/api/notify` | POST | QStash (по расписанию) | Уведомления о низком балансе, еженедельный дайджест |

### 1.2 Формат запроса `/api/publish`

```json
{
  "schedule_id": 42,
  "category_id": 15,
  "connection_id": 7,
  "platform_type": "wordpress",
  "user_id": 12345678,
  "project_id": 3,
  "idempotency_key": "pub_42_2026-02-11T10:00:00Z"
}
```

### 1.3 Верификация подписи QStash

```python
from upstash_qstash import Receiver

receiver = Receiver(
    current_signing_key=os.environ["QSTASH_CURRENT_SIGNING_KEY"],
    next_signing_key=os.environ["QSTASH_NEXT_SIGNING_KEY"],
)

# В каждом эндпоинте:
is_valid = receiver.verify(
    body=request.body,
    signature=request.headers["Upstash-Signature"],
    url="https://our-bot.railway.app/api/publish"
)
if not is_valid:
    return Response(status_code=401)
```

### 1.4 Идемпотентность (защита от двойного списания)

```python
# Redis-блокировка перед обработкой:
lock_key = f"publish_lock:{idempotency_key}"
acquired = await redis.set(lock_key, "1", nx=True, ex=300)  # 5 мин TTL

if not acquired:
    return Response(status_code=200, body="Already processing")  # QStash не повторит

try:
    result = await execute_publish(...)
    await redis.set(lock_key, "done", ex=300)  # Сохранить результат до истечения TTL
except Exception:
    await redis.delete(lock_key)  # Удалить только при ошибке (разрешить повтор)
    raise
```

### 1.5 Retry-политика QStash

- QStash автоматически повторяет при HTTP 5xx (не при 2xx/4xx)
- Максимум 3 повтора с exponential backoff
- При 3 неудачах → пометить расписание как `status: error`, уведомить пользователя
- Эндпоинт ДОЛЖЕН возвращать 200 даже при бизнес-ошибке (иначе QStash повторит)
- Уведомления о результатах публикации отправляются только если `users.notify_publications = TRUE`

> Уведомления пользователя о пропущенных автопубликациях → см. [EDGE_CASES.md](EDGE_CASES.md)

### 1.6 Контракт `/api/cleanup`

```json
{
  "action": "cleanup",
  "idempotency_key": "cleanup_2026-02-11"
}
```

**Действия:**
1. `article_previews` WHERE `status = 'draft' AND expires_at < now()` → для каждой записи:
   - Установить `status = 'expired'`
   - Удалить Telegraph-страницу (Telegraph API `editPage` → пустой контент, или игнорировать ошибку)
   - Вернуть токены: `UPDATE users SET balance = balance + ap.tokens_charged WHERE id = ap.user_id`
   - Записать возврат: `INSERT INTO token_expenses (user_id, amount, operation_type) VALUES (ap.user_id, +ap.tokens_charged, 'refund')`
   - Отправить уведомление (если `notify_publications = TRUE`): "Превью статьи «{keyword}» истекло. Токены возвращены: +{tokens_charged}. [Сгенерировать заново]"
2. `publication_logs` WHERE `created_at < now() - INTERVAL '90 days'` → архивировать/удалить (настраиваемый период)
3. Логировать количество очищенных записей

### 1.7 Контракт `/api/notify`

```json
{
  "action": "notify",
  "type": "low_balance | weekly_digest | reactivation",
  "idempotency_key": "notify_low_2026-02-11"
}
```

**Типы уведомлений:**
| Тип | Целевая аудитория | Условие | Текст |
|-----|------------------|---------|-------|
| `low_balance` | users WHERE balance < 100 AND notify_balance = TRUE | Ежедневно 10:00 MSK | "Баланс: {balance} токенов. Этого хватит на ~{estimate}. [Пополнить]" |
| `weekly_digest` | users WHERE notify_news = TRUE AND last_activity > now() - '30 days' | Еженедельно пн 09:00 | "За неделю: {pubs} публикаций, {tokens} токенов. Топ-статья: {best_url}" |
| `reactivation` | users WHERE last_activity < now() - '14 days' | Еженедельно | "Давно не виделись! Ваши расписания на паузе. [Вернуться в бота]" |

### 1.8 Создание расписания в QStash (бот → QStash)

Секции 1.1-1.7 описывают что QStash отправляет боту. Эта секция — как бот создаёт расписание.

```python
from upstash_qstash import QStash

qstash = QStash(token=os.environ["QSTASH_TOKEN"])

# Маппинг schedule_days + schedule_times + timezone → cron + N расписаний
# Одно QStash-расписание = одно время публикации (cron не поддерживает массив времён)

def create_schedules_for_platform(schedule: PlatformSchedule) -> list[str]:
    """Создаёт N QStash-расписаний (по одному на каждое время).
    Возвращает список ID для сохранения в qstash_schedule_ids."""
    
    schedule_ids = []
    day_map = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 0}
    cron_days = ",".join(str(day_map[d]) for d in schedule.schedule_days)
    
    for time_slot in schedule.schedule_times:   # ["09:00", "18:00"]
        hour, minute = time_slot.split(":")
        # cron: MIN HOUR * * DOW (в timezone проекта)
        cron = f"{minute} {hour} * * {cron_days}"
        
        result = qstash.schedules.create(
            destination=f"{os.environ['RAILWAY_PUBLIC_URL']}/api/publish",
            cron=cron,
            body=json.dumps({
                "schedule_id": schedule.id,
                "category_id": schedule.category_id,
                "connection_id": schedule.connection_id,
                "platform_type": schedule.platform_type,
                "user_id": schedule.user_id,
                "project_id": schedule.project_id,
                "idempotency_key": f"pub_{schedule.id}_{time_slot}_{{timestamp}}"
            }),
            headers={"Content-Type": "application/json"},
        )
        schedule_ids.append(result.schedule_id)
    
    return schedule_ids

# Сохранение: UPDATE platform_schedules SET qstash_schedule_ids = schedule_ids
# При удалении: for sid in qstash_schedule_ids: qstash.schedules.delete(sid)
```

**Обновление расписания:**
1. Удалить все старые QStash-расписания (`qstash.schedules.delete`)
2. Создать новые
3. Обновить `qstash_schedule_ids` в БД

**Включение/выключение:** При `enabled=False` — удалить QStash-расписания, очистить `qstash_schedule_ids`. При `enabled=True` — создать заново.

---

## 2. Telegram Stars: полный платёжный flow

### 2.1 Разовая покупка

```
1. Пользователь нажимает [Starter: 3000 руб] → бот вызывает sendInvoice:
   {
     title: "Пакет Starter — 3500 токенов",
     description: "3000 + 500 бонусных токенов",
     payload: "purchase:starter:user_12345678",
     currency: "XTR",
     prices: [{label: "Starter", amount: 195}],  // 195 Stars
     provider_token: ""
   }

2. Telegram показывает нативное окно оплаты → пользователь подтверждает

3. Бот получает pre_checkout_query:
   → Проверить payload (формат, user_id совпадает)
   → answer_pre_checkout_query(ok=True)
   → Таймаут: если successful_payment не пришёл за 60 сек — НЕ начислять

4. Бот получает successful_payment:
   → Создать запись в payments (status: completed)
   → Начислить токены: UPDATE users SET balance = balance + 3500
   → Создать запись в token_expenses (operation: purchase)
   → Начислить реферальный бонус (если есть referrer_id): 10% от 3000 руб = 300 токенов
   → Отправить подтверждение: "Зачислено 3500 токенов! Баланс: {new_balance}"
```

### 2.2 Подписка (30 дней)

```
1. Бот вызывает createInvoiceLink с subscription_period=2592000 (30 дней в секундах)
   Через Bot API:
   bot.create_invoice_link(
       title="Подписка Pro — 7200 токенов/мес",
       description="Автопродление каждые 30 дней",
       payload=f"sub:pro:user_{user_id}",
       currency="XTR",
       prices=[LabeledPrice(label="Pro", amount=390)],
       subscription_period=2592000  # 30 дней
   )

2. При автопродлении Stars списываются автоматически:
   → Бот получает successful_payment с is_recurring=True
   → Начислить токены + уведомить
   
   Поля SuccessfulPayment для подписки:
   - is_recurring: True (автопродление)
   - is_first_recurring: True (первый платёж) / False (продление)
   - subscription_expiration_date: int (Unix timestamp окончания текущего периода)

3. Если у пользователя недостаточно Stars:
   → Подписка приостанавливается
   → Бот получает событие → уведомить "Подписка приостановлена, пополните Stars"

4. Отмена подписки:
   → Пользователь: через настройки Telegram
   → Бот: 
   Управление подпиской (бот):
   bot.edit_user_star_subscription(
       user_id=user_id,
       telegram_payment_charge_id=charge_id,
       is_canceled=True   # True = отменить продление, False = возобновить
   )
```

### 2.3 Обработка ошибок платежей

| Ситуация | Действие |
|----------|----------|
| pre_checkout пришёл, successful_payment — нет (таймаут 60с) | Не начислять, логировать. Telegram сам отменит |
| Двойной successful_payment (одинаковый charge_id) | Проверить по telegram_payment_charge_id в payments. Если есть — игнорировать |
| Запрос refund | `bot.refund_star_payment(user_id, charge_id)` → списать токены → обновить payments status=refunded |
| Refund при уже потраченных токенах | Списать сколько есть, баланс может уйти в минус → пользователь видит отрицательный баланс |

**Политика отрицательного баланса:**
- Генерация контента ЗАБЛОКИРОВАНА при balance < 0
- Отрицательный баланс автоматически погашается из следующей покупки
- Уведомление: "Ваш баланс отрицателен ({balance} токенов) из-за возврата средств. Пополните баланс для продолжения работы. [Пополнить]"

### 2.4 ЮKassa (альтернативный провайдер)

**Endpoint:** `/api/yookassa/webhook` (POST)

**Регистрация вебхука:**
```bash
curl https://api.yookassa.ru/v3/webhooks \
  -X POST \
  -u '<YOOKASSA_SHOP_ID>:<YOOKASSA_SECRET_KEY>' \
  -H 'Idempotence-Key: <unique_key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "event": "payment.succeeded",
    "url": "https://our-bot.railway.app/api/yookassa/webhook"
  }'
```
Повторить для `payment.canceled` и `refund.succeeded`.

**Формат уведомления:**
```json
{
  "type": "notification",
  "event": "payment.succeeded",
  "object": {
    "id": "2d6d597-000f-5000-9000-145f6df21d6f",
    "status": "succeeded",
    "paid": true,
    "amount": {"value": "3000.00", "currency": "RUB"},
    "metadata": {
      "user_id": "12345678",
      "package_name": "starter",
      "tokens_amount": "3500"
    },
    "payment_method": {"type": "bank_card"},
    "created_at": "2026-02-11T14:27:54.691Z"
  }
}
```

**Верификация запроса:**
```python
YOOKASSA_IP_WHITELIST = [
    "185.71.76.0/27", "185.71.77.0/27",
    "77.75.153.0/25", "77.75.156.11", "77.75.156.35",
    "77.75.154.128/25", "2a02:5180::/32",
]

async def verify_yookassa_request(request: Request) -> bool:
    client_ip = request.client.host
    return any(ip_address(client_ip) in ip_network(net) for net in YOOKASSA_IP_WHITELIST)
```

**Идемпотентность:** По `object.id` (yookassa_payment_id) — проверить в таблице `payments`.

**Flow создания платежа:**
```python
from yookassa import Payment

payment = Payment.create({
    "amount": {"value": "3000.00", "currency": "RUB"},
    "confirmation": {
        "type": "redirect",
        "return_url": "https://t.me/SEOMasterBot"
    },
    "metadata": {"user_id": user_id, "package_name": "starter", "tokens_amount": 3500},
    "description": "Пакет Starter — 3500 токенов"
})
# Отправить пользователю payment.confirmation.confirmation_url
```

**Обработка событий:**
| Событие | Действие |
|---------|----------|
| `payment.succeeded` | Начислить токены, записать в payments (status: completed), реферальный бонус |
| `payment.canceled` | Записать в payments (status: failed), уведомить пользователя |
| `refund.succeeded` | Списать токены, обновить payments (status: refunded), баланс может уйти в минус |

**Ответ:** HTTP 200 (тело и заголовки игнорируются). Если не 200 — ЮKassa повторяет в течение 24 часов.

**Требования:** HTTPS, TLS 1.2+, порт 443 или 8443.

### 2.5 ЮKassa подписки (рекуррентные платежи)

ЮKassa автоплатежи = сохранение способа оплаты + периодическое списание по `payment_method_id`.

**Шаг 1: Первый платёж с сохранением метода**
```python
# Первый платёж подписки — пользователь вводит данные карты
payment = Payment.create({
    "amount": {"value": "6000.00", "currency": "RUB"},
    "confirmation": {"type": "redirect", "return_url": "https://t.me/SEOMasterBot"},
    "save_payment_method": True,  # Сохранить карту для автоплатежей
    "metadata": {
        "user_id": user_id,
        "package_name": "pro",
        "tokens_amount": 7200,
        "is_subscription": True,
    },
    "description": "Подписка Pro — 7200 токенов/мес",
})
```

**Шаг 2: При `payment.succeeded` — сохранить payment_method_id**
```python
# В обработчике вебхука payment.succeeded
if webhook.object.metadata.get("is_subscription"):
    await db.execute("""
        UPDATE payments SET
            subscription_status = 'active',
            subscription_expires_at = now() + interval '30 days',
            yookassa_payment_method_id = :pm_id
        WHERE yookassa_payment_id = :pay_id
    """, pm_id=webhook.object.payment_method.id, pay_id=webhook.object.id)
```

**Шаг 3: Автосписание (QStash cron, раз в 30 дней)**
```python
# Эндпоинт /api/yookassa/renew (вызывается QStash)
async def renew_subscription(user_id: int, payment_method_id: str, package: str):
    payment = Payment.create({
        "amount": {"value": PACKAGE_PRICES[package], "currency": "RUB"},
        "payment_method_id": payment_method_id,  # Без подтверждения пользователя
        "metadata": {
            "user_id": user_id,
            "package_name": package,
            "tokens_amount": PACKAGE_TOKENS[package],
            "is_renewal": True,
        },
        "description": f"Продление подписки {package}",
    })
    # Результат придёт через вебхук payment.succeeded / payment.canceled
```

**Шаг 4: Отмена подписки**
```python
# Удалить QStash-расписание автопродления
# Обновить payments.subscription_status = 'cancelled'
# Подписка действует до subscription_expires_at
# НЕ вызываем YooKassa API — просто перестаём создавать платежи
```

**Ошибки автосписания:** Если `payment.canceled` при автопродлении → уведомить пользователя "Не удалось продлить подписку. Проверьте карту." Подписка остаётся active до `subscription_expires_at`, затем → expired.

> **Требование ЮKassa:** Уведомить пользователя за 24ч до списания. Реализация: QStash cron за 24ч до `subscription_expires_at` → Telegram-уведомление.

**Колонка для хранения:** добавить `yookassa_payment_method_id VARCHAR(255)` в таблицу `payments`.

---

## 3. Контракты сервисов

### 3.1 AI Orchestrator (OpenRouter SDK)

#### Инициализация клиента

```python
from openrouter import OpenRouter

# Singleton — создаётся один раз при старте бота
openrouter_client = OpenRouter(api_key=os.environ["OPENROUTER_API_KEY"])

# Альтернатива: через OpenAI SDK (для совместимости)
from openai import AsyncOpenAI
openai_client = AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
    default_headers={"HTTP-Referer": os.environ["RAILWAY_PUBLIC_URL"]},
)
```

> **Выбор SDK:** OpenRouter SDK (beta) или OpenAI SDK — оба работают. OpenAI SDK стабильнее, OpenRouter SDK даёт нативный доступ к `provider`, `models`, `plugins`. Решение — при разработке.

#### Контракты данных

```python
@dataclass
class GenerationRequest:
    task: Literal["article", "social_post", "keywords", "review", "image", "description", "competitor_analysis"]
    prompt_version: str          # "v5", "v3" — ссылка на prompt_versions
    context: GenerationContext   # Типизированный контекст (см. ниже)
    user_id: int                 # Для rate limiting и логирования
    max_retries: int = 2         # Количество попыток с fallback-моделью
    stream: bool = False         # Стриминг (только для article)

@dataclass
class GenerationResult:
    content: str | dict          # Текст или структурированный результат
    model_used: str              # Реальный model ID из OpenRouter, напр. "anthropic/claude-sonnet-4.5"
    input_tokens: int            # Токены LLM (входящие)
    output_tokens: int           # Токены LLM (исходящие)
    cost_usd: float              # Себестоимость запроса
    generation_time_ms: int
    prompt_version: str
    fallback_used: bool          # True если сработала резервная модель

@dataclass
class GenerationContext:
    company_name: str
    specialization: str
    category_name: str
    keyword: str
    language: str = "ru"
    # Опциональные (заполняются при наличии данных)
    prices_excerpt: str | None = None
    advantages: str | None = None
    city: str | None = None
    internal_links: list[str] | None = None
    branding_colors: dict | None = None
    serper_data: dict | None = None
    competitor_summary: str | None = None
    image_settings: dict | None = None
    text_settings: dict | None = None
    user_media_urls: list[str] | None = None   # URLs из categories.media (F43: медиа как контекст для AI)

class AIOrchestrator:
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def generate_stream(self, request: GenerationRequest) -> AsyncIterator[str]: ...
    async def heal_response(self, raw: str, expected_format: str) -> str: ...
```

#### Model Fallbacks (цепочка моделей)

OpenRouter поддерживает нативные fallbacks через параметр `models`. При ошибке провайдера (429, 5xx, модерация, контекст) — автоматический переход к следующей модели. Оплата только за модель, которая ответила.

```python
# Конфигурация цепочек по задачам
MODEL_CHAINS = {
    "article":            ["anthropic/claude-sonnet-4.5", "openai/gpt-5.2", "deepseek/deepseek-v3.2"],
    "social_post":        ["deepseek/deepseek-v3.2", "anthropic/claude-sonnet-4.5"],
    "keywords":           ["deepseek/deepseek-v3.2", "openai/gpt-5.2"],
    "review":             ["deepseek/deepseek-v3.2", "anthropic/claude-sonnet-4.5"],
    "description":        ["deepseek/deepseek-v3.2", "anthropic/claude-sonnet-4.5"],
    "competitor_analysis": ["openai/gpt-5.2", "anthropic/claude-sonnet-4.5"],
    "image":              ["google/gemini-3-pro-image-preview", "google/gemini-2.5-flash-image"],
}

# Использование — один запрос, OpenRouter сам делает fallback
response = await openai_client.chat.completions.create(
    model=MODEL_CHAINS[task][0],           # Основная модель
    messages=messages,
    extra_body={
        "models": MODEL_CHAINS[task],      # Цепочка fallback (включая основную)
    },
    timeout=45,
)
# response.model — модель, которая реально ответила
```

Триггеры автоматического fallback:
- Провайдер вернул ошибку (5xx, rate limit)
- Контекст превысил лимит модели
- Модерация/фильтрация контента
- Таймаут провайдера

#### Provider Routing (маршрутизация провайдеров)

```python
# Для бюджетных задач — приоритет по цене
response = await openai_client.chat.completions.create(
    model="deepseek/deepseek-v3.2",
    messages=messages,
    extra_body={
        "models": MODEL_CHAINS["social_post"],
        "provider": {
            "sort": "price",                   # Приоритет: минимальная цена
            "allow_fallbacks": True,           # Разрешить fallback на другие провайдеры
            "require_parameters": True,        # Только провайдеры с поддержкой всех параметров
            "data_collection": "deny",         # Запрет хранения данных провайдером
        },
    },
)
```

Доступные стратегии сортировки:
| Значение `sort` | Поведение |
|-----------------|-----------|
| `"price"` | Минимальная стоимость (для budget-задач) |
| `"throughput"` | Максимальная скорость tok/sec (для стриминга статей) |
| `"latency"` | Минимальная задержка первого токена (для UX) |
| не указан | Балансировка по цене с учётом аптайма (default) |

#### Structured Outputs (JSON Schema)

Для задач, возвращающих структурированные данные (keywords, social posts, articles), вместо свободного JSON используем JSON Schema. Гарантирует типобезопасный ответ без необходимости heal_response.

```python
# Пример: генерация ключевых фраз со строгой схемой
response = await openai_client.chat.completions.create(
    model="deepseek/deepseek-v3.2",
    messages=messages,
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "keywords_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "keywords": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "phrase": {"type": "string"},
                                "intent": {"type": "string", "enum": ["commercial", "informational"]},
                            },
                            "required": ["phrase", "intent"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["keywords"],
                "additionalProperties": False,
            },
        },
    },
    extra_body={
        "models": MODEL_CHAINS["keywords"],
        "plugins": [{"id": "response-healing"}],  # Авто-починка как fallback
    },
)
```

Когда использовать:
| Задача | `response_format` | `plugins: response-healing` |
|--------|-------------------|----------------------------|
| keywords | JSON Schema (strict) | Да (fallback) |
| social_post | JSON Schema (strict) | Да |
| article | JSON Schema (strict) | Да |
| review | JSON Schema (strict) | Да |
| description | Нет (plain text) | Нет |
| image | Нет (modalities) | Нет |

> **Response Healing plugin** (OpenRouter native) — автоматически чинит сломанный JSON (пропущенные скобки, trailing commas, markdown-обёртки). Работает только для non-streaming запросов. Для streaming — используем свой heal_response.

#### Пайплайн heal_response (для streaming и fallback)

1. Попытка `json.loads(raw)` — если OK, вернуть
2. Regex-фиксы: удаление trailing comma, закрытие незакрытых скобок, удаление markdown-обёрток (```json ... ```)
3. Повторная попытка `json.loads` — если OK, вернуть
4. Отправка на бюджетную модель с промптом: "Исправь этот JSON: {raw[:2000]}"
5. Если все попытки провалились → GenerationError, возврат токенов

`expected_format`: Literal["json", "plain_text"] — определяет нужна ли JSON-валидация.

#### Prompt Caching (оптимизация стоимости)

OpenRouter пробрасывает prompt caching от провайдеров. Для задач с повторяющимися system-промптами это даёт экономию 50-75%.

| Провайдер | Тип | Настройка | Экономия чтения |
|-----------|-----|-----------|-----------------|
| OpenAI | Автоматический | Не нужна (≥1024 tokens в prompt) | 50-75% |
| Anthropic | Ручной | `cache_control` breakpoint в system message | 75-90% (TTL 5 мин) |
| DeepSeek | Автоматический | Не нужна | ~50% |
| Google Gemini | Автоматический | Не нужна (Gemini 2.5+) | ~50% |

Для Anthropic-моделей (Claude) — добавляем `cache_control` в system message:
```python
messages = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": rendered_system_prompt,   # ~500-2000 токенов (повторяется)
                "cache_control": {"type": "ephemeral"},  # TTL 5 мин
            }
        ],
    },
    {"role": "user", "content": rendered_user_prompt},
]
```

При автопубликации (QStash) одна категория генерирует несколько постов подряд с одинаковым system-промптом → кеш попадает, экономия ~75% на input tokens.

#### Стриминг (SSE)

```python
stream = await openai_client.chat.completions.create(
    model="anthropic/claude-sonnet-4.5",
    messages=messages,
    stream=True,
    extra_body={
        "models": MODEL_CHAINS["article"],
        "provider": {"sort": "throughput"},   # Максимальная скорость для стриминга
    },
)

async for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        accumulated += delta
    # chunk.usage — только в финальном чанке (token counts)
```

Формат SSE от OpenRouter: `data: {json}\n\n`, завершение `data: [DONE]`.
Keepalive-комментарии (`: OPENROUTER PROCESSING`) — игнорировать.
Ошибки mid-stream: `finish_reason: "error"` в чанке + поле `error`.

**Стриминг в Telegram (F34):**
Telegram не поддерживает нативный стриминг. Реализация через `editMessageText`:
1. Создать сообщение: "Генерирую статью..."
2. Каждые 1.5 секунды: `editMessageText` с накопленным текстом
3. Обрезать до первого завершённого предложения (не разрывать на полуслове)
4. Telegram rate limit: ~30 edits/min/chat — интервал 1.5с обеспечивает запас
5. По завершении: удалить стриминг-сообщение, отправить Telegraph-превью
6. Для коротких генераций (<10с): пропустить стриминг, показать только прогресс-бар

### 3.2 BasePublisher

```python
@dataclass
class PublishRequest:
    connection: PlatformConnection   # Из БД (расшифрованные credentials)
    content: str                     # HTML или текст
    content_type: Literal["html", "telegram_html", "plain_text", "pin_text"]
    title: str | None                # Для WordPress
    images: list[bytes]              # Сгенерированные изображения
    category: Category               # Для контекста (keywords, media и т.д.)
    metadata: dict                   # platform-specific (wp_tags, pin_board и т.д.)

@dataclass
class PublishResult:
    success: bool
    post_url: str | None
    platform_post_id: str | None     # ID поста на платформе
    error: str | None

class BasePublisher(ABC):
    @abstractmethod
    async def validate_connection(self, connection: PlatformConnection) -> bool: ...

    @abstractmethod
    async def publish(self, request: PublishRequest) -> PublishResult: ...

    @abstractmethod
    async def delete_post(self, connection: PlatformConnection, post_id: str) -> bool: ...
```

**Реализации:** `WordPressPublisher`, `TelegramPublisher`, `VKPublisher`, `PinterestPublisher`.

### 3.3 WordPressPublisher — WP REST API

```python
class WordPressPublisher(BasePublisher):
    """WP REST API v2. Авторизация: Application Password (Basic Auth)."""

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials  # {"url", "login", "app_password"}
        base = creds["url"].rstrip("/") + "/wp-json/wp/v2"
        auth = httpx.BasicAuth(creds["login"], creds["app_password"])

        async with httpx.AsyncClient(auth=auth, timeout=30) as client:
            # 1. Загрузить изображения → получить attachment IDs
            attachment_ids = []
            for i, img_bytes in enumerate(request.images):
                resp = await client.post(
                    f"{base}/media",
                    content=img_bytes,
                    headers={
                        "Content-Type": "image/png",
                        "Content-Disposition": f'attachment; filename="image_{i}.png"',
                    },
                )
                resp.raise_for_status()
                attachment_ids.append(resp.json()["id"])

            # 2. Создать пост
            post_data = {
                "title": request.title,
                "content": request.content,             # HTML с inline-стилями (branding colors)
                "status": "publish",
                "featured_media": attachment_ids[0] if attachment_ids else 0,
                "meta": {
                    # Yoast SEO (если плагин установлен)
                    "_yoast_wpseo_title": request.metadata.get("seo_title", request.title),
                    "_yoast_wpseo_metadesc": request.metadata.get("seo_description", ""),
                    "_yoast_wpseo_focuskw": request.metadata.get("focus_keyword", ""),
                },
            }
            # Категория WP (если задана в metadata)
            if wp_cat := request.metadata.get("wp_category_id"):
                post_data["categories"] = [wp_cat]

            resp = await client.post(f"{base}/posts", json=post_data)
            resp.raise_for_status()
            post = resp.json()

        return PublishResult(
            success=True,
            post_url=post["link"],
            platform_post_id=str(post["id"]),
            error=None,
        )

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """GET /wp-json/wp/v2/users/me — проверка авторизации."""
        creds = connection.credentials
        base = creds["url"].rstrip("/") + "/wp-json/wp/v2"
        async with httpx.AsyncClient(auth=httpx.BasicAuth(creds["login"], creds["app_password"]), timeout=10) as client:
            resp = await client.get(f"{base}/users/me")
            return resp.status_code == 200
```

**Schema.org:** Инъекция через `<script type="application/ld+json">` в начало `content` (Article, FAQPage). Генерируется AI в промпте article_v5.yaml.

### 3.4 TelegramPublisher — Bot API

```python
class TelegramPublisher(BasePublisher):
    """Публикация через бот-публикатор пользователя (отдельный бот, добавленный админом в канал)."""

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials  # {"bot_token", "channel_id"}
        pub_bot = Bot(token=creds["bot_token"])

        try:
            if request.images:
                # Фото + подпись (Telegram limit: 1024 символов для caption)
                caption = request.content[:1024]
                if len(request.content) > 1024:
                    # Длинный пост: фото без подписи → отдельное текстовое сообщение
                    await pub_bot.send_photo(creds["channel_id"], BufferedInputFile(request.images[0], "post.png"))
                    msg = await pub_bot.send_message(creds["channel_id"], request.content[:4096], parse_mode="HTML")
                else:
                    msg = await pub_bot.send_photo(
                        creds["channel_id"],
                        BufferedInputFile(request.images[0], "post.png"),
                        caption=caption,
                        parse_mode="HTML",
                    )
            else:
                msg = await pub_bot.send_message(creds["channel_id"], request.content[:4096], parse_mode="HTML")

            return PublishResult(success=True, post_url=None, platform_post_id=str(msg.message_id), error=None)
        finally:
            await pub_bot.session.close()

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """getMe + проверка прав администратора канала."""
        pub_bot = Bot(token=connection.credentials["bot_token"])
        try:
            me = await pub_bot.get_me()
            member = await pub_bot.get_chat_member(connection.credentials["channel_id"], me.id)
            return member.status in ("administrator", "creator")
        except Exception:
            return False
        finally:
            await pub_bot.session.close()
```

### 3.5 VKPublisher — VK API

```python
class VKPublisher(BasePublisher):
    """VK API v5.199. Прямой токен (vkhost.github.io), одна группа per connection."""
    VK_API = "https://api.vk.com/method"
    VK_VERSION = "5.199"

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials  # {"access_token", "group_id"}
        token = creds["access_token"]
        owner_id = f"-{creds['group_id']}"  # минус для группы

        async with httpx.AsyncClient(timeout=30) as client:
            attachments = []
            # 1. Загрузить фото (если есть)
            if request.images:
                # Получить URL для загрузки
                resp = await client.get(f"{self.VK_API}/photos.getWallUploadServer", params={
                    "access_token": token, "group_id": creds["group_id"], "v": self.VK_VERSION,
                })
                upload_url = resp.json()["response"]["upload_url"]
                # Загрузить файл
                upload_resp = await client.post(upload_url, files={"photo": ("image.png", request.images[0], "image/png")})
                upload_data = upload_resp.json()
                # Сохранить фото
                save_resp = await client.get(f"{self.VK_API}/photos.saveWallPhoto", params={
                    "access_token": token, "group_id": creds["group_id"],
                    "photo": upload_data["photo"], "server": upload_data["server"], "hash": upload_data["hash"],
                    "v": self.VK_VERSION,
                })
                photo = save_resp.json()["response"][0]
                attachments.append(f"photo{photo['owner_id']}_{photo['id']}")

            # 2. Опубликовать пост
            resp = await client.get(f"{self.VK_API}/wall.post", params={
                "access_token": token, "owner_id": owner_id,
                "message": request.content[:16384],  # VK лимит
                "attachments": ",".join(attachments),
                "v": self.VK_VERSION,
            })
            post_id = resp.json()["response"]["post_id"]

        return PublishResult(
            success=True,
            post_url=f"https://vk.com/wall{owner_id}_{post_id}",
            platform_post_id=str(post_id),
            error=None,
        )

    async def validate_connection(self, connection: PlatformConnection) -> bool:
        """groups.getById — проверка токена и доступа к группе."""
        creds = connection.credentials
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{self.VK_API}/groups.getById", params={
                "access_token": creds["access_token"], "group_id": creds["group_id"], "v": self.VK_VERSION,
            })
            return "response" in resp.json()
```

### 3.6 PinterestPublisher — API v5

```python
class PinterestPublisher(BasePublisher):
    BASE_URL = "https://api.pinterest.com/v5"
    
    async def publish(self, request: PublishRequest) -> PublishResult:
        # 1. Загрузить изображение (base64)
        pin_data = {
            "board_id": request.metadata["board_id"],
            "title": request.metadata.get("pin_title", "")[:100],  # лимит 100 символов
            "description": request.content[:500],                    # лимит 500 символов
            "media_source": {
                "source_type": "image_base64",
                "content_type": "image/png",
                "data": base64.b64encode(request.images[0]).decode(),
            },
            "link": request.metadata.get("link"),                    # URL на сайт клиента
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/pins",
                json=pin_data,
                headers={"Authorization": f"Bearer {request.connection.credentials['access_token']}"},
            )
        # Ответ: {"id": "12345", "link": "https://pinterest.com/pin/..."}
```

**Refresh token:** Pinterest access_token истекает через 30 дней. Refresh:
```python
async def refresh_pinterest_token(connection: PlatformConnection) -> str:
    resp = await httpx.post(
        "https://api.pinterest.com/v5/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": connection.credentials["refresh_token"],
            "client_id": os.environ["PINTEREST_APP_ID"],
            "client_secret": os.environ["PINTEREST_APP_SECRET"],
        },
    )
    new_tokens = resp.json()  # {"access_token": "...", "refresh_token": "...", "expires_in": 2592000}
    # Обновить credentials в БД
    return new_tokens["access_token"]
```

Проверка при каждой публикации: если `expires_at < now() + 1 day` → refresh. При ошибке refresh → E08-аналог для Pinterest.

### 3.7 Валидация контента перед публикацией

```python
@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]           # ["Текст слишком короткий (490 символов, мин. 500)"]
    warnings: list[str]         # ["Нет FAQ-секции"]

PLACEHOLDER_PATTERNS = [
    r"\[INSERT",
    r"Lorem ipsum",
    r"\bTODO\b",
    r"\[YOUR",
    r"<placeholder>",
    r"\{заполнить\}",
    r"ПРИМЕР ТЕКСТА",
]

class ContentValidator:
    def validate(self, content: str, content_type: str, platform: str) -> ValidationResult:
        errors = []
        
        # Общие проверки
        if len(content) < 500:
            errors.append(f"Текст слишком короткий ({len(content)} символов, мин. 500)")
        
        for pattern in PLACEHOLDER_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                errors.append(f"Обнаружен placeholder-текст: {pattern}")
        
        # WordPress-специфичные
        if platform == "wordpress" and content_type == "article":
            if not re.search(r"<h1[^>]*>", content):
                errors.append("Отсутствует H1-заголовок")
            if not re.search(r"<p[^>]*>.{50,}", content):
                errors.append("Нет абзацев связного текста (мин. 50 символов)")
        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=[])
```

При частичном провале (например, H1 есть, но длина 490) — все ошибки собираются в список, валидация не проходит.

### 3.8 Быстрая публикация (F42) — callback-based flow

Быстрая публикация реализуется через **callback_data** (не FSM), т.к. не требует пользовательского ввода — только нажатие кнопок.

```
Шаг 1 (если проектов >1): callback_data = "quick:project:{id}"
Шаг 2: callback_data = "quick:cat:{cat_id}:{platform}:{conn_id}"
```

После нажатия кнопки шага 2:
- Для WordPress → переход в FSM `ArticlePublish` (с Telegraph-превью)
- Для TG/VK/Pinterest → переход в FSM `SocialPostPublish` (подтверждение → генерация → публикация)

Формат callback_data — см. ARCHITECTURE.md §5.2.

---

## 4. Rate limits, переменные окружения, безопасность

### 4.1 Rate limits (Redis token-bucket)

**Наши лимиты (Aiogram middleware):**

| Эндпоинт/действие | Лимит | Окно | При превышении |
|-------------------|-------|------|----------------|
| Генерация контента (текст) | 10 запросов | 1 час | "Превышен лимит генераций. Подождите {время}" |
| Генерация изображений | 20 запросов | 1 час | Аналогично |
| Генерация ключевых фраз | 5 запросов | 1 час | Аналогично |
| Любой callback/message | 30 запросов | 1 мин | Молча игнорировать (anti-flood) |
| Покупка токенов | 5 запросов | 10 мин | "Слишком частые покупки. Подождите" |
| Подключение платформы | 10 запросов | 1 час | Аналогично |
| API вебхуки (QStash) | 100 запросов | 1 мин | 429 (QStash повторит) |

**Реализация:** Aiogram middleware с Redis INCR + EXPIRE.

**Лимиты OpenRouter (внешние, не контролируем):**

| Условие | Лимит | Обработка |
|---------|-------|-----------|
| Paid модели (при наличии кредитов) | Без жёстких лимитов | — |
| Free модели (≥$10 кредитов) | 1000 req/day, 20 rpm | Не используем free-модели |
| HTTP 429 от OpenRouter | Провайдер перегружен | `allow_fallbacks: true` → автопереключение |
| HTTP 402 от OpenRouter | Кредиты закончились | Мониторинг через Sentry alert, E12 |
| Cloudflare DDoS block | Аномальный трафик | Exponential backoff, alert |

### 4.2 Переменные окружения

```env
# === Обязательные ===
TELEGRAM_BOT_TOKEN=           # Токен бота от @BotFather
ADMIN_ID=                     # Telegram ID администратора (GOD MODE)
SUPABASE_URL=                 # https://xxx.supabase.co
SUPABASE_KEY=                 # service_role key (серверный)
UPSTASH_REDIS_URL=            # redis://xxx.upstash.io:6379
UPSTASH_REDIS_TOKEN=          # Токен Upstash Redis
QSTASH_TOKEN=                 # Токен QStash для создания расписаний
QSTASH_CURRENT_SIGNING_KEY=   # Для верификации вебхуков
QSTASH_NEXT_SIGNING_KEY=      # Ротируемый ключ
OPENROUTER_API_KEY=           # Ключ OpenRouter (для всех AI-моделей)
FIRECRAWL_API_KEY=            # Ключ Firecrawl
ENCRYPTION_KEY=               # Fernet-ключ для шифрования credentials (generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
TELEGRAM_WEBHOOK_SECRET=      # secret_token для верификации вебхуков Telegram (generate: python -c "import secrets; print(secrets.token_hex(32))")

# === Опциональные ===
DATAFORSEO_LOGIN=             # Логин DataForSEO (если используется)
DATAFORSEO_PASSWORD=          # Пароль DataForSEO
SERPER_API_KEY=               # Ключ Serper.dev
YOOKASSA_SHOP_ID=             # ID магазина ЮKassa (если подключена)
YOOKASSA_SECRET_KEY=          # Секретный ключ ЮKassa
SENTRY_DSN=                   # DSN для Sentry (мониторинг ошибок)
RAILWAY_PUBLIC_URL=           # URL приложения на Railway (для вебхуков)
PINTEREST_APP_ID=              # Pinterest App ID (OAuth)
PINTEREST_APP_SECRET=          # Pinterest App Secret
USD_RUB_RATE=92.5              # Курс USD→RUB для отображения API-расходов в админке

# === Дефолты (можно не указывать) ===
DEFAULT_TIMEZONE=Europe/Moscow
FSM_TTL_SECONDS=86400          # 24 часа — TTL Redis-ключа (жёсткая очистка)
FSM_INACTIVITY_TIMEOUT=1800    # 30 мин — таймаут неактивности (автосброс FSM)
PREVIEW_TTL_SECONDS=86400      # 24 часа
MAX_REGENERATIONS_FREE=2       # Бесплатных перегенераций
```

### 4.3 Хранение секретов

- Все credentials в `platform_connections.credentials` → **TEXT, зашифрованный Fernet** (symmetric encryption, ключ в env var `ENCRYPTION_KEY`). Расшифрованное значение — JSON-строка, парсится в dict на уровне приложения
- Supabase RLS: дополнительный уровень защиты. Основная авторизация — в repository layer (WHERE user_id = ?). service_role key обходит RLS.
- API-ключи → только в Railway env vars, НЕ в коде
- Telegram webhook secret → `secret_token` параметр в `set_webhook()`:
  ```python
  # main.py — on_startup
  await bot.set_webhook(
      url=f"{os.environ['RAILWAY_PUBLIC_URL']}/webhook",
      secret_token=os.environ["TELEGRAM_WEBHOOK_SECRET"],
      allowed_updates=["message", "callback_query", "pre_checkout_query"],
  )
  # Aiogram верифицирует X-Telegram-Bot-Api-Secret-Token автоматически
  ```

---

## 5. Промпт-спецификация (пример)

Промпты хранятся как YAML-файлы в `services/ai/prompts/` и дублируются в таблице `prompt_versions` для A/B тестирования.

### 5.0 Движок рендеринга промптов

**Движок:** Jinja2 с кастомными разделителями (чтобы не конфликтовать с JSON `{}`).

```python
from jinja2 import Environment

prompt_env = Environment(
    variable_start_string="<<",
    variable_end_string=">>",
    block_start_string="<%",
    block_end_string="%>",
    comment_start_string="<#",
    comment_end_string="#>",
    autoescape=False,
)

def render_prompt(template_yaml: str, context: dict) -> str:
    template = prompt_env.from_string(template_yaml)
    return template.render(**sanitize_variables(context))
```

**Источник истины:** YAML-файлы — seed-данные. При деплое загружаются в таблицу `prompt_versions` командой `python -m bot.cli sync_prompts`. Во время выполнения читается ТОЛЬКО из БД. A/B варианты существуют только в БД.

**Санитизация переменных (защита от prompt injection):**
```python
def sanitize_variables(context: dict) -> dict:
    """Экранирует пользовательский ввод в переменных промпта."""
    sanitized = {}
    for key, value in context.items():
        if isinstance(value, str):
            # Удалить Jinja2-разделители из пользовательского ввода
            value = value.replace("<<", "").replace(">>", "")
            value = value.replace("<%", "").replace("%>", "")
        sanitized[key] = value
    return sanitized
```

**Обработка отсутствующих переменных:** Если переменная `required: false` и отсутствует → используется `default`. Если `required: true` и отсутствует → ошибка генерации, возврат токенов.

### Пример: article_v5.yaml

```yaml
meta:
  task_type: seo_article
  version: v5
  model_tier: premium
  max_tokens: 8000
  temperature: 0.7

system: |
  Ты — SEO-копирайтер. Пиши на <<language>>.
  Компания: <<company_name>> (<<specialization>>).
  Город: <<city>>. Преимущества: <<advantages>>.

user: |
  Напиши SEO-статью на тему "<<keyword>>" (<<volume>> запросов/мес, сложность: <<difficulty>>).

  Требования:
  - Объём: <<words_min>>-<<words_max>> слов
  - Структура: H1 (1), H2 (3-6), H3 (по необходимости), FAQ (3-5 вопросов)
  - Ключевая фраза "<<keyword>>" — в H1, первом абзаце, 2-3 H2, заключении
  - LSI-фразы: <<lsi_keywords>>
  - Внутренние ссылки (вставь естественно): <<internal_links>>
  - Упомяни цены из прайса: <<prices_excerpt>>
  - FAQ на основе реальных вопросов: <<serper_questions>>
  - Учти данные конкурентов: <<competitor_summary>>

  Формат ответа — JSON:
  {
    "title": "...",
    "meta_description": "... (до 160 символов)",
    "content_html": "... (полный HTML с inline-стилями: цвет текста <<text_color>>, акцент <<accent_color>>)",
    "faq_schema": [{"question": "...", "answer": "..."}]
  }

variables:
  - name: keyword
    source: categories.keywords (выбранная фраза)
    required: true
  - name: volume
    source: DataForSEO
    required: false
    default: "неизвестно"
  - name: difficulty
    source: DataForSEO
    required: false
    default: "неизвестно"
  - name: words_min
    source: text_settings
    required: true
    default: 1500
  - name: words_max
    source: text_settings
    required: true
    default: 2500
  - name: company_name
    source: projects.company_name
    required: true
  - name: specialization
    source: projects.specialization
    required: true
  - name: city
    source: projects.company_city
    required: false
    default: ""
  - name: advantages
    source: projects.advantages
    required: false
    default: ""
  - name: language
    source: users.language
    required: true
    default: "ru"
  - name: lsi_keywords
    source: DataForSEO related keywords
    required: false
    default: ""
  - name: internal_links
    source: Firecrawl crawl (platform_connections.credentials.internal_links)
    required: false
    default: ""
  - name: prices_excerpt
    source: categories.prices (первые 10 позиций)
    required: false
    default: ""
  - name: serper_questions
    source: Serper "People Also Ask"
    required: false
    default: ""
  - name: competitor_summary
    source: Firecrawl /extract результат
    required: false
    default: ""
  - name: text_color
    source: site_brandings.colors.text
    required: false
    default: "#333333"
  - name: accent_color
    source: site_brandings.colors.accent
    required: false
    default: "#0066cc"
```

### Пример: social.yaml

```yaml
meta:
  task_type: social_post
  version: v3
  model_tier: budget
  max_tokens: 2000
  temperature: 0.8

system: |
  Ты — SMM-копирайтер. Пиши на <<language>>.
  Компания: <<company_name>> (<<specialization>>).

user: |
  Напиши пост для <<platform>> на тему "<<keyword>>".

  Требования:
  - Стиль: <<text_style>>
  - Длина: <<words_min>>-<<words_max>> слов
  - Платформа <<platform>>:
    - telegram: HTML-разметка (<b>, <i>, <a>), макс. 4096 символов
    - vk: текст + хештеги, макс. 16 384 символов
    - pinterest: описание пина, макс. 500 символов + заголовок 100 символов
  - Упомяни цены (если есть): <<prices_excerpt>>
  - Ключевая фраза "<<keyword>>" — в первом предложении
  - Призыв к действию в конце

  Формат ответа — JSON:
  {
    "text": "...",
    "hashtags": ["...", "..."],
    "pin_title": "..."
  }

variables:
  - name: keyword
    source: categories.keywords (выбранная фраза)
    required: true
  - name: platform
    source: telegram, vk, pinterest
    required: true
  - name: company_name
    source: projects.company_name
    required: true
  - name: specialization
    source: projects.specialization
    required: true
  - name: language
    source: users.language
    required: true
    default: "ru"
  - name: text_style
    source: text_settings.style
    required: true
    default: "Разговорный"
  - name: words_min
    source: text_settings
    required: true
    default: 100
  - name: words_max
    source: text_settings
    required: true
    default: 300
  - name: prices_excerpt
    source: categories.prices (первые 5 позиций)
    required: false
    default: ""
```

### Пример: keywords.yaml

```yaml
meta:
  task_type: keywords
  version: v2
  model_tier: budget
  max_tokens: 4000
  temperature: 0.5

system: |
  Ты — SEO-специалист. Генерируй ключевые фразы на <<language>>.

user: |
  Сгенерируй <<quantity>> SEO-ключевых фраз для бизнеса:
  - Товары/услуги: <<products>>
  - География: <<geography>>
  - Компания: <<company_name>> (<<specialization>>)

  Требования:
  - Микс: высокочастотные (20%), среднечастотные (50%), низкочастотные (30%)
  - Включи коммерческие ("купить", "заказать", "цена") и информационные ("как выбрать", "отзывы")
  - Учти географию в фразах где уместно
  - НЕ дублируй фразы, НЕ используй синонимы-дубликаты

  Формат ответа — JSON-массив:
  [
    {"phrase": "кухни на заказ москва", "intent": "commercial"},
    {"phrase": "как выбрать кухонный гарнитур", "intent": "informational"}
  ]

variables:
  - name: quantity
    source: FSM-выбор (50, 100, 150, 200)
    required: true
  - name: products
    source: FSM-ответ (товары/услуги)
    required: true
  - name: geography
    source: FSM-ответ (география)
    required: true
  - name: company_name
    source: projects.company_name
    required: true
  - name: specialization
    source: projects.specialization
    required: true
  - name: language
    source: users.language
    required: true
    default: "ru"
```

### Пример: review.yaml

```yaml
meta:
  task_type: review
  version: v1
  model_tier: budget
  max_tokens: 2000
  temperature: 0.9

system: |
  Ты — копирайтер. Пиши реалистичные отзывы на <<language>>.

user: |
  Сгенерируй <<quantity>> отзывов для компании "<<company_name>>" (<<specialization>>).

  Требования:
  - Распределение рейтингов: 60% — 5 звёзд, 25% — 4 звезды, 15% — 3 звезды
  - Каждый отзыв: имя автора, дата (последние 6 месяцев), рейтинг (1-5), текст, плюсы, минусы
  - Стиль: разговорный, как реальный покупатель
  - Упомяни товары из прайса: <<prices_excerpt>>

  Формат ответа — JSON-массив:
  [{"author": "...", "date": "2026-01-15", "rating": 5, "text": "...", "pros": "...", "cons": "..."}]

variables:
  - name: quantity
    source: FSM-выбор (3/5/10)
    required: true
  - name: company_name
    source: projects.company_name
    required: true
  - name: specialization
    source: projects.specialization
    required: true
  - name: language
    source: users.language
    required: true
    default: "ru"
  - name: prices_excerpt
    source: categories.prices (первые 5 позиций)
    required: false
    default: ""
```

### Пример: description.yaml

```yaml
meta:
  task_type: description
  version: v1
  model_tier: budget
  max_tokens: 1000
  temperature: 0.7

system: |
  Ты — SEO-копирайтер. Пиши на <<language>>.

user: |
  Напиши описание категории "<<category_name>>" для компании "<<company_name>>" (<<specialization>>).

  Контекст:
  - Ключевые фразы категории: <<keywords_sample>>
  - Товары/услуги: <<prices_excerpt>>
  - Отзывы клиентов: <<reviews_excerpt>>

  Требования:
  - Объём: 100-300 слов
  - Включи основные ключевые фразы естественно
  - Описание используется как контекст для AI при генерации статей и постов

  Формат: простой текст (без HTML, без JSON).

variables:
  - name: category_name
    source: categories.name
    required: true
  - name: company_name
    source: projects.company_name
    required: true
  - name: specialization
    source: projects.specialization
    required: true
  - name: language
    source: users.language
    required: true
    default: "ru"
  - name: keywords_sample
    source: categories.keywords (первые 10 фраз)
    required: false
    default: "не заданы"
  - name: prices_excerpt
    source: categories.prices (первые 5 позиций)
    required: false
    default: ""
  - name: reviews_excerpt
    source: categories.reviews (первые 3 отзыва, если есть)
    required: false
    default: ""
```

---

## 6. Стратегия ротации ключевых фраз

При автопубликации бот должен выбирать ключевые фразы для статей/постов таким образом, чтобы не повторять одну фразу слишком часто.

### Алгоритм

```
1. Получить все фразы категории: categories.keywords (JSON-массив)
2. Отсортировать по перспективности: volume DESC, difficulty ASC
3. Исключить фразы, использованные за последние 7 дней:
   SELECT keyword FROM publication_logs
   WHERE category_id = ? AND created_at > now() - INTERVAL '7 days'
4. Выбрать первую доступную фразу (round-robin с приоритетом)
5. Если все фразы использованы за 7 дней → взять LRU (самую давно использованную)
6. Если фраз в категории < 5 → предложить пользователю: "Добавьте ещё ключевых фраз для разнообразия контента"
```

### Параметры

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| Cooldown-период | 7 дней | При 1 посте/день и 10 фразах — каждая фраза раз в 10 дней |
| Минимальный пул | 5 фраз | Ниже — предупреждение пользователю |
| Приоритет | volume DESC, difficulty ASC | Сначала высокочастотные + лёгкие для продвижения |
| Fallback | LRU (Least Recently Used) | Если все на cooldown — берём самую давнюю |

### Логирование

Каждая публикация записывает `keyword` в `publication_logs`. Это позволяет:
- Отслеживать частоту использования каждой фразы
- Анализировать эффективность (CTR, позиции) по фразам
- Автоматически исключать "выгоревшие" фразы (будущая фича)

---

## 7. Генерация изображений (Nano Banana / OpenRouter)

### 7.1 Модели

| Модель | Model ID | Назначение | Цена (input/output) |
|--------|----------|-----------|---------------------|
| Nano Banana (Gemini 2.5 Flash Image) | `google/gemini-2.5-flash-image` | Стандартная генерация (соцсети, бюджет) | $0.30/$2.50 per M tokens, $30/M image output |
| Nano Banana Pro (Gemini 3 Pro Image) | `google/gemini-3-pro-image-preview` | Премиум генерация (статьи, высокое качество) | $2/$12 per M tokens, $120/M image output |

**Fallback цепочка:** определяется через `MODEL_CHAINS["image"]` (§3.1): Nano Banana Pro → Nano Banana → ошибка + возврат токенов.

### 7.2 API-запрос

```python
import openai

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

response = client.chat.completions.create(
    model="google/gemini-3-pro-image-preview",
    messages=[{
        "role": "user",
        "content": render_prompt("image.yaml", context)
    }],
    extra_body={
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": aspect_ratio,  # из image_settings.formats[0]
            "image_size": "2K",            # HD→1K, Ultra HD→2K, 8K→4K
        }
    }
)
```

### 7.3 Ответ

Изображения возвращаются как base64 в `response.choices[0].message.images[]`:
```json
{
  "images": ["data:image/png;base64,iVBOR..."]
}
```

**Обработка:**
1. Декодировать base64 → bytes
2. Для WordPress: загрузить через WP REST Media API → получить `attachment_id`
3. Для Telegram/VK: отправить как `InputMediaPhoto`
4. Для Pinterest: закодировать в base64 для Pin API
5. Для превью: сохранить URL в `article_previews.images` JSONB

### 7.4 Маппинг настроек

| `image_settings` поле | Маппинг в prompt / API |
|-----------------------|----------------------|
| `formats` (["1:1", "2:3"]) | `image_config.aspect_ratio` — выбрать случайный из массива |
| `quality` ("HD"/"Ultra HD"/"8K") | `image_config.image_size`: HD→"1K", Ultra HD→"2K", 8K→"4K" |
| `styles` (["Фотореализм"]) | Включить в промпт: "Стиль: фотореалистичный" |
| `tones` (["Тёплый"]) | Включить в промпт: "Тональность: тёплая" |
| `cameras` (["Canon EOS R5"]) | Включить в промпт: "Снято на Canon EOS R5" |
| `angles` (["Аэросъёмка"]) | Включить в промпт: "Ракурс: аэросъёмка" |
| `count` (4) | N отдельных запросов (1 изображение за запрос). См. §7.4.1 ниже |
| `text_on_image` (0-100%) | Включить в промпт: "Текст на изображении: {value}%" |

#### 7.4.1 Генерация нескольких изображений (count > 1)

**Стратегия вариативности:** Каждый запрос из N получает модифицированный промпт:
- Изображение 1: базовый промпт (основной ракурс)
- Изображение 2+: добавляется суффикс `"Покажи с другого ракурса: {angle}"`, где angle берётся из `image_settings.angles` (round-robin) или из предустановленного списка `["крупный план", "общий план", "детали", "в контексте использования"]`

**Выбор aspect_ratio:** Если `formats` содержит несколько значений (напр. `["16:9", "1:1"]`), каждый запрос получает следующий формат по round-robin. Если один формат — все изображения одинаковые.

**Partial failure:** Запросы выполняются через `asyncio.gather(return_exceptions=True)`. Если K из N изображений успешны (K ≥ 1) — продолжить с K изображениями, предупредить: "Сгенерировано {K} из {N} изображений". Если все N провалились — fallback на следующую модель из `MODEL_CHAINS["image"]`. Если вся цепочка исчерпана — возврат 30×N токенов, уведомление об ошибке.

### 7.5 Промпт-шаблон (image.yaml)

```yaml
meta:
  task_type: image
  version: v1
  model_tier: premium       # premium → gemini-3-pro, budget → gemini-2.5-flash
  max_tokens: 4000

user: |
  Сгенерируй изображение для <<content_type>> на тему "<<keyword>>".
  
  Компания: <<company_name>> (<<specialization>>).
  Стиль: <<style>>. Тональность: <<tone>>.
  <<camera_instruction>>
  <<angle_instruction>>
  <<text_on_image_instruction>>
  
  Цветовая палитра сайта:
  - Основной: <<primary_color>>
  - Акцентный: <<accent_color>>
  - Фон: <<background_color>>
  
  Изображение должно соответствовать теме и визуальному стилю бренда.
  НЕ добавляй текст на изображение, если не указано иное.

variables:
  - name: keyword
    source: categories.keywords (выбранная фраза)
    required: true
  - name: content_type
    source: "article" | "social_post"
    required: true
  - name: company_name
    source: projects.company_name
    required: true
  - name: specialization
    source: projects.specialization
    required: true
  - name: style
    source: image_settings.styles[0] или IMAGE_DEFAULTS
    required: true
    default: "Фотореализм"
  - name: tone
    source: image_settings.tones[0] или IMAGE_DEFAULTS
    required: true
    default: "Нейтральный"
  - name: camera_instruction
    source: image_settings.cameras (если пусто — опустить)
    required: false
    default: ""
  - name: angle_instruction
    source: image_settings.angles (если пусто — опустить)
    required: false
    default: ""
  - name: primary_color
    source: site_brandings.colors.primary
    required: false
    default: "#333333"
  - name: accent_color
    source: site_brandings.colors.accent
    required: false
    default: "#0066cc"
  - name: background_color
    source: site_brandings.colors.background
    required: false
    default: "#ffffff"
```

### 7.6 Стоимость

| Контент | Модель | ~Токенов OpenRouter | ~USD | Внутренних токенов |
|---------|--------|--------------------:|-----:|-------------------:|
| 1 изображение (соцсеть) | Nano Banana | ~500 output | ~$0.015 | 30 |
| 4 изображения (статья) | Nano Banana Pro | ~2000 output | ~$0.24 | 120 |

---

## 8. Контракты внешних сервисов

### 8.1 FirecrawlClient

```python
@dataclass
class BrandingResult:
    colors: dict       # {background, text, accent, primary, secondary}
    fonts: dict        # {heading, body}
    logo_url: str | None

@dataclass
class CrawlResult:
    pages: list[dict]  # [{url, title, links: [...]}]
    total_pages: int

@dataclass
class ExtractResult:
    data: dict         # Структурированные данные по схеме
    source_urls: list[str]

class FirecrawlClient:
    async def scrape_branding(self, url: str) -> BrandingResult: ...
    async def crawl_site(self, url: str, limit: int = 100) -> CrawlResult: ...
    async def extract(self, urls: list[str], prompt: str, schema: dict) -> ExtractResult: ...
```

**Retry:** 3 попытки, exponential backoff (1s, 3s, 9s). При недоступности → E15.
**Кеширование:** Результат `scrape_branding` кешируется в Redis на 7 дней (ключ: `branding:{project_id}`).

### 8.2 DataForSEOClient

```python
@dataclass
class KeywordData:
    phrase: str
    volume: int          # Запросов/мес
    difficulty: int      # 0-100
    cpc: float           # Стоимость клика в USD
    intent: str          # commercial, informational

class DataForSEOClient:
    async def enrich_keywords(
        self, phrases: list[str], location: str = "Russia", language: str = "ru"
    ) -> list[KeywordData]: ...
```

**Batch:** До 700 фраз за 1 запрос. Для 200 фраз — 1 запрос.
**Стоимость:** $0.0001/фраза. 200 фраз = $0.02.
**Retry:** 2 попытки. При недоступности → E03 (показать фразы без данных).

### 8.3 SerperClient

```python
@dataclass
class SearchResult:
    organic: list[dict]      # [{title, link, snippet}]
    people_also_ask: list[str]
    related_searches: list[str]

class SerperClient:
    async def search(self, query: str, location: str = "Russia", language: str = "ru") -> SearchResult: ...
```

**Кеширование:** Результат поиска в Redis на 24 часа (ключ: `serper:{md5(query)}`).
**Retry:** 2 попытки. При недоступности → E04 (генерация без Serper-данных).

### 8.4 PageSpeedClient

```python
@dataclass
class PageSpeedResult:
    performance: int       # 0-100
    accessibility: int
    best_practices: int
    seo_score: int
    lcp_ms: int           # Largest Contentful Paint
    inp_ms: int           # Interaction to Next Paint
    cls: float            # Cumulative Layout Shift
    ttfb_ms: int          # Time to First Byte
    recommendations: list[dict]  # [{title, description, priority}]
    full_report: dict     # Полный JSON PSI API

class PageSpeedClient:
    async def audit(self, url: str, strategy: str = "mobile") -> PageSpeedResult: ...
```

**Маппинг PSI → site_audits:**
| PSI поле | Колонка |
|----------|---------|
| `lighthouseResult.categories.performance.score * 100` | `performance` |
| `lighthouseResult.categories.seo.score * 100` | `seo_score` |
| `loadingExperience.metrics.LARGEST_CONTENTFUL_PAINT_MS.percentile` | `lcp_ms` |
| `loadingExperience.metrics.INTERACTION_TO_NEXT_PAINT.percentile` | `inp_ms` |
| `loadingExperience.metrics.CUMULATIVE_LAYOUT_SHIFT_SCORE.percentile / 100` | `cls` |
| `loadingExperience.metrics.EXPERIMENTAL_TIME_TO_FIRST_BYTE.percentile` | `ttfb_ms` |

**Стоимость:** Бесплатно (25K запросов/день).
**Retry:** 2 попытки. При timeout (>30s) → сохранить частичные данные.

### 8.5 TelegraphClient

```python
@dataclass  
class TelegraphPage:
    url: str              # https://telegra.ph/Article-Title-02-11
    path: str             # Article-Title-02-11 (для удаления)

class TelegraphClient:
    async def create_page(self, title: str, html: str, author: str = "SEO Master Bot") -> TelegraphPage: ...
    async def delete_page(self, path: str) -> bool: ...
```

**TTL:** Превью автоматически удаляется через 24 часа (job `/api/cleanup`).
**При недоступности (E05):** Показать первые 500 символов статьи в чат, предложить публикацию без превью.

### 8.6 CredentialManager

```python
from cryptography.fernet import Fernet

class CredentialManager:
    """Шифрование/расшифровка credentials. Используется ТОЛЬКО в repository layer."""
    
    def __init__(self, encryption_key: str):
        self.fernet = Fernet(encryption_key.encode())
    
    def encrypt(self, credentials: dict) -> str:
        """dict → зашифрованная строка для хранения в БД."""
        json_bytes = json.dumps(credentials).encode()
        return self.fernet.encrypt(json_bytes).decode()
    
    def decrypt(self, encrypted: str) -> dict:
        """Зашифрованная строка из БД → dict."""
        json_bytes = self.fernet.decrypt(encrypted.encode())
        return json.loads(json_bytes)
```

**Слой шифрования:** Repository. Сервисы и паблишеры всегда получают расшифрованный dict.
**Ротация ключей** (`python -m bot.cli rotate_keys`):
```python
async def rotate_keys(old_key: str, new_key: str):
    old_manager = CredentialManager(old_key)
    new_manager = CredentialManager(new_key)
    
    connections = await repo.get_all_connections()  # Все записи
    failed = []
    
    for conn in connections:
        try:
            decrypted = old_manager.decrypt(conn.credentials)
            conn.credentials = new_manager.encrypt(decrypted)
            await repo.update_connection_credentials(conn.id, conn.credentials)
        except Exception as e:
            failed.append((conn.id, str(e)))
    
    if failed:
        # Не менять ENCRYPTION_KEY env var — часть записей ещё на старом ключе
        raise RotationError(f"Не удалось перешифровать {len(failed)} записей: {failed}")
    
    # Все успешно → можно обновить ENCRYPTION_KEY в Railway env vars
    print(f"Ротация завершена: {len(connections)} записей перешифровано")
```
Алгоритм: поштучно (не batch), при ошибке — откат невозможен, но старые записи остаются читаемыми старым ключом. ENV var менять ТОЛЬКО после 100% успеха.
