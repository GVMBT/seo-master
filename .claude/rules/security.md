---
paths:
  - "**/*.py"
---

# Security Rules

- Credentials: ТОЛЬКО Fernet encryption, ключ из env var ENCRYPTION_KEY
- SQL: параметризованные запросы ВСЕГДА (никаких конкатенаций)
- Env vars: НЕ хардкодить, НЕ логировать, НЕ коммитить
- Telegram webhook: верификация secret_token (docs/API_CONTRACTS.md §4.3)
- QStash webhook: верификация подписи (docs/API_CONTRACTS.md §1.3)
- Rate limits: Redis token-bucket (docs/API_CONTRACTS.md §4.1)
- User input: sanitize перед передачей в AI-промпты
- Admin: проверка role=='admin' через middleware, не в хендлерах
