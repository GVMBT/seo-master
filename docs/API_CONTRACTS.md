# SEO Master Bot v2 — API-контракты и интеграции

> Связанные документы: [PRD.md](PRD.md) (продуктовые требования), [ARCHITECTURE.md](ARCHITECTURE.md) (техническая архитектура), [FSM_SPEC.md](FSM_SPEC.md) (FSM-состояния), [EDGE_CASES.md](EDGE_CASES.md) (обработка ошибок), [UX_PIPELINE.md](UX_PIPELINE.md) + [UX_TOOLBOX.md](UX_TOOLBOX.md) (UX-спецификации)

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
  "idempotency_key": "pub_42_09:00"
}
```

PublishService проверяет `cross_post_connection_ids` на schedule после успешной lead-публикации.
Для каждого зависимого подключения: AI-адаптация (~10 ток) → publish → log с `content_type="cross_post"`.
Partial failure OK: ведущий пост остаётся опубликованным, ошибочные кросс-посты рефундятся.

### 1.3 Верификация подписи QStash

```python
from qstash import Receiver

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
# Redis-блокировка по Upstash-Message-Id header:
# Уникален per trigger, одинаков при retry того же сообщения.
msg_id = request["qstash_msg_id"]  # из require_qstash_signature декоратора
lock_key = f"publish_lock:{msg_id}"
acquired = await redis.set(lock_key, "1", nx=True, ex=300)  # 5 мин TTL

if not acquired:
    return web.json_response({"status": "duplicate"})  # QStash НЕ повторит (2xx)
```

> **Upstash-Message-Id** — заголовок QStash, уникальный для каждого trigger и стабильный при retry.
> Все три QStash-хендлера (publish, cleanup, notify) используют один паттерн: `{prefix}_lock:{msg_id}`.
> Body-поле `idempotency_key` (`pub_{schedule_id}_{time_slot}`) остаётся для логирования/отладки.

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
   - **Атомарный захват:** `UPDATE article_previews SET status = 'expired' WHERE id = $1 AND status = 'draft' RETURNING *`
     Если 0 строк → превью уже опубликовано/expired (race condition с пользователем), пропустить
   - Удалить Telegraph-страницу (Telegraph API `editPage` → пустой контент, или игнорировать ошибку)
   - Вернуть токены: `await users_repo.refund_balance(ap.user_id, ap.tokens_charged)` (ARCHITECTURE.md §5.5, атомарный RPC)
   - Записать возврат: `await payments_repo.create_expense(user_id=ap.user_id, amount=ap.tokens_charged, operation_type='refund')`
   - Отправить уведомление (если `notify_publications = TRUE`): "Превью статьи «{keyword}» истекло. Токены возвращены: +{tokens_charged}. [Сгенерировать заново]"
2. `publication_logs` WHERE `created_at < now() - INTERVAL '90 days'` → архивировать/удалить (настраиваемый период)
3. Логировать количество очищенных записей

> **Race condition cleanup vs publish:** Обе операции используют атомарный `UPDATE ... WHERE status = 'draft' RETURNING *`.
> Кто первый обновит status — тот выиграл. Проигравший получит 0 строк и корректно прервётся.
> Redis lock для preview НЕ нужен — DB-level sufficient (PostgreSQL row-level locking).

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
from qstash import QStash

qstash = QStash(token=os.environ["QSTASH_TOKEN"])

# Маппинг schedule_days + schedule_times + timezone → cron + N расписаний
# Одно QStash-расписание = одно время публикации (cron не поддерживает массив времён)

def create_schedules_for_platform(schedule: PlatformSchedule) -> list[str]:
    """Создаёт N QStash-расписаний (по одному на каждое время).
    Возвращает список ID для сохранения в qstash_schedule_ids.

    Примечание: platform_schedules не содержит user_id/project_id напрямую.
    Вызывающий код (service layer) делает JOIN:
    platform_schedules → categories.project_id → projects.user_id
    и передаёт обогащённый объект PlatformSchedule с user_id и project_id."""
    
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
                "idempotency_key": f"pub_{schedule.id}_{time_slot}"
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
   → Начислить токены: await users_repo.credit_balance(user_id, 3500) (ARCHITECTURE.md §5.5, атомарный RPC)
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

Эндпоинт: `POST /api/yookassa/renew`
Верификация: QStash signature (`@require_qstash_signature`)

```python
# Body (от QStash):
{
    "user_id": 123456,
    "payment_method_id": "pm_xxx",
    "package": "pro"
}
```

Идемпотентность: Redis NX lock `yookassa_renew:{user_id}` (TTL 1ч).
При ошибке создания платежа → уведомить пользователя (E37), НЕ ретраить (QStash retry может создать дубликат).

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
    # Результат придёт через вебхук payment.succeeded / payment.canceled (E37)
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

> **Решено:** OpenAI AsyncClient (`openai>=2.20`) с `base_url="https://openrouter.ai/api/v1"`. OpenRouter-специфичные фичи (`models[]`, `provider`, `plugins`) передаются через `extra_body`/`extra_headers`.

#### Контракты данных

```python
@dataclass
class GenerationRequest:
    task: Literal["article", "social_post", "keywords", "review", "image", "description"]
    prompt_version: str          # "v6", "v3" — ссылка на prompt_versions
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
    keyword: str                                # ALWAYS populated. For clusters: = main_phrase. For legacy: = selected phrase
                                                # NOTE: промпты используют <<keyword>> (social) и <<main_phrase>> (article). GenerationContext заполняет оба
    language: str = "ru"
    # === Cluster-aware fields (article_v6, keywords_cluster_v3) ===
    main_phrase: str | None = None              # cluster.main_phrase. If None → use keyword (legacy). New code should prefer main_phrase when not None
    secondary_phrases: str | None = None        # "phrase1 (N/мес), phrase2 (M/мес)"
    cluster_volume: int | None = None           # cluster.total_volume
    main_volume: int | None = None              # cluster.phrases[main].volume
    main_difficulty: int | None = None          # cluster.phrases[main].difficulty
    cluster_type: str | None = None             # "article" | "product_page"
    # === Competitor analysis (Firecrawl /scrape) ===
    competitor_analysis: str | None = None       # AI summary of competitor content
    competitor_gaps: str | None = None           # Topics missing from all competitors
    # === Dynamic sizing ===
    words_min: int | None = None                 # From competitor analysis or text_settings
    words_max: int | None = None
    # === Image SEO ===
    images_count: int | None = None              # image_settings.count (for images_meta)
    # === Existing optional fields ===
    prices_excerpt: str | None = None
    advantages: str | None = None
    city: str | None = None
    internal_links: list[str] | None = None
    branding_colors: dict | None = None
    serper_data: dict | None = None
    serper_questions: str | None = None          # "People Also Ask" — random 3 of N
    lsi_keywords: str | None = None              # DataForSEO related keywords
    image_settings: dict | None = None
    text_settings: dict | None = None
    user_media_urls: list[str] | None = None     # URLs из categories.media (F43: медиа как контекст для AI)

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
    "article":              ["anthropic/claude-sonnet-4.5", "openai/gpt-5.2", "deepseek/deepseek-v3.2"],
    "article_outline":      ["deepseek/deepseek-v3.2", "openai/gpt-5.2"],         # Stage 1: outline generation (budget)
    "article_critique":     ["deepseek/deepseek-v3.2", "openai/gpt-5.2"],         # Stage 3: conditional critique (budget, only if score < 80)
    "article_research":     ["perplexity/sonar-pro"],                              # Web research: current facts, trends, statistics
    "social_post":          ["deepseek/deepseek-v3.2", "anthropic/claude-sonnet-4.5"],
    "keywords":             ["deepseek/deepseek-v3.2", "openai/gpt-5.2"],         # AI clustering (keywords_cluster.yaml v3), NOT data fetching
    "review":               ["deepseek/deepseek-v3.2", "anthropic/claude-sonnet-4.5"],
    "description":          ["deepseek/deepseek-v3.2", "anthropic/claude-sonnet-4.5"],
    "cross_post":           ["deepseek/deepseek-v3.2", "openai/gpt-5.2"],           # Text adaptation between platforms (budget)
    "image":                ["google/gemini-3-pro-image-preview", "google/gemini-3.1-flash-image-preview"],
}

