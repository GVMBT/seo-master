# Модуль api/ — HTTP-эндпоинты для вебхуков

## Общие паттерны (api/__init__.py)
- require_qstash_signature — декоратор: Receiver.verify(body, signature, url)
  - Читает Upstash-Signature header, QStash current/next signing keys из settings
  - На успех: request["verified_body"] (parsed JSON), request["qstash_msg_id"]
  - На провал: 401 "Missing signature" / "Invalid signature" / "Malformed body"
- api/models.py — Pydantic v2 payload models: PublishPayload, CleanupPayload, NotifyPayload

## QStash SDK sync calls
The QStash Python SDK is synchronous. In api/health.py, calls are wrapped in `asyncio.to_thread()` to avoid
blocking the event loop. In services/scheduler.py, QStash schedule.create() and schedule.delete() are also
sync calls used inside async methods — these are short-lived network calls. For heavier checks (like
schedule.list() in health), always use `asyncio.to_thread()`.

## /api/publish (POST) — QStash автопубликация (Phase 9: IMPLEMENTED)
- @require_qstash_signature decorator
- Shutdown check: SHUTDOWN_EVENT.is_set() -> 503 + Retry-After: 60
- Идемпотентность: Redis NX lock by Upstash-Message-Id header (publish_lock:{msg_id}, 5 мин TTL)
- Backpressure: PUBLISH_SEMAPHORE(10) with 300s timeout -> 503 on timeout
- Post-semaphore shutdown check (double gate)
- Delegates to PublishService.execute(payload) -> PublishOutcome
- Notify user via bot.send_message if result.notify is True
- ВСЕГДА возвращать 200 (даже при бизнес-ошибке), иначе QStash повторит

## /api/cleanup (POST) — ежедневная очистка (Phase 9: IMPLEMENTED)
- @require_qstash_signature decorator
- Идемпотентность: Redis NX lock by Upstash-Message-Id (cleanup_lock:{msg_id}, 5 мин TTL)
- CleanupPayload validation: Pydantic model with `action: Literal["cleanup"]`, validated before execution
- Delegates to CleanupService.execute() -> CleanupResult
- Notifies users about refunded previews via bot.send_message (respects user.notify_balance preference)
- Returns: {status, expired, refunds, logs_deleted}

## /api/notify (POST) — уведомления (Phase 9: IMPLEMENTED)
- @require_qstash_signature decorator
- Идемпотентность: Redis NX lock by Upstash-Message-Id (notify_lock:{msg_id}, 5 мин TTL)
- Payload: NotifyPayload (type: low_balance | weekly_digest | reactivation)
- Delegates to NotifyService.build_*() -> list[(user_id, text)]
- _send_notifications(): TelegramRetryAfter retry, TelegramForbiddenError skip, 50ms spacing
- Returns: {status, type, sent, failed}

## /api/health (GET) — проверка (Phase 9: IMPLEMENTED)
- Public: {status: "ok", version: "2.0.0"} (no token or invalid token)
- Detailed (Bearer token): checks database, redis, openrouter, qstash
- QStash check: sync SDK call wrapped in asyncio.to_thread() to avoid blocking event loop
- Status: "ok" | "degraded" (non-critical fails) | "down" (db/redis fails)

## /api/yookassa (POST) — webhook (Phase 8)
- Верификация по IP-whitelist
- payment.succeeded → начисление + реферал
- payment.canceled → статус failed
- refund.succeeded → списание (баланс может быть отрицательным)

## /api/yookassa/renew (POST) — QStash → автопродление подписок
## /api/auth/pinterest (GET) — Pinterest OAuth redirect + callback
