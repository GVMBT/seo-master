# Модуль api/ — HTTP-эндпоинты для вебхуков

## /api/publish (POST) — QStash автопубликация
- Верификация подписи QStash (Receiver.verify) — docs/API_CONTRACTS.md §1.3
- Идемпотентность: Redis NX lock (publish_lock:{key}, 5 мин TTL)
- Проверка баланса → списание → генерация → валидация → публикация
- Валидация: длина >=500 символов, наличие H1 (WP), нет placeholder-текста
- ВСЕГДА возвращать 200 (даже при бизнес-ошибке), иначе QStash повторит
- Уведомление только если users.notify_publications = TRUE

## /api/cleanup (POST) — ежедневная очистка
- article_previews: status=draft AND expires_at < now() → expired
- Удалить Telegraph, вернуть токены (balance += tokens_charged)
- Записать token_expenses(refund), уведомить пользователя
- publication_logs: >90 дней → архивировать/удалить

## /api/notify (POST) — уведомления
- low_balance: balance < 100, ежедневно 10:00 MSK (notify_balance = TRUE)
- weekly_digest: активным за 30 дней, пн 09:00 (notify_news = TRUE)
- reactivation: неактивным 14+ дней, еженедельно

## /api/yookassa (POST) — webhook
- Верификация по IP-whitelist
- payment.succeeded → начисление + реферал
- payment.canceled → статус failed
- refund.succeeded → списание (баланс может быть отрицательным)

## /api/yookassa/renew (POST) — QStash → автопродление подписок
## /api/auth/pinterest (GET) — Pinterest OAuth redirect + callback
## /api/health (GET) — проверка: database, redis, openrouter, qstash