# Использование — один запрос, OpenRouter сам делает fallback
response = await openai_client.chat.completions.create(
    model=MODEL_CHAINS[task][0],           # Основная модель
    messages=messages,
    extra_body={
        "models": MODEL_CHAINS[task][1:],  # Только fallback-модели (без основной)
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

**Расширенные параметры routing (февр. 2026):**
```python
"provider": {
    "sort": "throughput",
    "allow_fallbacks": True,
    "require_parameters": True,
    "data_collection": "deny",
    # Новые параметры:
    "max_price": {"prompt": 5, "completion": 15},     # Потолок цены $/M tokens
    "preferred_min_throughput": {"p90": 50},            # Мин. 50 tok/sec на P90
    "preferred_max_latency": {"p90": 3},                # Макс. 3с TTFB на P90
    "quantizations": ["fp16", "fp8"],                   # Фильтр по точности модели
    "only": ["Anthropic", "Google"],                    # Whitelist провайдеров
    "ignore": ["Together"],                             # Blacklist провайдеров
}
```

Рекомендуемые пресеты для задач:
| Задача | sort | max_price (prompt/compl) | min_throughput |
|--------|------|------------------------|----------------|
| article (streaming) | `throughput` | 5/15 | 50 tok/s |
| article_research | `latency` | 3/15 | — |
| social_post | `price` | 0.03/0.02 | — |
| keywords | `price` | 0.03/0.02 | — |
| review | `price` | 0.03/0.02 | — |
| description | `price` | 0.03/0.02 | — |
| article_outline | `price` | 0.03/0.02 | — |
| article_critique | `price` | 0.03/0.02 | — |
| image | — | — | — |

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
| article_research | JSON Schema (strict) | Да (fallback) |
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

| Провайдер | Тип | Настройка | Цена cached read | Экономия |
|-----------|-----|-----------|-----------------|----------|
| Anthropic | Ручной | `cache_control` breakpoint в system message | $0.30/M (vs $3.00/M) | **90%** (TTL 5 мин) |
| OpenAI | Автоматический | Не нужна (≥1024 tokens в prompt) | 50% от input | 50% |
| DeepSeek | Автоматический | Не нужна | ~50% от input | ~50% |
| Google Gemini | Автоматический | Не нужна (Gemini 2.5+) | ~50% от input | ~50% |

**Расчёт экономии для статей (Claude Sonnet 4.5):**
- System prompt article_v6: ~1500 tokens → при cached read: $0.00045 vs $0.0045 (экономия $0.004/статью)
- При 500 статей/мес: **$2/мес экономии** на input tokens. Автопубликация одной категории
  генерирует несколько статей подряд → cache hit гарантирован (TTL 5 мин).

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
    images: list[bytes]              # Сгенерированные изображения (WebP)
    images_meta: list[dict]          # [{alt, filename, figcaption}] — из AI response (reconciled)
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

> **Важно: shared HTTP client.** В примерах ниже `async with httpx.AsyncClient(...) as client:` используется для наглядности. В реальной реализации **ЗАПРЕЩЕНО** создавать новый `httpx.AsyncClient` на каждый запрос (см. ARCHITECTURE.md §2.2). Вместо этого используйте shared `http_client` из зависимостей. Для BasicAuth (WordPress): передавайте `auth` через параметры запроса (`client.post(..., auth=httpx.BasicAuth(...))`). Для Bearer (VK, Pinterest): передавайте через `headers`.

### 3.3 WordPressPublisher — WP REST API

```python
class WordPressPublisher(BasePublisher):
    """WP REST API v2. Авторизация: Application Password (Basic Auth)."""

    async def publish(self, request: PublishRequest) -> PublishResult:
        creds = request.connection.credentials  # {"url", "login", "app_password"}
        base = creds["url"].rstrip("/") + "/wp-json/wp/v2"
        auth = httpx.BasicAuth(creds["login"], creds["app_password"])

        async with httpx.AsyncClient(auth=auth, timeout=30) as client:
            # 1. Загрузить изображения → получить attachment IDs (с SEO-метаданными)
            attachment_ids = []
            for i, img_bytes in enumerate(request.images):
                meta = request.images_meta[i] if i < len(request.images_meta) else {}
                filename = f"{meta.get('filename', f'image-{i}')}.webp"
                alt_text = meta.get("alt", "")
                resp = await client.post(
                    f"{base}/media",
                    content=img_bytes,
                    headers={
                        "Content-Type": "image/webp",
                        "Content-Disposition": f'attachment; filename="{filename}"',
                    },
                )
                resp.raise_for_status()
                media_id = resp.json()["id"]
                # Update alt_text and caption via WP REST
                if alt_text or meta.get("figcaption"):
                    await client.post(
                        f"{base}/media/{media_id}",
                        json={
                            "alt_text": alt_text,
                            "caption": meta.get("figcaption", ""),
                        },
                    )
                attachment_ids.append(media_id)

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

**Schema.org:** Инъекция через `<script type="application/ld+json">` в начало `content` (Article, FAQPage). Генерируется AI в промпте article_v6.yaml.

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
    """VK API v5.199. Прямой токен, одна группа per connection."""
    VK_API = "https://api.vk.ru/method"
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

### 3.7 Валидация и оценка качества контента

#### ContentValidator (базовая валидация)

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
        
        # WordPress-специфичные (H1 = post title, content starts with H2)
        if platform == "wordpress" and content_type == "article":
            if not re.search(r"<h2[^>]*>", content):
                errors.append("Отсутствует H2-заголовок (контент должен начинаться с H2)")
            if not re.search(r"<p[^>]*>.{50,}", content):
                errors.append("Нет абзацев связного текста (мин. 50 символов)")
        
        return ValidationResult(is_valid=len(errors) == 0, errors=errors, warnings=[])

    def validate_images_meta(
        self, images_meta: list[dict], expected_count: int, main_phrase: str,
    ) -> ValidationResult:
        """Validate AI-generated images_meta before reconciliation."""
        errors, warnings = [], []

        if len(images_meta) != expected_count:
            warnings.append(
                f"images_meta count ({len(images_meta)}) != expected ({expected_count})"
            )

        for i, meta in enumerate(images_meta):
            if not meta.get("alt", "").strip():
                errors.append(f"images_meta[{i}].alt is empty")
            elif main_phrase.lower() not in meta["alt"].lower():
                warnings.append(f"images_meta[{i}].alt does not contain main_phrase")
            fn = meta.get("filename", "")
            if not fn or not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", fn):
                errors.append(f"images_meta[{i}].filename is not a valid slug: '{fn}'")
            if len(fn) > 180:
                errors.append(f"images_meta[{i}].filename too long ({len(fn)} chars)")

        return ValidationResult(
            is_valid=len(errors) == 0, errors=errors, warnings=warnings
        )
```

При частичном провале — все ошибки собираются в список, валидация не проходит.

**validate_images_meta** вызывается в Stage 5 (reconciliation) ПЕРЕД сопоставлением с изображениями.
При ошибках валидации — заменяем невалидные meta на generic (из title).

#### ContentQualityScorer (программная оценка качества)

Запускается на шаге 7 multi-step pipeline (§5). Оценивает **готовый HTML** (после Markdown → HTML).
Не вызывает AI — полностью программная (~200 строк Python).

**Зависимости:** `razdel` (токенизация русского текста), `pymorphy3` (морфология).

```python
@dataclass
class QualityScore:
    total: int                    # 0-100, взвешенная сумма
    breakdown: dict[str, int]     # {"seo": 28, "readability": 22, "naturalness": 18, ...}
    issues: list[str]             # ["keyword_density too high: 4.2%", ...]
    passed: bool                  # total >= threshold (default 40)

class ContentQualityScorer:
    """Programmatic SEO quality scorer. No AI calls."""

    def score(
        self,
        html: str,
        main_phrase: str,
        secondary_phrases: list[str],
        *,
        threshold: int = 40,
    ) -> QualityScore:
        """Score article quality. Returns 0-100."""
        scores = {}

        # === SEO metrics (max 30 points) ===
        scores["seo"] = self._score_seo(html, main_phrase, secondary_phrases)

        # === Readability (max 25 points) ===
        scores["readability"] = self._score_readability(html)

        # === Structure (max 20 points) ===
        scores["structure"] = self._score_structure(html)

        # === Naturalness (max 15 points) ===
        scores["naturalness"] = self._score_naturalness(html)

        # === Content depth (max 10 points) ===
        scores["depth"] = self._score_depth(html)

        total = sum(scores.values())
        return QualityScore(
            total=total,
            breakdown=scores,
            issues=self._issues,
            passed=total >= threshold,
        )
```

**Метрики по категориям:**

| Категория | Макс. баллов | Метрики |
|-----------|:------------:|---------|
| **SEO** | 30 | keyword_density (1.5-2.5%), keyword_in_h1, keyword_in_first_paragraph, keyword_in_conclusion, secondary_phrases_coverage, meta_description_length (120-160 chars) |
| **Readability** | 25 | Flesch-Kincaid для русского (формула Оборневой 2006), avg_sentence_length (<20 слов), avg_paragraph_length (<150 слов), vocabulary_diversity (TTR > 0.4) |
| **Structure** | 20 | h1_count (ровно 1), h2_count (3-6), faq_presence, schema_org_presence, internal_links_count, toc_presence |
| **Naturalness** | 15 | anti_slop_check (нет запрещённых слов), burstiness (вариативность длин предложений), no_generic_phrases, factual_density (числа/даты/названия в тексте) |
| **Content depth** | 10 | word_count (в рамках target), unique_entities (NER: бренды, города, цифры), list_presence (ul/ol), image_count |

**Flesch readability для русского (Оборнева 2006):**
```python
def flesch_ru(text: str) -> float:
    """Flesch Reading Ease adapted for Russian (Oborneva 2006)."""
    import razdel
    sentences = list(razdel.sentenize(text))
    words = list(razdel.tokenize(text))
    syllables = sum(count_syllables_ru(w.text) for w in words)
    if not sentences or not words:
        return 0.0
    asl = len(words) / len(sentences)       # avg sentence length
    asw = syllables / len(words)            # avg syllables per word
    return 206.835 - 1.3 * asl - 60.1 * asw
    # 80-100: очень легко, 60-80: легко, 40-60: средне, <40: сложно
```

**Quality gates:**
| Score | Действие | Контекст |
|:-----:|----------|----------|
| **80-100** | Auto-publish OK | Высокое качество, проходит без critique |
| **60-79** | Warning + conditional critique (шаг 8) | DeepSeek critique → Claude rewrite (1 попытка) |
| **40-59** | Warning, publish allowed | Предупреждение пользователю |
| **0-39** | Block publish | Ошибка генерации, возврат токенов, повторная генерация |

**SimHash (content uniqueness):**
```python
def check_uniqueness(
    content_hash: int,            # simhash текущей статьи
    published_hashes: list[int],  # из publication_logs.content_hash
    threshold: int = 3,           # Hamming distance
) -> bool:
    """Returns True if content is unique enough."""
    for existing in published_hashes:
        if bin(content_hash ^ existing).count("1") <= threshold:
            return False  # слишком похоже
    return True
```
Хранение: `publication_logs.content_hash BIGINT` (SimHash, 64 бита).
При Hamming distance ≤ 3 (>70% совпадение) → warning "Статья похожа на ранее опубликованную."

**Anti-hallucination checks (regex fact-checking):**
```python
def check_fabricated_data(html: str, prices_excerpt: str, advantages: str) -> list[str]:
    """Check for hallucinated prices, contacts, statistics."""
    issues = []
    # Цены в тексте должны совпадать с prices_excerpt (±20%)
    price_re = re.compile(r"(\d[\d\s]*)\s*(?:руб|₽|рублей)", re.IGNORECASE)
    text_prices = [int(p.replace(" ", "")) for p in price_re.findall(html)]
    known_prices = extract_prices(prices_excerpt)
    for p in text_prices:
        if not any(abs(p - kp) / max(kp, 1) < 0.2 for kp in known_prices):
            issues.append(f"Возможно выдуманная цена: {p} руб. (нет в прайсе)")
    # Проверка телефонов (не должны быть в тексте, если не в VERIFIED_DATA)
    phone_re = re.compile(r"\+?[78]\s*[\(-]?\d{3}[\)-]?\s*\d{3}[\s-]?\d{2}[\s-]?\d{2}")
    if phone_re.search(html) and not phone_re.search(advantages):
        issues.append("Найден телефон, не указанный в данных компании")
    # Фейковая статистика ("по данным исследований", "согласно опросу")
    fake_stats_re = re.compile(r"(?:по данным|согласно|исследовани[ея]|опрос|статистик)", re.IGNORECASE)
    if fake_stats_re.search(html):
        issues.append("Возможна фабрикованная статистика — проверить источник")
    return issues
```

### 3.8 ~~Быстрая публикация (F42)~~ → Goal-Oriented Pipeline

> **Замена:** Quick Publish заменён на Goal-Oriented Pipeline (см. [UX_PIPELINE.md](UX_PIPELINE.md)).
> Новые FSM: `ArticlePipelineFSM` (25 состояний), `SocialPipelineFSM` (28 состояний).
> Новые callback_data: `pipeline:article:*`, `pipeline:social:*`.

Pipeline использует FSM (не callback-based), т.к. включает inline sub-flows с пользовательским вводом (readiness check).

```
ArticlePipelineFSM: select_project → select_wp → select_category → readiness_check → confirm_cost → generating → preview → publishing
SocialPipelineFSM: select_project → select_connection → select_category → readiness_check → confirm_cost → generating → review → publishing
```

- ArticlePipeline: WordPress → Telegraph-превью → публикация
- SocialPipeline: TG/VK/Pinterest → ревью → публикация (+опциональный кросс-постинг)

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
HEALTH_CHECK_TOKEN=            # Bearer-токен для детального health check (generate: python -c "import secrets; print(secrets.token_hex(32))")
SUPABASE_STORAGE_BUCKET=content-images  # Bucket для промежуточного хранения изображений (cleanup 24ч)
RAILWAY_GRACEFUL_SHUTDOWN_TIMEOUT=120  # Секунд между SIGTERM и SIGKILL

# === Дефолты (можно не указывать) ===
DEFAULT_TIMEZONE=Europe/Moscow
FSM_TTL_SECONDS=86400          # 24 часа — TTL Redis-ключа (жёсткая очистка)
FSM_INACTIVITY_TIMEOUT=1800    # 30 мин — таймаут неактивности (автосброс FSM)
PREVIEW_TTL_SECONDS=86400      # 24 часа
MAX_REGENERATIONS_FREE=2       # Бесплатных перегенераций
```

### 4.3 Хранение секретов

- Все credentials в `platform_connections.credentials` → **TEXT, зашифрованный Fernet** (symmetric encryption, ключ в env var `ENCRYPTION_KEY`). Расшифрованное значение — JSON-строка, парсится в dict на уровне приложения
- Supabase RLS **НЕ используется** — service_role key обходит все RLS-политики. Авторизация реализована в Repository layer (`WHERE user_id = ?`). Это сознательное решение: бот — единственный клиент БД, все запросы проходят через Repository.
- API-ключи → только в Railway env vars, НЕ в коде
- Telegram webhook secret → `secret_token` параметр в `set_webhook()`:
  ```python
  # main.py — on_startup
  await bot.set_webhook(
      url=f"{os.environ['RAILWAY_PUBLIC_URL']}/webhook",
      secret_token=os.environ["TELEGRAM_WEBHOOK_SECRET"],
      allowed_updates=["message", "callback_query", "pre_checkout_query", "my_chat_member"],
  )
  # Aiogram верифицирует X-Telegram-Bot-Api-Secret-Token автоматически
  # Примечание: my_chat_member отслеживает НАШЕГО бота. Для бота-публикатора пользователя
  # (отдельный бот) статус в канале проверяется при каждой публикации (getChatMember)
  ```

---

## 5. Промпт-спецификация (пример)

Промпты хранятся как YAML-файлы в `services/ai/prompts/` и дублируются в таблице `prompt_versions` для версионирования.

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

**Источник истины:** YAML-файлы — seed-данные. При деплое загружаются в таблицу `prompt_versions` командой `python -m bot.cli sync_prompts`. Во время выполнения читается ТОЛЬКО из БД.

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

### Пример: article_v7.yaml

> **Ключевые изменения v6→v7:**
> 1. **Multi-step pipeline**: Outline (DeepSeek) → Expand (Claude) → Conditional Critique (DeepSeek, если quality_score < 80).
> 2. **Персона**: "SEO-копирайтер" → "контент-редактор в штате компании" — более конкретная, привязана к бизнесу.
> 3. **Temperature**: 0.7 → 0.6 для статей — точность важнее креативности.
> 4. **Markdown вместо HTML**: AI генерирует Markdown → `mistune` 3.x + `SEORenderer` → детерминистичный HTML с auto heading IDs, ToC, figure/figcaption, lazy loading. Устраняет проблему AI-генерируемого невалидного HTML.
> 5. **XML-теги**: структурированные секции `<SEO_CONSTITUTION>`, `<COMPANY_DATA>`, `<CONTENT_RULES>` в system prompt.
> 6. **Anti-slop blacklist**: ~20 слов-паразитов AI, явно запрещённых в промпте.
> 7. **Anti-contamination**: явная инструкция "НЕ копируй структуру конкурентов, используй ТОЛЬКО для gap-анализа".
> 8. **Self-review checklist**: встроенный чеклист в конце промпта, AI проверяет перед отдачей.
> 9. **Few-shot examples**: пример хорошего и плохого абзаца для калибровки стиля.
> 10. **Нишевая специализация**: Jinja2 условные блоки для YMYL-дисклеймеров, тональности, профессиональных терминов.
>
> Изменения v5→v6 (сохранены): кластер фраз, динамическая длина, Firecrawl /scrape, competitor_gaps, anti-cannibalization, images_meta.

#### Пайплайн генерации статьи (11 шагов, multi-step + research)

```
Шаг 1.  Выбор кластера (не одной фразы) → rotation по кластерам (§6)
Шаг 2.  ПАРАЛЛЕЛЬНО:
         2a. Serper search(main_phrase) → топ-5 URL + People Also Ask + Related
         2b. RESEARCH: Perplexity Sonar Pro → актуальные факты, тренды, статистика (research_v1.yaml)
             → JSON Schema: {facts[], trends[], statistics[], summary}
             → Redis кеш: research:{md5(main_phrase)[:12]}, TTL 7 дней
             → Graceful degradation: при ошибке Sonar — pipeline продолжает БЕЗ research (E53)
Шаг 3.  Firecrawl /scrape → топ-3 URL → markdown (структура, длина, темы)
Шаг 4.  AI анализирует конкурентов → определяет gaps + динамическую длину:
         target_words = median(competitor_word_counts) × 1.1, cap [1500, 5000]
Шаг 5.  OUTLINE: DeepSeek генерирует план статьи (article_outline_v1.yaml)
         → H1, H2×3-6, H3 при необходимости, FAQ вопросы, ключевые тезисы
         → Получает current_research для планирования разделов с учётом актуальных данных
Шаг 6.  EXPAND: Claude расширяет outline в полную статью (article_v7.yaml)
         → Markdown-формат, images_meta, faq_schema
         → Получает current_research: "Приоритизируй при противоречиях с собственными знаниями,
           дополняй своей экспертизой где research не покрывает"
Шаг 6a. BLOCK SPLIT: разбить текст на логические блоки (по H2/H3)
         → distribute_images(blocks, images_count) → block_indices
         → для каждого block_index: извлечь block_context (первые 200 слов секции)
         → запустить N image-промптов параллельно (block_context + image_settings)
Шаг 7.  ContentQualityScorer (§3.7): программная оценка качества
         → score >= 80: pass | score 60-79: warn | score < 40: block
Шаг 8.  CONDITIONAL CRITIQUE: если score < 80:
         → DeepSeek анализирует слабые места → Claude переписывает (1 попытка)
         → Получает current_research для верификации фактов в статье (бесплатная проверка)
         → ~30% статей, +$0.02 avg cost
Шаг 9.  Markdown → HTML: mistune + SEORenderer (§5.1)
         → auto heading IDs, ToC, figure/figcaption, lazy loading, branding CSS
Шаг 10. Telegraph-превью → публикация (изображения вставляются в соответствующие блоки текста)
```

**Стоимость multi-step + research:**
| Шаг | Модель | Стоимость | Примечание |
|-----|--------|-----------|------------|
| Research (шаг 2b) | Perplexity Sonar Pro | ~$0.01 | Всегда (кеш 7д, amortized ~$0.005) |
| Outline (шаг 5) | DeepSeek V3.2 | ~$0.01 | Всегда |
| Expand (шаг 6) | Claude 4.5 Sonnet | ~$0.12 | Всегда |
| Critique (шаг 8) | DeepSeek V3.2 | ~$0.02 | Только ~30% статей (score < 80) |
| **Avg total AI** | | **~$0.15** | +$0.01 vs без research, значительный прирост актуальности |

#### 5.1 Markdown → HTML Pipeline (SEORenderer)

AI генерирует **Markdown** (не HTML). Преобразование в HTML — детерминистичное:

```python
import mistune

class SEORenderer(mistune.HTMLRenderer):
    """Custom renderer: heading IDs, ToC, figure/figcaption, lazy loading."""

    def __init__(self, branding: dict | None = None) -> None:
        super().__init__()
        self._toc: list[dict] = []
        self._branding = branding or {}

    def heading(self, text: str, level: int, **attrs) -> str:
        slug = slugify(text)  # кириллица → транслит → lowercase-hyphens
        self._toc.append({"level": level, "text": text, "id": slug})
        return f'<h{level} id="{slug}">{text}</h{level}>\n'

    def image(self, alt: str, url: str, title: str | None = None) -> str:
        # {{IMAGE_N}} placeholders → <figure> с lazy loading
        return (
            f'<figure><img src="{url}" alt="{alt}" loading="lazy">'
            f'<figcaption>{title or alt}</figcaption></figure>\n'
        )

    def render_toc(self) -> str:
        """Generate Table of Contents HTML from collected headings."""
        # Only H2/H3 in ToC
        items = [h for h in self._toc if h["level"] in (2, 3)]
        if len(items) < 3:
            return ""
        html = '<nav class="toc"><h2>Содержание</h2><ul>'
        for item in items:
            indent = ' class="toc-h3"' if item["level"] == 3 else ""
            html += f'<li{indent}><a href="#{item["id"]}">{item["text"]}</a></li>'
        html += "</ul></nav>"
        return html
```

**Branding CSS** вместо inline-стилей: генерируется `<style>` блок из `site_brandings.colors` (text, accent, background). AI НЕ управляет стилями — только контент.

**Зависимость:** `mistune>=3.1` (PyPI). Добавить в `pyproject.toml`.

```yaml
meta:
  task_type: article
  version: v7
  model_tier: premium
  max_tokens: 12000
  temperature: 0.6

system: |
  Ты — контент-редактор в штате компании <<company_name>>. Пиши на <<language>>.

  <SEO_CONSTITUTION>
  1. Используй ТОЛЬКО факты из VERIFIED_DATA, COMPANY_DATA и CURRENT_RESEARCH. НЕ выдумывай кейсы, цифры, ROI, клиентов, статистику.
  2. Title (поле title) содержит главную фразу кластера. content_markdown начинается с ## H2 (НЕ # H1 — title уже является заголовком страницы).
  3. Главная фраза: 2-3 точных вхождения + синонимы/парафразы в остальных местах. Дословное повторение >3 раз — keyword stuffing.
  4. Структура: вступление → основные разделы (H2) → FAQ → заключение с CTA.
  5. Каждый H2 решает конкретную проблему читателя.
  6. Название компании — максимум 3 раза в тексте: вступление, один экспертный раздел, заключение.
  7. Внутренние ссылки вставляются в контексте (не списком).
  8. FAQ отвечает на реальные вопросы из поисковых систем.
  9. Заключение содержит конкретный призыв к действию с упоминанием компании.
  </SEO_CONSTITUTION>

  <COMPANY_DATA>
  Компания: <<company_name>> (<<specialization>>).
  Город: <<city>>.
  Преимущества: <<advantages>>.
  <% if niche_type == "medical" %>Ниша YMYL (медицина). Добавь дисклеймер: "Информация носит ознакомительный характер и не заменяет консультацию специалиста."<% endif %>
  <% if niche_type == "legal" %>Ниша YMYL (право). Добавь дисклеймер: "Статья носит информационный характер. За юридической консультацией обратитесь к специалисту."<% endif %>
  <% if niche_type == "finance" %>Ниша YMYL (финансы). Добавь дисклеймер: "Данная информация не является инвестиционной рекомендацией."<% endif %>
  </COMPANY_DATA>

  <CONTENT_RULES>
  Текущая дата: <<current_date>>.
  Стиль: <<text_style>>.

  ЗАПРЕЩЁННЫЕ слова (anti-slop): является, осуществлять, данный, широкий ассортимент,
  индивидуальный подход, высококвалифицированный, в кратчайшие сроки, уникальный опыт,
  на сегодняшний день, в рамках, комплексный подход, оптимальное решение,
  динамично развивающийся, занимает лидирующие позиции, воплощает в себе,
  мы рады предложить, не имеющий аналогов, передовые технологии, инновационный подход,
  высочайшее качество.
  Замена: используй конкретные факты вместо штампов.

  Конкурентные данные использовать ТОЛЬКО для gap-анализа. НЕ копировать структуру
  и формулировки конкурентов. Каждый раздел должен быть уникальным по содержанию.
  </CONTENT_RULES>

  <SELF_REVIEW>
  Перед отдачей ответа проверь:
  - [ ] Главная фраза в title, первом абзаце и заключении (в тексте — синонимы и парафразы)
  - [ ] content_markdown НЕ содержит # H1 — начинается с ## H2
  - [ ] Нет слов из ЗАПРЕЩЁННЫХ
  - [ ] Все факты, кейсы, цифры — ТОЛЬКО из VERIFIED_DATA, COMPANY_DATA и CURRENT_RESEARCH
  - [ ] FAQ основан на реальных вопросах, а не выдуманных
  - [ ] Название компании — максимум 3 раза в тексте
  - [ ] Title НЕ содержит название компании
  </SELF_REVIEW>

user: |
  Напиши SEO-статью в формате Markdown, нацеленную на кластер поисковых фраз:

  Главная фраза: "<<main_phrase>>" (<<main_volume>> запросов/мес, сложность: <<main_difficulty>>)
  Дополнительные фразы кластера: <<secondary_phrases>>
  Суммарный потенциал кластера: <<cluster_volume>> запросов/мес

  <% if outline %>
  <OUTLINE>
  <<outline>>
  </OUTLINE>
  <% endif %>

  <% if competitor_analysis %>
  <COMPETITOR_ANALYSIS>
  <<competitor_analysis>>
  </COMPETITOR_ANALYSIS>
  <% endif %>

  <% if competitor_gaps %>
  <COMPETITOR_GAPS>
  <<competitor_gaps>>
  </COMPETITOR_GAPS>
  <% endif %>

  <% if current_research %>
  <<current_research>>
  <% endif %>

  <VERIFIED_DATA>
  Цены компании (используй ТОЛЬКО эти, не выдумывай): <<prices_excerpt>>
  Преимущества (используй ТОЛЬКО эти): <<advantages>>
  Внутренние ссылки: <<internal_links>>
  </VERIFIED_DATA>

  Требования:
  - Объём: <<words_min>>-<<words_max>> слов
  - Формат: **Markdown** (НЕ HTML). Заголовки через #, ##, ###. Изображения: ![alt]({{IMAGE_N}} "figcaption")
  - Структура: ## H2 (3-6, включают дополнительные фразы кластера), ### H3 (по необходимости), ## FAQ (3-5 вопросов). content_markdown НЕ содержит # H1 — заголовок в поле title.
  - Главная фраза "<<main_phrase>>" — в title, первом абзаце, 1-2 H2, заключении. В остальных местах используй синонимы и парафразы
  - Дополнительные фразы кластера — распредели по H2 и тексту естественно
  - LSI-фразы: <<lsi_keywords>>
  - FAQ на основе реальных вопросов: <<serper_questions>>

  <EXAMPLE_GOOD>
  "В 2025 году мы установили 340 кухонь из массива дуба в Москве. Средняя стоимость проекта —
  от 280 000 руб. с фурнитурой Blum. Срок изготовления: 21 рабочий день с момента замера."
  </EXAMPLE_GOOD>

  <EXAMPLE_BAD>
  "Мы предлагаем широкий ассортимент кухонь высочайшего качества по оптимальным ценам.
  Наш индивидуальный подход и высококвалифицированные специалисты гарантируют результат."
  </EXAMPLE_BAD>

  Image SEO (для каждого из <<images_count>> изображений):
  - alt-текст (содержит ключевую фразу, описывает изображение)
  - slug для имени файла (латиница, через дефис, содержит ключевую фразу)
  - подпись под картинкой (figcaption)

  Формат ответа — JSON:
  {
    "title": "...",
    "meta_description": "... (до 160 символов)",
    "content_markdown": "... (полный Markdown. Картинки: ![alt]({{IMAGE_N}} \"figcaption\"))",
    "faq_schema": [{"question": "...", "answer": "..."}],
    "images_meta": [
      {"alt": "Описание с ключевой фразой", "filename": "slug-klyuchevaya-fraza", "figcaption": "Подпись"},
      ...
    ]
  }

variables:
  - name: main_phrase
    source: cluster.main_phrase (выбранный кластер)
    required: true
  - name: main_volume
    source: cluster.phrases[main].volume
    required: false
    default: "неизвестно"
  - name: main_difficulty
    source: cluster.phrases[main].difficulty
    required: false
    default: "неизвестно"
  - name: secondary_phrases
    source: cluster.phrases (кроме main), format "phrase1 (N/мес), phrase2 (M/мес)"
    required: false
    default: ""
  - name: cluster_volume
    source: cluster.total_volume
    required: false
    default: "неизвестно"
  - name: words_min
    source: dynamic from competitor analysis OR text_settings fallback
    required: true
    default: 1500
  - name: words_max
    source: dynamic from competitor analysis OR text_settings fallback
    required: true
    default: 2500
  - name: competitor_analysis
    source: AI summary of Firecrawl /scrape results (топ-3 конкурентов)
    required: false
    default: ""
  - name: competitor_gaps
    source: AI-detected topics missing from all competitors
    required: false
    default: ""
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
  - name: text_style
    source: text_settings.style (тональность текста)
    required: false
    default: "Информативный"
  - name: niche_type
    source: detect_niche(specialization) → medical|legal|finance|realestate|auto|beauty|food|education|it|travel|sport|children|pets|construction|general
    required: false
    default: "general"
  - name: current_date
    source: datetime.now().strftime("%B %Y")
    required: true
  - name: lsi_keywords
    source: DataForSEO related keywords
    required: false
    default: ""
  - name: internal_links
    source: Firecrawl /map (platform_connections.credentials.internal_links)
    required: false
    default: ""
  - name: prices_excerpt
    source: categories.prices (первые 10 позиций)
    required: false
    default: ""
  - name: serper_questions
    source: Serper "People Also Ask" — random 3 of N (anti-cannibalization, не первые 3)
    required: false
    default: ""
  - name: images_count
    source: image_settings.count (сколько изображений в статье, для images_meta)
    required: true
    default: 4
  - name: text_color
    source: site_brandings.colors.text
    required: false
    default: "#333333"
  - name: accent_color
    source: site_brandings.colors.accent
    required: false
    default: "#0066cc"
```

#### Динамическая длина статьи

Если данные конкурентов доступны (шаг 3 пайплайна), длина определяется автоматически:

```python
import statistics

def calculate_target_length(
    competitor_word_counts: list[int],
    text_settings: dict,
) -> tuple[int, int]:
    """Calculate target article length from competitor analysis."""
    if not competitor_word_counts:
        return text_settings.get("words_min", 1500), text_settings.get("words_max", 2500)

    median_words = int(statistics.median(competitor_word_counts))
    target_min = max(1500, int(median_words * 1.1))   # +10% vs median competitor
    target_max = min(5000, target_min + 500)           # cap at 5000 words
    return target_min, target_max
```

Без данных конкурентов — fallback на `text_settings` категории (default 1500-2500).

#### Anti-cannibalization (уникальность между пользователями)

Два пользователя в одной нише + городе получат одинаковые кластеры и Serper-данные.
Без защиты — Google увидит два почти идентичных текста, оба проиграют.

**Механизмы уникализации (уже в промпте):**
1. **System prompt** явно требует: "Пиши уникально под ЭТУ компанию, упоминай конкретные преимущества, цены, кейсы"
2. **`prices_excerpt`** — конкретные цены компании (у конкурента другие)
3. **`advantages`** — уникальные преимущества
4. **`company_name`** + `city` — привязка к бренду
5. **`branding_colors`** — визуальная уникальность

**Дополнительные меры:**
- `serper_questions`: random 3 of N (не первые 3) → разные FAQ-секции у разных пользователей
- `temperature: 0.6` (не 0) → вариативность, но с акцентом на точность
- При автопубликации: timestamp-seed для random → воспроизводимость при retry

**P2 (Phase 11+):** Content similarity check — контент-хеш (simhash/minhash) готовых статей
→ при >70% совпадении с существующей публикацией того же кластера → предупреждение
"Статья похожа на ранее опубликованную. Рекомендуем переформулировать."
Хранение: `publication_logs.content_hash BIGINT` (simhash).

**Решено (Phase 10.1):** Web Research step — выделенный шаг исследования через Perplexity Sonar Pro.
Вместо встраивания web search в Critique — выделенный Research step (шаг 2b), результат которого
передаётся во ВСЕ три AI-шага (Outline, Expand, Critique) как `<<current_research>>`.
Это даёт актуальные факты 2025-2026 уже на этапе планирования, а не только при проверке.
Подробности: research_v1.yaml (§3.10), JSON Schema, Redis кеш 7 дней, graceful degradation (E53).

#### Image SEO

Google Images = 20-30% трафика для коммерческих ниш. Без alt-тегов с ключевыми фразами этот трафик теряется.

**JSON-ответ AI включает `images_meta`:**
```json
{
  "images_meta": [
    {
      "alt": "Кухня на заказ из массива дуба в современном стиле — компания МебельПро",
      "filename": "kuhnya-na-zakaz-massiv-duba",
      "figcaption": "Кухня из массива дуба с фурнитурой Blum — от 180 000 руб."
    }
  ]
}
```

**Использование при публикации на WordPress:**
- `filename` → имя файла при загрузке через WP REST Media API (`kuhnya-na-zakaz-massiv-duba.webp`)
- `alt` → `alt_text` при загрузке media (WP REST API field)
- `figcaption` → `<figcaption>` в HTML, также `caption` в WP media
- `content_html` содержит `<figure><img src='{{IMAGE_N}}' ...>` — placeholder заменяется на WP attachment URL

**Формат изображений:** Все изображения конвертируются в WebP перед загрузкой (Pillow/sharp).
Если исходный формат PNG (Gemini) → `PIL.Image.save(format='webp', quality=85)`.

#### Себестоимость одной статьи (полный пайплайн, multi-step v7)

| Операция | Сервис | Стоимость | Этап |
|----------|--------|-----------|------|
| Ключевые фразы (разовая на категорию) | DataForSEO suggestions + related | ~$0.003/запрос × 2 | Создание категории |
| Обогащение volume/difficulty (разовое) | DataForSEO enrich | ~$0.02/200 фраз | Создание категории |
| Кластеризация (разовая) | DeepSeek v3.2 | ~$0.001 | Создание категории |
| Serper search | Serper | ~$0.001 | На статью |
| **Web Research** | **Perplexity Sonar Pro** | **~$0.01** | **На статью (кеш 7д)** |
| Скрейпинг конкурентов (3 URL) | Firecrawl /scrape | $0.003 | На статью |
| Outline (шаг 5) | DeepSeek V3.2 | ~$0.01 | На статью |
| Expand (шаг 6) | Claude 4.5 Sonnet | ~$0.12 | На статью |
| Conditional critique (шаг 8, ~30%) | DeepSeek V3.2 | ~$0.02 × 30% = $0.006 avg | На статью |
| Генерация 4 изображений | OpenRouter (Gemini) | ~$0.12-0.20 | На статью |
| WebP-конвертация + загрузка | CPU + Supabase Storage | ~$0 | На статью |
| **Итого за статью** | | **~$0.27-0.35** (avg ~$0.31) | |

При цене 320 токенов = 320 руб (~$3.50) → маржинальность **~91%**.
Ключевые фразы амортизируются по всем статьям категории (разовая операция).
Multi-step + research добавляет ~$0.03 к стоимости one-shot, но значительно повышает качество и актуальность.
Research кешируется 7 дней — при частой публикации одного кластера amortized cost ~$0.005.

#### Параллельный пайплайн (оптимизация latency)

Без оптимизации waterfall: ~75-125 секунд. С параллелизмом: ~40-70 секунд.

```python
async def generate_article_pipeline(cluster, category, project, connections):
    """Full article generation pipeline with parallel stages + research."""

    # Stage 1: Serper + Research ПАРАЛЛЕЛЬНО
    serper_task = serper.search(cluster.main_phrase)               # ~2с
    research_task = preview._fetch_research(                       # ~5-15с
        main_phrase=cluster.main_phrase,
        specialization=category.specialization,
        company_name=project.company_name,
    )
    serper_result, research_data = await asyncio.gather(
        serper_task, research_task, return_exceptions=True,
    )
    # Graceful degradation: research failure → empty context (E53)
    if isinstance(research_data, Exception):
        log.warning("research_failed", error=str(research_data))
        research_data = None
    current_research = format_research_for_prompt(research_data, step="expand")  # -> str or ""

    # Stage 2: Firecrawl scrape (параллельно 3 URL) + keyword data (уже в БД)
    top3_urls = [r["link"] for r in serper_result.organic[:3]]
    competitor_pages = await asyncio.gather(                       # ~5с (параллельно)
        *[firecrawl.scrape_content(url) for url in top3_urls],
        return_exceptions=True,
    )
    valid_pages = [p for p in competitor_pages if isinstance(p, ScrapeResult)]

    # Stage 3: Анализ конкурентов + dynamic length
    words_min, words_max = calculate_target_length(
        [p.word_count for p in valid_pages], category.text_settings
    )
    # summarize_competitors / detect_gaps — программные функции в articles.py:
    # summarize_competitors: объединяет headings + summary каждого конкурента в текст для промпта
    # detect_gaps: сравнивает headings конкурентов, находит темы покрытые <2 из 3 конкурентов
    competitor_analysis = summarize_competitors(valid_pages)  # -> str (для <<competitor_analysis>> в промпте)
    competitor_gaps = detect_gaps(valid_pages)                # -> str (для <<competitor_gaps>> в промпте)

    # Stage 4: Текст и изображения ПАРАЛЛЕЛЬНО
    # research_data передаётся в ArticleService.generate() → per-step formatting:
    # - Outline: format_research_for_prompt(data, "outline") — для планирования разделов
    # - Expand: format_research_for_prompt(data, "expand") — приоритизация при противоречиях
    # - Critique: format_research_for_prompt(data, "critique") — верификация фактов
    text_task = asyncio.create_task(
        article_service.generate(
            ..., research_data=research_data,  # raw dict, formatted per-step internally
        )
    )
    images_task = asyncio.create_task(
        orchestrator.generate_images(cluster.main_phrase, category.image_settings)
    )
    text_result, images_result = await asyncio.gather(            # ~30-60с (параллельно)
        text_task, images_task, return_exceptions=True,
    )

    # Stage 5: Пост-обработка (WebP, upload, Telegraph)
    # ...
```

**Ключевой инсайт:** Research и Serper запускаются параллельно на Stage 1. Research (~5-15с) завершается
к началу Firecrawl scraping, не добавляя латентности к pipeline (Firecrawl+Analysis занимают ~6с).

**Timeline:**

```text
Sequential:  Serper(2с) → Research(10с) → Firecrawl(15с) → Analysis(1с) → Text(45с) → Images(30с) → Upload(3с) = 106с
Parallel:    [Serper(2с) || Research(10с)] → Firecrawl(5с) → Analysis(1с) → [Text(45с) || Images(30с)] → Upload(3с) = 64с
              ↑ параллельно ↑                                                ↑ параллельно ↑
```

С progress indicator (F34 streaming): пользователь видит "Анализирую конкурентов... Пишу статью... Генерирую изображения..." — нормальный UX.

#### Image-text reconciliation (Stage 5)

Текст и изображения генерируются параллельно. После завершения обоих — reconciliation:

```python
def reconcile_images(
    text_result: ArticleResult,       # содержит images_meta[], content_markdown с {{IMAGE_N}}
    images_result: list[bytes | Exception],  # base64-decoded images
) -> tuple[str, list[ImageUpload]]:
    """Reconcile AI text images_meta with generated images."""
    meta = text_result.images_meta          # [{alt, filename, figcaption}, ...]
    images = [img for img in images_result if isinstance(img, bytes)]

    # Case 1: len(images) == len(meta) — perfect match
    # Case 2: len(images) < len(meta) — trim meta to match images count
    # Case 3: len(images) > len(meta) — use generic alt/filename for extras
    # Case 4: len(images) == 0 — publish without images (E34)

    uploads = []
    for i, img_bytes in enumerate(images):
        m = meta[i] if i < len(meta) else {
            "alt": f"{text_result.title} — изображение {i+1}",
            "filename": f"{slugify(text_result.title)}-{i+1}",
            "figcaption": "",
        }
        processed = post_process_image(Image.open(BytesIO(img_bytes)))  # sharpen + contrast
        webp_bytes = convert_to_webp(processed)  # PIL → WebP quality=85
        uploads.append(ImageUpload(
            data=webp_bytes,
            filename=f"{m['filename']}.webp",
            alt_text=m["alt"],
            caption=m["figcaption"],
        ))

    # Replace {{IMAGE_N}} placeholders in content_markdown BEFORE Markdown→HTML
    markdown = text_result.content_markdown
    for i, upload in enumerate(uploads):
        markdown = markdown.replace(f"{{{{IMAGE_{i+1}}}}}", upload.wp_url or "")
    # Remove unreplaced image placeholders (if images < expected)
    markdown = re.sub(r"!\[[^\]]*\]\(\{\{IMAGE_\d+\}\}[^)]*\)", "", markdown)

    return markdown, uploads
```

**Правила reconciliation:**
| Ситуация | Действие |
|----------|----------|
| images == meta | 1:1 маппинг по индексу |
| images < meta | Лишние meta отбрасываются, unreplaced {{IMAGE_N}} удаляются из HTML |
| images > meta | Для лишних images — generic alt/filename из title |
| images == 0 | Публикация без изображений (E34), возврат 30×N токенов за изображения |
| meta == 0 (AI не вернул) | Generic alt/filename для всех images |

**WebP-конвертация:** `PIL.Image.open(BytesIO(png_bytes)).save(buf, format='webp', quality=85)`.
При ошибке конвертации — fallback на PNG (E33).

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
    source: cluster.main_phrase (из выбранного кластера, см. §6.1)
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

### Пример: keywords_cluster.yaml

> **Data-first подход:** Сначала DataForSEO даёт реальные фразы из поисковых систем,
> затем AI кластеризует и дополняет. Это инверсия прежнего подхода "AI генерирует →
> DataForSEO валидирует", который давал 30-40% фраз с нулевым объёмом.

#### Пайплайн генерации ключевых фраз (5 шагов)

```
Шаг 1. DataForSEO keyword_suggestions(seed=specialization+city+products)
        → 200+ РЕАЛЬНЫХ фраз, которые люди ищут
Шаг 2. DataForSEO related_keywords(seed=top-10 фраз из шага 1)
        → расширение семантики (ещё ~100 фраз)
Шаг 3. AI кластеризация (keywords_cluster.yaml):
        → группировка фраз по поисковому интенту
        → "главная фраза" + "дополнительные" в каждом кластере
        → добавление узкоспециальных фраз, которых нет в DataForSEO
Шаг 4. DataForSEO enrich_keywords(финальный список)
        → volume, difficulty, CPC для каждой фразы
Шаг 5. Пользователь видит кластеры (не отдельные фразы):
        "Кухни на заказ" (4 фразы, суммарно 26,500/мес, сложность: средняя)
```

**Стоимость:** keyword_suggestions = $0.0015/запрос, related_keywords = $0.0015/запрос,
enrich = $0.0001/фраза. Итого для 200 фраз: ~$0.025 (~2.3 руб). Бесплатно для пользователя.

```yaml
meta:
  task_type: keywords
  version: v3
  model_tier: budget
  max_tokens: 6000
  temperature: 0.3

system: |
  Ты — SEO-специалист. Работай на <<language>>.
  Задача: кластеризовать реальные поисковые фразы по интенту и дополнить семантику.

user: |
  Вот <<raw_count>> реальных поисковых фраз из DataForSEO для бизнеса:
  - Компания: <<company_name>> (<<specialization>>)
  - Товары/услуги: <<products>>
  - География: <<geography>>

  Реальные фразы (с объёмами):
  <<raw_keywords_json>>

  Задачи:
  1. Сгруппируй фразы по поисковому интенту (фразы с одинаковым интентом = один кластер).
     Критерий: если Google показал бы одинаковые результаты — это один кластер.
  2. Для каждого кластера определи главную фразу (максимальный volume).
  3. Добавь до <<extra_count>> узкоспециальных фраз, которых нет в списке DataForSEO,
     но которые релевантны бизнесу. Пометь их как "ai_suggested": true.
  4. Определи тип кластера: "article" (информационный, подходит для статьи) или
     "product_page" (транзакционный, не подходит для статьи — только landing/каталог).

  Формат ответа — JSON:
  {
    "clusters": [
      {
        "cluster_name": "Кухни на заказ Москва",
        "cluster_type": "article",
        "main_phrase": "кухни на заказ москва",
        "phrases": [
          {"phrase": "кухни на заказ москва", "ai_suggested": false},
          {"phrase": "заказать кухню в москве", "ai_suggested": false},
          {"phrase": "кухни под заказ москва цены", "ai_suggested": false},
          {"phrase": "кухни на заказ от производителя москва", "ai_suggested": true}
        ]
      }
    ]
  }

variables:
  - name: raw_count
    source: len(DataForSEO results)
    required: true
  - name: raw_keywords_json
    source: DataForSEO keyword_suggestions + related_keywords (JSON)
    required: true
  - name: extra_count
    source: ceil(quantity * 0.15)
    required: true
    default: 30
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

#### Структура кластера в categories.keywords (JSONB)

После кластеризации `categories.keywords` хранит массив **кластеров**, а не отдельных фраз:

```json
[
  {
    "cluster_name": "Кухни на заказ Москва",
    "cluster_type": "article",
    "main_phrase": "кухни на заказ москва",
    "total_volume": 26500,
    "avg_difficulty": 45,
    "phrases": [
      {"phrase": "кухни на заказ москва", "volume": 12400, "difficulty": 52, "cpc": 1.2, "intent": "commercial", "ai_suggested": false},
      {"phrase": "заказать кухню в москве", "volume": 8100, "difficulty": 44, "cpc": 1.0, "intent": "commercial", "ai_suggested": false},
      {"phrase": "кухни под заказ москва цены", "volume": 3200, "difficulty": 38, "cpc": 0.9, "intent": "commercial", "ai_suggested": false},
      {"phrase": "кухни на заказ от производителя москва", "volume": 2800, "difficulty": 41, "cpc": 1.1, "intent": "commercial", "ai_suggested": true}
    ]
  },
  {
    "cluster_name": "Как выбрать кухню",
    "cluster_type": "article",
    "main_phrase": "как выбрать кухню",
    "total_volume": 9800,
    "avg_difficulty": 28,
    "phrases": [...]
  }
]
```

**Обратная совместимость:** Если `keywords[0]` содержит `"phrase"` без `"cluster_name"` — это
legacy-формат (плоский список). Код должен поддерживать оба формата (Phase 10 миграция).

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

## 6. Стратегия ротации кластеров ключевых фраз

> **Single source of truth** для ротации кластеров. Edge cases: E22 (все на cooldown → LRU),
> E23 (<3 кластеров → предупреждение), E36 (legacy формат → fallback на фразовую ротацию).
> Social posts: см. §6.1.

При автопубликации бот выбирает **кластер** для следующей статьи/поста.
Одна статья таргетирует весь кластер (main_phrase + secondary_phrases), а не одну фразу.

### Алгоритм

```
1. Получить все кластеры категории: categories.keywords (JSON-массив кластеров, см. §keywords_cluster.yaml)
2. Отфильтровать: только cluster_type = "article" (пропустить "product_page")
3. Отсортировать по перспективности: total_volume DESC, avg_difficulty ASC
4. Исключить кластеры, использованные за последние 7 дней:
   SELECT keyword FROM publication_logs
   WHERE category_id = ? AND created_at > now() - INTERVAL '7 days'
   (keyword хранит main_phrase кластера)
5. Выбрать первый доступный кластер (round-robin с приоритетом)
6. Если все кластеры использованы за 7 дней → взять LRU (самый давно использованный)
7. Если кластеров в категории < 3 → предложить пользователю:
   "Добавьте ещё ключевых фраз для разнообразия контента"
```

**Legacy-формат:** Если `keywords[0]` не содержит `cluster_name` — fallback на старый
алгоритм (ротация по отдельным фразам, volume DESC, difficulty ASC).

### Параметры

| Параметр | Значение | Обоснование |
|----------|----------|-------------|
| Cooldown-период | 7 дней | При 1 посте/день и 10 кластерах — каждый раз в 10 дней |
| Минимальный пул | 3 кластера | Ниже — предупреждение пользователю |
| Приоритет | total_volume DESC, avg_difficulty ASC | Сначала высокопотенциальные + лёгкие кластеры |
| Fallback | LRU (Least Recently Used) | Если все на cooldown — берём самый давний |
| Фильтр | cluster_type = "article" | Пропустить транзакционные кластеры (product_page) |

### Логирование

Каждая публикация записывает `keyword` (= main_phrase кластера) в `publication_logs`. Это позволяет:
- Отслеживать частоту использования каждого кластера
- Анализировать эффективность (CTR, позиции) по кластерам
- Автоматически исключать "выгоревшие" кластеры (будущая фича)
- `publication_logs.keyword` всегда = `cluster.main_phrase` (для обратной совместимости с индексом)

### 6.1 Social post rotation (TG/VK/Pinterest)

Социальные посты используют тот же пул кластеров, но с отличиями:

```
1. Фильтр: НЕТ фильтра по cluster_type — все кластеры пригодны для постов (и "article", и "product_page")
   Причина: для статей фильтруем только "article" (product_page не подходит для длинного контента),
   но для постов (100-300 слов) любой кластер работает.
   Если cluster_type="article" И cluster_type="product_page" оба есть — используются все.
2. Из выбранного кластера берётся ТОЛЬКО main_phrase (не весь кластер)
   → передаётся в social.yaml как <<keyword>>
3. Cooldown ОБЩИЙ по content_type: статья и пост по одному кластеру НЕ конфликтуют
   → cooldown 7 дней проверяется ОТДЕЛЬНО для article и social_post:
   SELECT keyword FROM publication_logs
   WHERE category_id = ? AND content_type = ? AND created_at > now() - INTERVAL '7 days'
4. Минимальный пул: 3 кластера (как для статей)
```

**Почему не весь кластер:** Пост в Telegram/VK — 100-300 слов. Невозможно органично
вписать 15 secondary_phrases кластера. Одна main_phrase достаточна для SMM-контента.

**Пример:** Кластер "Кухни из массива" (main_phrase = "кухня из массива дерева")
→ статья использует все 18 фраз кластера
→ пост использует только "кухня из массива дерева"
→ обе публикации записывают `keyword = "кухня из массива дерева"` в publication_logs,
  но с разным `content_type` → cooldown не пересекается.

---

## 7. Генерация изображений (Nano Banana / OpenRouter)

### 7.1 Модели

| Модель | Model ID | Назначение | Цена (input/output) |
|--------|----------|-----------|---------------------|
| Nano Banana 2 (Gemini 3.1 Flash Image) | `google/gemini-3.1-flash-image-preview` | Pro-качество на Flash-скорости (fallback) | $0.25/$1.50 per M tokens, $60/M image output |
| Nano Banana Pro (Gemini 3 Pro Image) | `google/gemini-3-pro-image-preview` | Премиум генерация (статьи, высокое качество) | $2/$12 per M tokens, $120/M image output |

**Fallback цепочка:** определяется через `MODEL_CHAINS["image"]` (§3.1): Nano Banana Pro → Nano Banana 2 → ошибка + возврат токенов.

### 7.2 API-запрос

```python
import openai

client = openai.AsyncOpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.environ["OPENROUTER_API_KEY"],
)

response = await client.chat.completions.create(
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

**Блочная привязка (block-aware generation):** Изображения генерируются не абстрактно "к статье", а привязаны к конкретным логическим блокам (H2-секциям) текста. Промпт каждого изображения строится из контекста ближайшего блока.

**Стратегия распределения по блокам:**

После генерации текста (шаг 6) статья разбивается на логические блоки (по H2/H3 заголовкам). Изображения распределяются равномерно по значимым блокам:

```python
def distribute_images(blocks: list[dict], images_count: int) -> list[int]:
    """Return block indices where images should be placed.
    
    blocks: [{heading: str, content: str, level: int}, ...]
    Returns: sorted list of block indices (0-based).
    """
    if images_count == 0 or not blocks:
        return []
    # Skip intro (block 0) and conclusion (last block) when possible
    candidate_blocks = list(range(len(blocks)))
    if len(candidate_blocks) > images_count + 1:
        candidate_blocks = candidate_blocks[1:-1]  # exclude intro/conclusion
    # Evenly spaced selection
    step = max(1, len(candidate_blocks) / images_count)
    indices = []
    for i in range(min(images_count, len(candidate_blocks))):
        idx = candidate_blocks[int(i * step)]
        indices.append(idx)
    return sorted(indices)
```

| images_count | Статья из 6 блоков | Позиции |
|-------------|-------------------|---------|
| 1 | Hero после первого H2 | [1] |
| 2 | Hero + середина | [1, 3] |
| 3 | Через ~2 блока | [1, 2, 3] |
| 4 | Равномерно | [1, 2, 3, 4] |

**Контекстный промпт:** Каждое изображение получает `block_context` — краткое содержание блока, к которому оно привязано. Это заменяет generic-промпт по теме статьи на точный контекст раздела.

**Стратегия вариативности:** Каждый запрос из N получает модифицированный промпт:
- `block_context`: текст H2-секции (первые 200 слов), к которой привязано изображение
- Изображение 1: базовый промпт + block_context (hero, 16:9)
- Изображение 2+: block_context + суффикс `"Покажи с другого ракурса: {angle}"`, где angle берётся из `image_settings.angles` (round-robin) или из предустановленного списка `["крупный план", "общий план", "детали", "в контексте использования"]`

**Выбор aspect_ratio:** Если `formats` содержит несколько значений (напр. `["16:9", "1:1"]`), каждый запрос получает следующий формат по round-robin. Если один формат — все изображения одинаковые. При Smart Aspect Ratio (§7.6): первое изображение = hero (16:9), остальные = content (4:3).

**Параллельная генерация:** Все N запросов запускаются одновременно через `asyncio.gather(return_exceptions=True)` — каждый бандл (block_context + image prompt) независим.

**Partial failure:** Если K из N изображений успешны (K >= 1) — продолжить с K изображениями, перераспределить оставшиеся по блокам, предупредить: "Сгенерировано {K} из {N} изображений". Если все N провалились — fallback на следующую модель из `MODEL_CHAINS["image"]`. Если вся цепочка исчерпана — возврат 30*N токенов, уведомление об ошибке.

### 7.5 Промпт-шаблон (image.yaml)

```yaml
meta:
  task_type: image
  version: v1
  model_tier: premium       # premium → gemini-3-pro, budget → gemini-2.5-flash
  max_tokens: 4000

user: |
  Сгенерируй изображение для <<content_type>> на тему "<<keyword>>".
  <% if block_context %>
  Контекст раздела статьи, к которому привязано изображение:
  <<block_context>>
  <% endif %>
  
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

  Negative: watermark, logo, text overlay, blurry, low resolution, distorted faces,
  extra fingers, deformed hands, stock photo watermark, ugly, oversaturated.
  <% if niche_style %>Стиль ниши: <<niche_style>>.<% endif %>

  <% if image_number %>
  Это изображение <<image_number>> из <<total_images>>.
  Вариация: <<variation_hint>>.
  <% endif %>

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
  - name: image_number
    source: индекс текущего изображения (1-based) при count > 1
    required: false
    default: ""
  - name: total_images
    source: image_settings.count
    required: false
    default: ""
  - name: variation_hint
    source: round-robin из image_settings.angles или ["крупный план", "общий план", "детали", "в контексте использования"]
    required: false
    default: ""
  - name: block_context
    source: первые 200 слов H2-секции, к которой привязано изображение (§7.4.1 distribute_images)
    required: false
    default: ""
  - name: niche_style
    source: NICHE_IMAGE_STYLES[detect_niche(specialization)]
    required: false
    default: ""
```

#### Niche Image Style Presets

```python
NICHE_IMAGE_STYLES: dict[str, str] = {
    "medical":      "Clean clinical setting, soft natural lighting, professional medical environment",
    "legal":        "Professional office, dark wood tones, formal corporate atmosphere",
    "finance":      "Modern fintech aesthetic, clean lines, blue and white tones",
    "realestate":   "Real estate photography, wide angle, HDR style, bright and airy",
    "food":         "Food photography, shallow depth of field, warm lighting, appetizing presentation",
    "beauty":       "Beauty/lifestyle photography, soft focus, pastel tones, studio lighting",
    "construction": "Industrial photography, construction site, yellow/grey tones, wide angle",
    "auto":         "Automotive photography, dynamic angles, studio lighting, reflective surfaces",
}
```

#### Image Post-Processing (Pillow)

После генерации, перед WebP-конвертацией — автоматическое улучшение:

```python
from PIL import Image, ImageEnhance, ImageFilter

def post_process_image(img: Image.Image) -> Image.Image:
    """Sharpen + slight contrast/color boost for AI-generated images."""
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=2))
    img = ImageEnhance.Contrast(img).enhance(1.05)
    img = ImageEnhance.Color(img).enhance(1.08)
    return img
