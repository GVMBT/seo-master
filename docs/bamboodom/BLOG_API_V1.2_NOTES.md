# blog_api.php v1.2 — defensive layer

**Дата:** 24.04.2026
**От:** сторона B (bamboodom.ru)
**Для:** сторона A (seo-master bot)

## TL;DR

Seven защитных механизмов добавлены **поверх** существующего API. Публикации продолжают работать как раньше; новое — в ответе `blog_publish` и `blog_upload_image` теперь есть массив `warnings`, который нужно показывать оператору в UI.

Ничего не ломается — все старые публикации пройдут. Ответ `blog_publish` получил 4 новых поля, все дополнительные.

## Новое в ответе `blog_publish`

```json
{
  "ok": true,
  "slug": "...",
  "url": "...",
  "action_type": "created|updated",
  "draft": true,
  "draft_forced": false,     // ← НОВОЕ
  "blocks_parsed": 15,
  "blocks_dropped": [...],
  "warnings": [              // ← НОВОЕ
    { "code": "...", "hint": "...", "items": [...] }
  ],
  "size_kb": 12,             // ← НОВОЕ
  "sandbox": false
}
```

Если `warnings` не пустой — **оператору в UI нужно показать предупреждения** перед переводом статьи из draft в production.

## Коды warnings и что с ними делать

### `draft_forced`
**Что значит:** вы прислали `draft=false`, но без admin auth. Сервер автоматически перевёл в `draft=true`.
**Что делать:** оператор должен вручную опубликовать через админку.
**Причина:** защита от случайной прямой публикации AI-статей.

### `unknown_articles_in_text`
**Что значит:** в тексте (title/excerpt/p/h2/h3/h4/list/quote/callout/code) упомянуты артикулы, которых нет в `article_index.json`.
**Формат:** `items: [{code: "TK999Z", where: ["title", "p#4"]}]`
**Что делать:** перегенерировать секцию или убрать вымышленный артикул.
**Пример:** статья говорит «попробуйте TK999Z» — такого артикула не существует.

### `denylist_matches`
**Что значит:** сработали правила semantic denylist (маркетинговые шаблоны, которых мы избегаем).
**Формат:** `items: [{category: "guarantees", match: "100% экологичн", where: "excerpt"}]`

**Категории** (12 штук, 60+ правил):
- `longevity` — обещания срока службы («прослужит десятилетия», «30 лет гарантии»)
- `guarantees` — абсолютные гарантии («100% экологичный», «полностью натурально»)
- `health` — клеймы здоровья («гипоаллергенный», «очищает воздух»)
- `pricing` — суперклеймы по цене («самый дешёвый», «бесплатная доставка»)
- `competitors` — обесценивание конкурентов («в отличие от дешёвых МДФ»)
- `tech_exaggeration` — технические преувеличения («не горит», «не царапается»)
- `certifications` — псевдо-сертификация («европейское качество»)
- `fake_stats` — выдуманная статистика («80% покупателей»)
- `universality` — универсальность («подходит для любых задач»)
- `eco` — эко-клеймы за рамками фактов («биоразлагаемый»)
- `marketing_fluff` — маркетинговый мусор («революционный материал»)
- `wrong_tech` — технические ошибки про наш продукт («пазогребневое соединение», «монтаж на обрешётку»)

**Что делать:** перегенерировать секцию с более аккуратными формулировками. Эти правила — сигнал, а не блокировка. Если правило даёт false positive — пришлите пример, я ослаблю паттерн.

### `seo_issues`
**Что значит:** проблемы в `seo.meta_title` / `seo.meta_description`.
**Формат:** `items: [{code: "seo_title_too_long", hint: "meta_title 80 chars, рекомендуется ≤60"}]`

**Коды:**
- `seo_title_missing` — пусто → будет использован title статьи
- `seo_title_too_long` — >60 символов (не обрежется, но Google обрежет)
- `seo_description_missing` — пусто → будет использован excerpt
- `seo_description_too_long` — >160 символов

## Отбраковка пустых блоков

Ранее валидатор проверял только структурную корректность (тип, артикул у product). Пустой `cta` без `text`/`link` проходил и рендерился на сайте как безтекстовая кнопка-прямоугольник (живой случай в статье «WPC для ванной» — 24.04.2026).

Теперь отбрасываются **все блоки, которые не имеют смысла без содержимого**. Попадают в `blocks_dropped` с конкретным `reason`:

| Блок | Условие отбраковки | Reason |
|------|--------------------|--------|
| `cta` | нет `text`/`title` И нет `link`/`href` | `empty_cta` |
| `cta` | есть link но нет text | `cta_missing_text` |
| `cta` | есть text но нет link | `cta_missing_link` |
| `h2`/`h3`/`h4`/`p`/`quote`/`code` | пустой `text` | `empty_text` |
| `callout` | нет ни `text` ни `title` | `empty_callout` |
| `image` | нет `src` | `empty_image` |
| `list` | `items` пуст или все элементы пустые | `empty_list` |
| `gallery` | `images` пуст | `empty_gallery` |
| `video` | нет `src`/`url` | `empty_video` |
| `table` | `rows` пуст | `empty_table` |

Для `list` дополнительно: пустые строки внутри `items` молча отфильтровываются, оставляя только непустые. Если после фильтра ничего не осталось — блок отбрасывается целиком.

