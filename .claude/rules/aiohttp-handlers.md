---
paths:
  - "api/**/*.py"
---

# aiohttp Webhook Handlers

## Архитектура хендлера (ОБЯЗАТЕЛЬНО)

Хендлер aiohttp.web — это ТОНКАЯ обёртка. Вся бизнес-логика в Service Layer.

```python
# ПРАВИЛЬНО:
async def handle_publish(request: web.Request) -> web.Response:
    body = await request.json()               # 1. Принять JSON
    payload = PublishPayload.model_validate(body)  # 2. Pydantic-валидация
    service = PublishService(request.app["http_client"], request.app["db"])
    result = await service.execute(payload)   # 3. Делегировать в сервис
    return web.json_response(result)          # 4. Вернуть результат

# ЗАПРЕЩЕНО:
async def handle_publish(request: web.Request) -> web.Response:
    body = await request.json()
    user = await db.get_user(body["user_id"])  # НЕТ — SQL в хендлере
    tokens = calc_cost(body)                    # НЕТ — бизнес-логика в хендлере
    await charge_balance(user, tokens)          # НЕТ — финансовая операция в хендлере
    ...
```

## HTTP-клиенты (КРИТИЧНО для производительности)

НИКОГДА не создавай `aiohttp.ClientSession` или `httpx.AsyncClient` внутри хендлера.
Используй shared-клиент из `request.app`:

```python
# ПРАВИЛЬНО:
http_client = request.app["http_client"]  # Создан один раз при startup

# ЗАПРЕЩЕНО:
async with aiohttp.ClientSession() as session:  # НЕТ — новый на каждый запрос
    await session.post(...)
```

Shared `http_client` инжектируется в `app` при startup (bot/main.py) и передаётся в сервисы.
Для aiogram-хендлеров — через `data["http_client"]` (DBSessionMiddleware).

## Чеклист для каждого хендлера в api/

- [ ] Хендлер <= 15 строк (без учёта docstring)
- [ ] Нет import из `services/`, `db/repositories/` кроме как для конструирования сервиса
- [ ] Нет прямых SQL-запросов
- [ ] Нет вычислений токенов, стоимости, баланса
- [ ] Нет создания ClientSession/AsyncClient
- [ ] Pydantic-модель для входящего payload
- [ ] Верификация подписи/IP ДО парсинга body (middleware или первая строка)
- [ ] Возвращает 200 даже при бизнес-ошибке (для QStash — иначе retry)
- [ ] structlog.get_logger() для логирования, не print()