```

#### Smart Aspect Ratio

Вместо одного формата для всех изображений — позиционная логика:

| Позиция | Aspect Ratio | Назначение |
|---------|:------------:|------------|
| Image 1 (hero) | 16:9 | Featured image, WP thumbnail |
| Image 2-3 (content) | 4:3 | Inline content images |
| Image 4+ (detail) | 1:1 | Product shots, details |

При `image_settings.formats` с одним значением — используется оно для всех.

### 7.6 Стоимость

| Контент | Модель | ~Токенов OpenRouter | ~USD | Внутренних токенов |
|---------|--------|--------------------:|-----:|-------------------:|
| 1 изображение (соцсеть) | Nano Banana | ~500 output | ~$0.015 | 30 |
| 4 изображения (статья) | Nano Banana Pro | ~2000 output | ~$0.24 | 120 |

---

## 7a. Web Research Pipeline (Perplexity Sonar Pro)

Выделенный шаг исследования через Perplexity Sonar Pro для актуализации данных в статьях.
Sonar Pro — модель с встроенным веб-поиском, возвращает факты с источниками (citations).

### 7a.1 Модель и маршрутизация

```python
MODEL_CHAINS["article_research"] = ["perplexity/sonar-pro"]
# Без fallback — Sonar Pro единственная модель с нативным web search.
# При недоступности — graceful degradation (E53): pipeline продолжает без research.

