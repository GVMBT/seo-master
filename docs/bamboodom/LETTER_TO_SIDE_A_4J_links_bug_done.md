# Сторона B → сторона A: lowercase URL bug fixed

**От:** сторона B (bamboodom.ru blog API + сайт)
**Кому:** сторона A (seo-master / @best_seo_master_bot)
**Дата:** 2026-04-26 20:24 МСК
**В ответ на:** `LETTER_TO_SIDE_B_4J_links_bug.md`

---

## ✅ Commit B done

Маркер: `LOWERCASE-FIX-V1` в `article.html`. Бэкап оставлен.

## Что было сломано

3 места в `article.html` приводили часть URL к нижнему регистру:

```js
// L1079 — WPC
href = `/texture/${prod.code.toLowerCase()}.html`;

// L1090 — Reiki fallback
href = `/reiki/${(prod.img || '').replace(...) || prod.code.toLowerCase()}.html`;

// L1099 — Profile image (не href, но тот же баг)
img = `/img/prof/${slug.toLowerCase()}.jpg`;
```

## Что стало

`.toLowerCase()` убран — теперь:

```js
href = `/texture/${prod.code}.html`;            // L1079 — TK029P сохраняется
href = `/reiki/${... || prod.code}.html`;       // L1090
img  = `/img/prof/${slug}.jpg`;                 // L1099 — для img профилей
```

## По 4 категориям

| Категория | href строится из | Lowercase? | Статус |
|---|---|---|---|
| WPC `/texture/` | `prod.code` | **был toLowerCase**, фикснут | ✅ |
| Flex `/flex-texture/` | `slug` от `prod.img` (без `.webp/.jpg`) | нет, регистр сохраняется | ✅ |
| Reiki `/reiki/` | `slug` от `prod.img` или fallback на `prod.code` | **был toLowerCase в fallback**, фикснут | ✅ |
| Profile `/profile/` | `slug` от `prod.fullModel || prod.code` с заменой ` ` → `_`, `*` → `x`, `/` → `-` | нет, регистр сохраняется | ✅ |

Также фикснут image path для Profile (L1099) — был `slug.toLowerCase()`, на сервере файлы разного регистра (`L10.webp`, `QB0501.webp`, `prof_qb0501.jpg`).

## Sanity check

Patch встроил автопроверку: после замены regex `href = .../*\.toLowerCase\(\)` ищет остатки → результат **0** (toLowerCase больше нет в URL-builders).

## Smoke-test

Открыл sandbox-статью партии 4J (WPC офис), product-блоки в DOM:

```
/texture/TK029P.html    ← UPPERCASE
/texture/TK181B.html    ← UPPERCASE
/texture/TK196M.html    ← UPPERCASE
```

Все три — `200 OK`. Перепубликация партии не требуется (статьи рендерятся на лету из payload).

## Backlog

Проблема URL-encoding (если в slug пробелы или кириллица) — отдельная история, не блокер для 4J. Производитсятся позже если в production обнаружится.

## Production-cutover

Зелёный свет на понедельник 27.04. С нашей стороны блокеров не осталось:

- ✅ STRICT-ARTICLES-V1 — hard fail при unknown codes в production
- ✅ SEO-V1 — canonical + Schema.org JSON-LD + OpenGraph
- ✅ LOWERCASE-FIX-V1 — UPPERCASE URLы товаров
- ✅ SITEMAP-CRON-V1 — auto-regen каждую ночь
- ✅ PROMOTE-V1 — endpoint `blog_promote_from_sandbox` для ручного промоута sandbox→production
- ✅ BLOG-CAB-V5 — UI cabinet полный (тумблер, виджет, лог, кнопка promote, фирменный confirm)
- ✅ SEO-SOFT-V1 — soft warning 1400-1499 слов

В понедельник утром Александр включит `default_draft_mode → production` через тумблер в cabinet, после чего ваши `blog_publish` без `draft` параметра пойдут в production blog.

---

— Александр (сторона B)
