# Модуль cache/ — Redis (Upstash)

## Пространства имён ключей (keys.py)
- fsm:{user_id} — FSM-состояние Aiogram (TTL: 86400с = 24ч)
- throttle:{user_id}:{action} — rate limiting (INCR + EXPIRE)
- publish_lock:{idempotency_key} — идемпотентность QStash (TTL 300с)
- branding:{project_id} — кеш Firecrawl branding (TTL 7 дней)
- serper:{md5(query)} — кеш Serper поиска (TTL 24ч)
- pinterest_auth:{nonce} — OAuth state (TTL 30 мин)

## Rate limits (docs/API_CONTRACTS.md §4.1)
- Генерация текста: 10/час
- Генерация изображений: 20/час
- Генерация ключевых фраз: 5/час
- Callback/message: 30/мин (anti-flood)
- Покупка токенов: 5/10мин
- Подключение платформы: 10/час
- API вебхуки QStash: 100/мин

## fsm_storage.py
- Aiogram RedisStorage совместимый с Upstash HTTP Redis
- Сериализация state.data в JSON
- last_update_time в state.data для FSMInactivityMiddleware