# Sonar Pro параметры:
# - Встроенный web search (НЕ plugin, НЕ :online suffix)
# - Поддерживает JSON Schema structured outputs
# - $3/M input, $15/M output, $5/1K search queries
# - context: 200K tokens
# - search_context_size: "high" для максимальной глубины
```

### 7a.2 JSON Schema для research response

```python
RESEARCH_SCHEMA: dict[str, Any] = {
    "name": "research_response",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string"},
                        "source": {"type": "string"},
                        "year": {"type": "string"},
                    },
                    "required": ["claim", "source", "year"],
                    "additionalProperties": False,
                },
            },
            "trends": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "trend": {"type": "string"},
                        "relevance": {"type": "string"},
                    },
                    "required": ["trend", "relevance"],
                    "additionalProperties": False,
                },
            },
            "statistics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string"},
                        "value": {"type": "string"},
                        "source": {"type": "string"},
                    },
                    "required": ["metric", "value", "source"],
                    "additionalProperties": False,
                },
            },
            "summary": {"type": "string"},
        },
        "required": ["facts", "trends", "statistics", "summary"],
        "additionalProperties": False,
    },
}
```

### 7a.3 Промпт (research_v1.yaml)

```yaml
meta:
  task_type: article_research
  version: v1
  model_tier: research
  max_tokens: 4000
  temperature: 0.3