Whitespace-only (`"   "`) считается пустой строкой.

## Жёсткие лимиты (раньше их не было, статья отклоняется с 400)

| Поле | Лимит |
|------|-------|
| `title` | 200 chars |
| `excerpt` | 500 chars |
| блоков в статье | 80 |
| текст одного блока (`p`/`quote`/`callout`/`list`) | 10000 chars |
| весь JSON статьи | 200 KB |

Если лимит превышен — `{"ok": false, "error": "article too large (...)"}`. Новые лимиты видны в `blog_key_test`.

## HTML sanitization

Ранее текст блоков попадал в `blog.json` **как есть** — включая `<script>`, `<iframe>`, `onclick` и прочее.

Теперь применяется whitelist: разрешены только `<b>`, `<strong>`, `<i>`, `<em>`, `<u>`, `<a>`, `<br>`, `<code>`. Всё остальное **удаляется молча**. У `<a>` оставляются только `href` (с проверкой на `javascript:`/`data:`/`vbscript:`), `title`, `target`. К `target="_blank"` автоматически добавляется `rel="noopener noreferrer"`.

Применяется ко всем текстовым полям: `title`, `excerpt`, `h2/h3/h4.text`, `p.text`, `quote.text`, `callout.text`/`title`, `cta.text`/`title`/`subtitle`, `list.items[]`. Не применяется к `code.text` (намеренно — там код как есть).

## Авто-конвертация картинок в WebP

`blog_upload_image` теперь автоматически:

1. Конвертирует JPEG/PNG/GIF → WebP (quality 80).
2. Ресайзит если большая сторона > 2000px (сохраняя пропорции).
3. Обновляет имя файла: `cover.png` → `cover.webp`.
4. Возвращает новые поля в ответе:

```json
{
  "ok": true,
  "url": "/img/blog/slug/cover.webp",  // .webp, не .png!
  "filename": "cover.webp",
  "size_bytes": 145320,
  "width": 2000,
  "height": 1125,
  "converted": true,                   // ← НОВОЕ
  "warnings": [                        // ← НОВОЕ
    {"code": "resized", "hint": "Resized to 2000x1125 (max side 2000)"}
  ]
}
```

**Что нужно сделать на стороне A:** вставляйте в блок `image.src` то, что вернул сервер в поле `url` (может отличаться от исходного имени). Раньше `url` всегда соответствовал переданному `filename` — теперь может измениться расширение.

Если GD недоступен (редко на хостингах) — warning `conversion_gd_missing`, файл сохраняется как есть.

## Draft enforcement

Раньше вы могли прислать `draft=false` и статья немедленно публиковалась. Теперь:

- **Bot-key (ваш `X-Blog-Key`)** → всегда `draft=true`, независимо от того что прислали.
- **Admin auth (`body.token` или `body.login+password`)** → `draft=false` работает.

В ответе появляется `draft_forced: true`, если ваш запрос был понижен до draft. Получив такой ответ — оператор должен зайти в кабинет, просмотреть статью и вручную публиковать через `blog_set_draft`.

**Почему:** AI-статья не должна попадать в production без человеческого review.

## Что НЕ изменилось

- Все существующие endpoints работают как раньше
- `blog_get`, `blog_list`, `blog_context`, `blog_article_codes`, `blog_article_info` — без изменений
- Rate limits те же (5/day на created, 1/3s на publish, 1/s на upload)
- API-ключ тот же
- sandbox режим работает как раньше
- Whitelist доменов для `source_url` не менялся

## `blog_key_test` v1.2

GET `/api.php?action=blog_key_test` теперь возвращает дополнительно:

```json
{
  "version": "1.2",
  "limits": {
    "article_max_blocks": 80,
    "article_max_size_kb": 200,
    "article_max_text_block_chars": 10000,
    "article_max_title_chars": 200,
    "article_max_excerpt_chars": 500,
    "seo_title_max_chars": 60,
    "seo_description_max_chars": 160,
    "image_max_side_px": 2000,
    "image_webp_quality": 80,
    // + старые лимиты
  },
  "defensive_layer": {
    "html_sanitize": true,
    "allowed_tags": ["b", "strong", "i", "em", "u", "a", "br", "code"],
    "article_scan_in_text": true,
    "denylist_categories": ["longevity", "guarantees", ...],
    "denylist_rules_count": 62,
    "draft_enforcement": "bot-key forces draft=true; direct publish requires admin auth",
    "webp_conversion": true
  }
}
```

Используйте для smoke-check при деплое.

## Audit log расширен

`data/blog_publish_log.json` теперь содержит новые поля:
- `draft_forced: bool`
- `warnings_count: int`
- `size_kb: int`

Формат остальных полей не менялся.

## Производственный сценарий

1. Команда A сгенерировала статью. Вы шлёте `blog_publish` как обычно.
2. Сервер проверяет: лимиты → блоки → санитизация → сканы.
3. Ответ содержит `warnings`. Если их нет — публикация прошла «чисто». Если есть — **оператору в UI показывать warnings** и требовать action: перегенерировать / отредактировать / всё равно опубликовать.
4. Статья лежит как `draft=true` (даже если в запросе было `draft=false`).
5. Оператор решает и публикует через `blog_set_draft` (admin auth).

---

— Claude, сторона B
