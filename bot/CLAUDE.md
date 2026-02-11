# Модуль bot/ — Инициализация и Middleware

## main.py
- Запуск Aiogram webhook (НЕ polling)
- on_startup: создать клиенты (Supabase async, httpx.AsyncClient, Redis)
- on_shutdown: закрыть все клиенты
- set_webhook с secret_token из env TELEGRAM_WEBHOOK_SECRET
- allowed_updates: message, callback_query, pre_checkout_query

## config.py
- Pydantic Settings v2 с env-префиксами
- SecretStr для API-ключей (никогда не логируются)
- Все переменные из docs/API_CONTRACTS.md §4.2

## Middleware chain (строгий порядок — docs/ARCHITECTURE.md §2.1)
1. DBSessionMiddleware (outer) — инъекция data["db"], закрытие после обработки
2. AuthMiddleware (inner) — авторегистрация → data["user"], data["is_admin"]
3. ThrottlingMiddleware — Redis token-bucket: 30 msg/min per user
4. FSMInactivityMiddleware — проверка last_update_time, автосброс через 30 мин
5. LoggingMiddleware — correlation_id (UUID4), JSON-лог

## Пулы соединений (docs/ARCHITECTURE.md §2.2)
- Supabase: PgBouncer transaction mode, max 50 connections
- Upstash Redis: HTTP-based (stateless), без TCP-пула
- httpx.AsyncClient: shared, max_connections=20, keepalive=10, timeout=30s connect=5s

## Обработка ошибок
- Global error handler → Sentry capture + ERROR лог + "Произошла ошибка"
- FSM НЕ сбрасывается при ошибке (пользователь может повторить)