system: |
  You are a research assistant specializing in finding CURRENT, VERIFIED data.
  Focus on data from 2025-2026. For each fact, provide the source.
  If conflicting data found, note the contradiction.
  NEVER fabricate data. If unsure, say "data not found".
  Language: <<language>>.

user: |
  Research the following topic for a professional article:

  Topic: "<<main_phrase>>"
  Industry: <<specialization>>
  Geography: <<geography>>
  Company context: <<company_name>> (<<company_description_short>>)

  Find:
  1. Current statistics and market data (2025-2026)
  2. Recent trends and developments
  3. Key facts relevant to the topic
  4. Regulatory changes (if applicable)

  Return JSON with facts, trends, statistics, and a brief summary.

variables:
  - name: main_phrase
    required: true
  - name: specialization
    required: true
  - name: geography
    required: false
    default: "Россия"
  - name: company_name
    required: true
  - name: company_description_short
    required: false
    default: ""
  - name: language
    required: true
    default: "ru"
```

### 7a.4 Кеширование

Research-данные кешируются в Redis с TTL 7 дней (по умолчанию):

```python
# Ключ: research:{md5(main_phrase:specialization)[:12]}
# TTL: 7 дней (604800 сек), настраиваемый в будущем через category.text_settings
cache_input = f"{main_phrase}:{specialization}".lower()
cache_key = f"research:{hashlib.md5(cache_input.encode()).hexdigest()[:12]}"

