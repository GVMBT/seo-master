# Журнал интеграции bamboodom.ru blog v1.1 — финальное состояние

**Обновлено:** 24.04.2026 13:00 МСК
**Статус:** первая production-статья опубликована
**URL первой статьи:** https://bamboodom.ru/article.html?slug=wpc-paneli-ili-gibkaya-keramika-kakoy-material-vybrat-dlya-vashego-proekta

---

## Содержание

1. [Что работает сейчас](#что-работает-сейчас)
2. [История сессий](#история-сессий)
3. [Список файлов на сервере](#список-файлов-на-сервере)
4. [Следующие шаги (Сессия 4B)](#следующие-шаги-сессия-4b)
5. [Документы](#документы)

---

## Что работает сейчас

### API v1.1 + hotfixes

**Endpoints (14):**
- `blog_key_test` — health check, возвращает version + writable + endpoints + taxonomies + limits
- `blog_context` — таксономии + данные по 4 категориям материалов
- `blog_article_codes` — полный список артикулов (wpc 282 + flex 77 + reiki 50 + profiles 146 = 555)
- `blog_article_info` — детали по одному артикулу (name, cover, current_retail)
- `blog_article_info_bulk` — до 50 кодов за раз
- `blog_publish` — создание/обновление статьи (default draft=true)
- `blog_upload_image` — загрузка картинок (multipart или source_url)
- `blog_list` — публичный список (только опубликованные)
- `blog_get` — одна статья по slug (публичный)
- `blog_list_admin` — все статьи включая drafts (admin auth)
- `blog_get_admin` — одна статья с data для редактирования (admin auth)
- `blog_set_draft` — переключение draft true/false (admin auth)
- `blog_update_article` — обновление содержимого (admin auth)
- `blog_delete` — удаление (admin auth)
- `logout` — отзыв токена (admin auth)

**Параметры все endpoints:**
- `?sandbox=1` — работа с изолированной sandbox-таблицей (`blog_sandbox.json`)
- Без sandbox — работа с production (`blog.json`)

**Rate-limits (v1.1.4):**
- `blog_publish`: 1 запрос в 3 секунды
- `blog_upload_image`: 1/1 секунду
- `blog_article_info`: 10/1 секунду
- **Daily drafts: max 5 new created per day per X-Blog-Key** (sandbox и updates не учитываются)

**Audit log (v1.1.4):**
- Все `blog_publish` пишутся в `data/blog_publish_log.json`
- Поля: timestamp, ip, key_hint (md5), event, slug, action_type, draft, sandbox, blocks_parsed, blocks_dropped_count
- Хранятся последние 500 записей

**Auth методы для admin-endpoints (v2):**
- `body.token` (preferred) — из `sessionStorage.admin_token` в клиенте
- `Authorization: Bearer <token>` header (для API-консьюмеров)
- `login+password` в body (legacy, для обратной совместимости)

### Клиентская часть

**Админская модерация:**
- `cabinet.html?tab=blog` — три вкладки: Черновики / Опубликованные / 🧪 Песочница
- Редактор блоков: все 14 типов (h2/h3/h4/p/list/image/quote/cta/product/callout/divider/code/table/gallery/video)
- Кнопки действий: Превью, Редактировать (с учётом sandbox), Опубликовать/В черновик, Удалить
- Sticky bar редактора с кнопкой Сохранить
- Предпросмотр `article.html` с `?sandbox=1` для sandbox-статей

**Публичная часть:**
- `/blog.html` — список опубликованных (без drafts и sandbox)
- `/article.html?slug=X` — production-статья
- `/article.html?slug=X&sandbox=1` — sandbox-статья с баннером 🧪

**Навигация:**
- Общее меню: пункт «Наш блог» → `/blog.html` (было на ecosteni.ru, исправлено)
- Админский сайдбар: пункт «Блог» → `/cabinet.html?tab=blog`

### Knowledge base

**Файл:** `bamboodom_knowledge.md` (у команды A, ~40 КБ, 9 разделов):
1. Материалы (WPC, flex, reiki, profiles)
2. Монтаж (клеевой для WPC, плиточный клей для flex)
3. FAQ клиентов (**требует расширения**)
4. Применение по помещениям
5. Forbidden claims (что нельзя писать)
6. Link map (куда ссылаться)
7. Бренд, компания, контакты
8. Ценообразование и партнёрка
9. Рекомендованный тон

**Рост в будущем** (4B/5A): 60-80 КБ с реальными кейсами и FAQ → поднятие длины статей до 1800-2500 слов.

---

## История сессий

### Сессии 1 (API v1.0) — базовый контракт
Базовые endpoints: publish, upload_image, list, get, delete.

### Сессия 1.5 (API v1.1) — расширение
+7 endpoints: context, article_codes, article_info (+bulk), publish_html, sandbox flag, rate-limit.

### Сессия 2 (Админ-модерация)
+4 admin endpoints: list_admin, get_admin, set_draft, update_article. Редактор блоков в cabinet.html.

### Hotfix v1.1.1 — честный updated_at
`blog_article_codes` начал возвращать `updated_at: max(filemtime всех источников)` и отдельно `fetched_at` — чтобы команда A понимала когда реально обновлять кеш.

### Hotfix v1.1.2 — reiki + profiles (555 артикулов)
Распаршены `reiki.html` (50 R-кодов) и `profiles.html` (146 XHS-кодов) в `article_index.json`. API начал их возвращать в `blog_article_codes` и `blog_context.materials`.

### Hotfix v1.1.3 — sandbox rendering
Публичный `article.html` не пробрасывал `?sandbox=1` в `blog_get` — sandbox-статьи открывались как 404. Добавлен `getSandbox()`, флаг пробрасывается во все fetch. Добавлен баннер «🧪 Sandbox-режим». Ширина контейнера статьи расширена до 1400px.

### Hotfix v1.1.4 — rate-limit + audit log
Defensive механизмы перед production: max 5 new drafts/day на ключ + журналирование в `blog_publish_log.json`.

### Сессия 2A (команда A) — интеграция с Upstash Redis
Кеширование ответов `blog_context`, `blog_article_codes`, `blog_article_info` в Redis с TTL 1 час. Добавлен `force_refresh` для сброса. Сессия закрыта без правок на стороне B.

### Сессия 3A (команда A) — ручная публикация через Telegram
FSM в админке Telegram-бота с paste JSON. Первая e2e-публикация через `blog_publish?sandbox=1`. Поймали баг article.html → v1.1.3.

### Сессия 4A (команда A) — AI-генерация, 3 итерации

**Итерация #1** (WPC для ванной) — 6/10. Найдено:
- Монтаж на обрешётку вместо клея (противоречит KB)
- Толщины 8-15 мм (реально только 5 и 8)
- Пазогребневые замки (не существуют)
- Бренд «Bamboodom» вместо «Дизайн-Сервис»
- Пропущено главное УТП — чёрный/белый наполнитель
- Не было CTA и SEO meta
→ Feedback #1 с 7 правками промпта.

**Итерация #2** (Флекс для колонн) — 7/10. Правки #1 в основном применены. Но:
- Контактный клей вместо плиточного (критично)
- Выдуманные бренды Bostik, Sika
- Толщина 2-3 мм (реально 2-17)
- Состав «глина + полимер» вместо «композит на сетке»
- Пропущено УТП флекса (фасады)
- CTA-поле `href` вместо `link` (техническая проблема — фикс на моей стороне в v1.1.4)
→ Feedback #2 с 7 правками.

**Итерация #3** (WPC vs flex сравнение) — 9/10. Все 14 правок применены. Одна ошибка — «серия Wooden» (реально P).
→ Feedback #3 с одним правилом (серии WPC — только буквы).

### Session tokens v2 (моя инициатива)
Обнаружил архитектурный баг — в sessionStorage пароль админа не хранится, все admin-endpoints падали из UI кабинета. Фикс:
- Login теперь возвращает `token` в ответе
- `blog_check_admin` принимает 3 способа auth (token / Bearer / legacy login+password)
- `shared.js` сохраняет токен в `sessionStorage.admin_token`
- Новый endpoint `logout`

### Публикация первой production-статьи (24.04.2026)
1. Команда A: sandbox-статья WPC vs flex
2. Я: feedback #3 — одна ошибка «серия Wooden»
3. Команда A: правка промпта v4 (commit d0bd9b9)
4. Я (через кабинет): ручной фикс Wooden → P
5. Я (через F12 консоль): клонирование sandbox → production как draft
6. Я (через кабинет): модерация draft → публикация

**Результат:** первая AI-сгенерированная статья в публичном блоге bamboodom.ru.

---

## Список файлов на сервере

### Production PHP
- `public_html/api.php` (77 КБ) — основной API + admin tokens
- `public_html/blog_api.php` (45 КБ) — blog-модуль, подключается через `require_once`

### Клиентские HTML/JS
- `public_html/blog.html` — публичный список блога
- `public_html/article.html` (19.3 КБ) — рендер одной статьи, поддержка sandbox
- `public_html/cabinet.html` (143.5 КБ) — личный кабинет + админская модерация
- `public_html/shared.js` (116 КБ) — общие компоненты, сайдбар, login с токеном

### Данные (в `data/`)
- `blog.json` — production-статьи
- `blog_sandbox.json` — sandbox-статьи (автоочистка 7 дней)
- `blog_taxonomies.json` — материалы, suitable_for, texture_types
- `article_index.json` (190 КБ) — 555 артикулов
- `article_meta.json` — дополнительная метаинфа (description, suitable_for)
- `blog_key.txt` — API-ключ команды A
- `blog_ratelimit.json` — per-second rate limits
- `blog_daily.json` — daily drafts counter (v1.1.4)
- `blog_publish_log.json` — audit log (v1.1.4)
- `admin_tokens.json` — admin sessions v2
- `users.json` — пользователи
- `params.json` — параметры расчёта цен (yuan, usd, del, msk, multi-mult)

### Картинки
- `public_html/img/blog/<slug>/` — production-картинки
- `public_html/img/blog_sandbox/<slug>/` — sandbox-картинки (автоочистка)

---

## Следующие шаги (Сессия 4B)

### Со стороны команды A

1. **Production-переключатель в UI бота**
 Из режима sandbox (4A default) в production draft=true. Финальный переход делается **после** 3-5 успешных production-статей с модерацией оператора B.

2. **Картинки в статьях**
 Cover image + 1-2 inline через ImageDirectorService. Upload через `blog_upload_image` с whitelist для Railway URL (уже работает в sandbox).

3. **Семантический валидатор layer 3**
 Claude Haiku для мягких forbidden claims типа «чувствительным к бытовой химии», «подходит для астматиков», которые regex не ловит. Высокий приоритет — кейсы проскакивали в итерациях #1-3.

4. **История публикаций в UI бота**
 Показывать оператору A последние 20 публикаций с ссылками и статусами.

5. **Применить библиотеку из 7 форматов**
 См. `ARTICLE_FORMATS_LIBRARY.md`. Системный промпт выбирает формат по типу темы и генерирует по соответствующему шаблону.

6. **Политика длины 1500+ слов**
 См. `ARTICLE_LENGTH_POLICY.md`. Жёсткие границы 1500-2200 слов в 4B с ростом в будущем.

### С моей стороны (параллельно)

1. **ProductCard в article.html → подключить к blog_article_info**
 Сейчас ProductCard в публичных статьях парсит W_ART из wpc.html. Нужно брать цену через API для live-обновлений.

2. **Загрузка картинок через мой редактор**
 Сейчас в кабинете только URL картинки. Добавить upload с последующим вызовом `blog_upload_image`.

3. **Семантический валидатор на сервере (defensive layer)**
 Если у команды A layer 3 что-то пропустит — мой сервер финально фильтрует и возвращает в `blocks_dropped`. Сделаю после того как увижу реальные кейсы.

4. **Расширение knowledge base**
 Совместно с оператором B. Целевой объём 100+ КБ:
 - FAQ из переписок клиентов (10-15 реальных вопросов)
 - Кейсы из практики Дизайн-Сервиса (5-10 кейсов с цифрами)
 - Матрица сценариев применения по помещениям
 - Детализация техники монтажа

### Критерии готовности к переходу на production без sandbox-first

Принимаем решение переключать bot из «sandbox by default» на «production by default» когда выполнены ВСЕ условия:
1. 3-5 production-статей опубликованы оператором B после модерации
2. Качество оценок статей стабильно ≥ 8/10
3. Галлюцинации минимальны (не более 1 мелкой на статью)
4. Layer 3 валидатор команды A активен и ловит мягкие forbidden claims
5. Knowledge base не менее 60 КБ

---

## Документы

**Архитектурные:**
- `SESSION_4A_ANSWERS.md` — ответы на 14 развилок 4A с обоснованием sandbox-first
- `SYNC_RESPONSE_FROM_B.md` — последняя синхронизация с командой A

**Фидбэк по AI-статьям:**
- `FEEDBACK_ARTICLE_1.md` — итерация #1 (WPC ванная, 6/10, 7 правок)
- `FEEDBACK_ARTICLE_2.md` — итерация #2 (Флекс колонны, 7/10, 7 правок)
- `FEEDBACK_ARTICLE_3.md` — итерация #3 (WPC vs flex, 9/10, 1 правка)

**Политики:**
- `ARTICLE_FORMATS_LIBRARY.md` — 7 форматов статей (новый, этот пакет)
- `ARTICLE_LENGTH_POLICY.md` — длина 1500+ слов (новый, этот пакет)

**Deploy packages:**
- `hotfix_v1_1_1.zip` — honest updated_at
- `hotfix_v1_1_2.zip` — reiki + profiles (555 артикулов)
- `hotfix_v1_1_3.zip` — sandbox rendering
- `hotfix_v1_1_4.zip` — rate-limit + audit log
- `deploy_tokens_v2.zip` — admin session tokens

**Knowledge base:**
- `bamboodom_knowledge.md` — 40 КБ, 9 разделов

**Скрипты:**
- `clone_to_production.js` — F12 payload для клонирования sandbox → production

---

## Метрики

- **API endpoints:** 14 + logout = 15
- **Артикулов в индексе:** 555 (wpc 282 + flex 77 + reiki 50 + profiles 146)
- **Итераций в 4A:** 3
- **Правок промпта по фидбэку:** 15 (7 в #1, 7 в #2, 1 в #3)
- **Galлюцинации пойманные в sandbox:** 13 (4 в #1, 6 в #2, 1 в #3 + 2 технических про cta/href)
- **Sandbox-катаcтрофы в production:** **0** (архитектура sandbox-first окупилась)
- **Production-статей опубликовано:** 1
- **Файлов на сервере изменено:** 5 (api.php, blog_api.php, cabinet.html, shared.js, article.html)

---

— Claude, сторона B
