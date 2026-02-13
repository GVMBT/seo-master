# Модуль bot/ — Инициализация и Middleware

## main.py
- Запуск Aiogram webhook (НЕ polling)
- on_startup: создать клиенты (Supabase async, httpx.AsyncClient, Redis)
- on_shutdown: закрыть все клиенты
- set_webhook с secret_token из env TELEGRAM_WEBHOOK_SECRET
- allowed_updates: message, callback_query, pre_checkout_query, my_chat_member

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

## Phase 9 wiring (bot/main.py)
- SHUTDOWN_EVENT: asyncio.Event — set on SIGTERM, checked by publish_handler before and after semaphore
- PUBLISH_SEMAPHORE: asyncio.Semaphore(10) — backpressure for concurrent auto-publish (ARCHITECTURE.md section 5.6)
- on_shutdown(): sets SHUTDOWN_EVENT, drains semaphore (waits up to timeout for all 10 permits), then cleans up
- dp.workflow_data["scheduler_service"]: SchedulerService (QStash management), used by scheduler router handlers
- app["scheduler_service"]: same instance, used by api handlers if needed
- API routes: /api/publish, /api/cleanup, /api/notify, /api/health — registered in create_app()

## bot/fsm_utils.py
- ensure_no_active_fsm(state) — auto-reset current FSM before entering new one (E29)
- _FSM_NAMES: human-readable Russian names for all 16 FSM classes
- Called at every FSM entry point before set_state()

## Обработка ошибок
- Global error handler → Sentry capture + ERROR лог + "Произошла ошибка"
- FSM НЕ сбрасывается при ошибке (пользователь может повторить)