# Check cache
cached = await redis.get(cache_key)
if cached:
    return ResearchData.model_validate_json(cached)

# Fetch from Sonar Pro
result = await orchestrator.generate(research_request)
research = ResearchData.model_validate_json(result.text)

# Cache result
await redis.set(cache_key, research.model_dump_json(), ex=604800)
```

### 7a.5 Форматирование для промптов

Research-данные форматируются по-разному для каждого AI-шага:

```python
def format_research_for_prompt(research: ResearchData | None, step: str) -> str:
    """Format research data for insertion into AI prompts."""
    if not research:
        return ""

    parts = []
    if research.facts:
        facts_text = "\n".join(
            f"- {f.claim} (источник: {f.source}, {f.year})" for f in research.facts
        )
        parts.append(f"Актуальные факты:\n{facts_text}")

    if research.trends:
        trends_text = "\n".join(f"- {t.trend}" for t in research.trends)
        parts.append(f"Тренды:\n{trends_text}")

    if research.statistics:
        stats_text = "\n".join(
            f"- {s.metric}: {s.value} ({s.source})" for s in research.statistics
        )
        parts.append(f"Статистика:\n{stats_text}")

    if research.summary:
        parts.append(f"Резюме: {research.summary}")

    context = "\n\n".join(parts)

    # Different instructions per step
    if step == "outline":
        return f"<CURRENT_RESEARCH>\n{context}\n\nИспользуй эти данные для планирования разделов статьи.\n</CURRENT_RESEARCH>"
    elif step == "expand":
        return f"<CURRENT_RESEARCH>\n{context}\n\nПриоритизируй эти данные при противоречиях с собственными знаниями. Дополняй своей экспертизой где research не покрывает.\n</CURRENT_RESEARCH>"
    elif step == "critique":
        return f"<CURRENT_RESEARCH>\n{context}\n\nИспользуй для верификации фактов в статье. Отмечай расхождения.\n</CURRENT_RESEARCH>"
    return ""
```

### 7a.6 Graceful Degradation (E53)

При недоступности Sonar Pro — pipeline продолжает без research-данных:
- `current_research = ""` → Jinja2 conditional block не рендерится
- Логирование: `research_skipped`, причина в metadata
- Статья генерируется на основе знаний модели + Serper + Firecrawl (как было до Research step)
- **НЕ является ошибкой** — предупреждение в логах, не уведомление пользователю

### 7a.7 Себестоимость Research step

| Параметр | Значение |
|----------|----------|
| Input tokens (prompt + search) | ~1000 |
| Output tokens (JSON response) | ~500-1500 |
| Search queries | ~1-3 |
| Стоимость за запрос | ~$0.005-0.015 (avg $0.01) |
| Redis cache hit rate | ~30-50% (для повторяющихся кластеров) |
| Amortized cost per article | ~$0.005-0.01 |

---

## 8. Контракты внешних сервисов

### 8.1 FirecrawlClient

> **API:** Firecrawl v2 (`https://api.firecrawl.dev/v2`). Вызовы через native httpx (не SDK).
> **Кредитная система:**
> - `/v2/scrape` = 1 кредит/page
> - `/v2/map` = 1 кредит за 5000 URL
> - `/v2/extract` = ~5 кредитов/URL (1 scrape + 4 JSON mode LLM)
> - `/v2/search` = 2 кредита за 10 результатов + 1 кредит/scraped page

```python
@dataclass
class ScrapeResult:
    url: str
    markdown: str          # Full page content as markdown
    summary: str | None    # AI-сокращённый текст (~3% от оригинала)
    word_count: int
    headings: list[dict]   # [{level: 2, text: "..."}] -- H1-H3
    meta_title: str | None
    meta_description: str | None

@dataclass
class BrandingResult:
    colors: dict       # {background, text, accent, primary, secondary}
    fonts: dict        # {heading, body}
    logo_url: str | None

@dataclass
class MapResult:
    urls: list[dict]   # [{url, title?, description?}]
    total_found: int

@dataclass
class ExtractResult:
    data: dict         # Структурированные данные по JSON schema
    source_url: str

@dataclass
class SearchResult:
    url: str
    title: str
    description: str
    markdown: str | None   # Scraped content (если запрошен)

class FirecrawlClient:
    async def scrape_content(self, url: str) -> ScrapeResult | None: ...
    async def scrape_branding(self, url: str) -> BrandingResult | None: ...
    async def map_site(self, url: str, limit: int = 5000) -> MapResult | None: ...
    async def extract(self, urls: list[str], prompt: str, schema: dict | None) -> ExtractResult | None: ...
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]: ...
```

#### Методы

**`scrape_content(url)`** — анализ конкурентов при генерации статей.
POST `/v2/scrape` с `formats: ['markdown', 'summary']`, `onlyMainContent: true`.
Возвращает markdown + AI-summary + структуру заголовков + word count.
Стоимость: 1 кредит/страница. `summary` бесплатный (входит в кредит).

Используется в пайплайне генерации статей (article_v7, шаг 3):
```python
# Scrape top-3 competitor URLs from Serper results
competitor_pages = await asyncio.gather(
    *[firecrawl.scrape_content(url) for url in serper_top3_urls],
    return_exceptions=True,
)
valid_pages = [p for p in competitor_pages if isinstance(p, ScrapeResult)]
```

**`scrape_branding(url)`** — извлечение брендинга при подключении WP-сайта.
Использует `/v2/extract` с LLM и JSON schema для реального извлечения CSS-цветов,
шрифтов и логотипа (вместо hardcoded fallback). LLM анализирует HTML/CSS страницы.
Стоимость: ~5 кредитов. Результат → `site_brandings` таблица.
Fallback-значения при частичных данных: `#ffffff` (bg), `#333333` (text), `#0066cc` (accent).

**`map_site(url, limit=5000)`** — быстрое обнаружение внутренних ссылок.
POST `/v2/map`. Возвращает до 5000 URL за 2-3 секунды.
Стоимость: **1 кредит за весь вызов** (не за страницу).

> **Почему `/map` вместо `/crawl`:** Для internal links нужны только URL + title.
> `/map` в 100 раз дешевле (1 кредит vs 100) и в 10 раз быстрее (2-3с vs 30с+).

```python
result = await firecrawl.map_site(url="https://client-site.ru", limit=5000)
internal_links = [item["url"] for item in result.urls]
```

**`extract(urls, prompt, schema)`** — структурированное LLM-извлечение данных.
POST `/v2/extract` с urls, prompt и опциональной JSON schema.
Firecrawl скрейпит страницу, пропускает через LLM, возвращает структурированный JSON.
Стоимость: ~5 кредитов/URL. Timeout: 60 секунд.

**`search(query, limit=5)`** — поиск + скрейп в одном вызове.
POST `/v2/search` с `scrapeOptions: {formats: ['markdown'], onlyMainContent: true}`.
Стоимость: 2 кредита/10 результатов + 1 кредит/scraped page.
Возвращает `list[SearchResult]` (пустой при ошибке).

> **Serper vs Firecrawl search:** Firecrawl search заменяет Serper + scrape в 1 API-вызов.
> Но НЕ предоставляет People Also Ask (PAA) — для PAA по-прежнему нужен Serper.
> В article pipeline используем оба: Serper для PAA + Firecrawl scrape для контента.

**Retry:** 3 попытки, exponential backoff (1s, 3s, 9s). При недоступности → E15.

**Кеширование:**
- `scrape_branding` — Redis 7 дней (ключ: `branding:{project_id}`)
- `scrape_content` — Redis 24 часа (ключ: `competitor:{md5(url)}`)
- `map_site` — Redis 14 дней (ключ: `map:{project_id}`)

#### Перекраулинг внутренних ссылок (P2, Phase 11+)

Внутренние ссылки устаревают: через 3 месяца новые страницы не учтены, удалённые → 404.
Решение: QStash cron раз в 14 дней вызывает `/api/recrawl` для каждого WP-подключения.

```
QStash CRON: 0 3 1,15 * * → POST /api/recrawl
  → Для каждого active WP connection: firecrawl.map_site(url, limit=5000)
  → Обновить platform_connections.credentials.internal_links
  → Стоимость: 1 кредит = $0.001/сайт/2 недели (было: ~100 кредитов = $0.08)
```

#### Будущее: Firecrawl `/agent` (v3+)

> Firecrawl Agent (Spark 1) — автономный поиск и извлечение данных без указания URL.
> Потенциал для standalone-анализа конкурентов (v3): один запрос вместо ручного пайплайна.
> Пока в Research Preview, динамическая цена, всегда списывается. Оценить при стабилизации API.

#### Будущее: Firecrawl `changeTracking` (v3, F45)

> Параметр `changeTracking: true` на `/scrape` отслеживает изменения страниц.
> Готовое решение для F45 (мониторинг контента) — не нужен свой diff-движок.
> Обходит кеш, стоимость: 1 кредит/проверку.

### 8.2 DataForSEOClient

```python
@dataclass
class KeywordData:
    phrase: str
    volume: int          # Запросов/мес
    difficulty: int      # 0-100
    cpc: float           # Стоимость клика в USD
    intent: str          # commercial, informational

@dataclass
class KeywordSuggestion:
    phrase: str
    volume: int
    cpc: float
    competition: float   # 0.0-1.0

class DataForSEOClient:
    # Default location: Ukraine (2804). Russia (2643) is banned from all
    # DataForSEO services. Ukraine supports language_code="ru" and provides
    # the closest Russian-language keyword data.
    # Kazakhstan (2398) is an alternative with fewer results.
    _DEFAULT_LOCATION: int = 2804

    async def keyword_suggestions(
        self, seed: str, location_code: int = _DEFAULT_LOCATION, language_code: str = "ru", limit: int = 200,
    ) -> list[KeywordSuggestion]: ...

    async def related_keywords(
        self, seed: str, location_code: int = _DEFAULT_LOCATION, language_code: str = "ru", limit: int = 100,
    ) -> list[KeywordSuggestion]: ...

    async def enrich_keywords(
        self, phrases: list[str], location_code: int = _DEFAULT_LOCATION, language_code: str = "ru",
    ) -> list[KeywordData]: ...
```

**Data-first пайплайн (keywords_cluster.yaml):**
1. `keyword_suggestions(seed=specialization+city+products)` → 200+ реальных фраз
2. `related_keywords(seed=top-10 из шага 1)` → расширение семантики
3. AI кластеризация (см. keywords_cluster.yaml)
4. `enrich_keywords(all_phrases)` → volume, difficulty, CPC для финального списка

**API эндпоинты DataForSEO:**
- `keyword_suggestions`: POST `/v3/dataforseo_labs/google/keyword_suggestions/live`
- `related_keywords`: POST `/v3/dataforseo_labs/google/related_keywords/live`
- `enrich_keywords` (bulk): POST `/v3/keywords_data/google_ads/search_volume/live`

**Batch:** enrich — до 700 фраз за 1 запрос. suggestions/related — 1 seed за запрос.
**Стоимость (v3 API, актуально февр. 2026):** suggestions = ~$0.01/запрос, related = ~$0.01/запрос, enrich = $0.0001/фраза.
Полный пайплайн для 200 фраз: ~$0.04 (~3.6 руб). По-прежнему пренебрежимо.
**Retry:** 2 попытки. При недоступности → E03 (fallback: AI генерирует фразы "из головы", как в v1).

> **v2 API sunset:** 5 мая 2026. Наши эндпоинты уже на v3 — миграция не нужна.

#### Дополнительные методы (P2, Phase 11+)

**`search_intent(phrases)`** — классификация intent до 1000 фраз за запрос.
POST `/v3/dataforseo_labs/google/search_intent/live`. Стоимость: $0.001 + $0.0001/фраза.
Возвращает ground-truth intent (commercial, informational, navigational, transactional).
Потенциальное улучшение: заменить AI-угадывание intent в keywords_cluster.yaml → данные DataForSEO.

**`keyword_suggestions_for_url(url)`** — ключевики конкурента по URL.
POST `/v3/dataforseo_labs/google/keywords_for_site/live`. Стоимость: ~$0.01/запрос.
Полезно для standalone-анализа конкурентов (v3) — получить семантику конкурента без ручного ввода seed.

#### Rank Tracking (P2, Phase 11+)

```python
@dataclass
class RankResult:
    keyword: str
    position: int | None   # 1-100, None = not in top-100
    url: str | None        # URL страницы в выдаче
    checked_at: datetime

class DataForSEOClient:
    # ... existing methods ...

    async def check_rank(
        self, keyword: str, domain: str,
        location_code: int = _DEFAULT_LOCATION,  # 2804 = Ukraine
        language_code: str = "ru",
    ) -> RankResult: ...
```

**API эндпоинт:** POST `/v3/serp/google/organic/live/regular`
**Стоимость:** $0.002/проверка (полный SERP). С `stop_crawl_on_match: true` — $0.0006-0.001 (остановка при нахождении домена). 100 статей/неделю = $0.24-0.40/мес.
**Кеширование:** Redis 24ч (ключ: `rank:{md5(keyword+domain)}`).

**QStash cron:** Раз в неделю проверить все publication_logs со `status='success'` и `rank_checked_at` > 7 дней назад.
Обновить `rank_position` и `rank_checked_at`.

**Отображение пользователю:**
```
Статья "Кухни на заказ в Москве"
  Опубликована: 15 янв 2026
  Позиция: 34 → 12 (↑22 за 3 недели)
```

### 8.3 SerperClient

```python
@dataclass
class SerperResult:
    organic: list[dict]                  # [{title, link, snippet}]
    people_also_ask: list[dict[str, Any]]  # [{question, snippet, link}] — objects, NOT strings
    related_searches: list[str]

class SerperClient:
    async def search(self, query: str, num: int = 10, gl: str = "ru", hl: str = "ru") -> SerperResult: ...
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
