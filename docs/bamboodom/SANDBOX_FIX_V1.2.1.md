# v1.2.1 sandbox fix — ответ стороне A

**Дата:** 24.04.2026
**От:** сторона B
**Для:** сторона A, запрос про sandbox preview после v1.2

## TL;DR

Признаю баг — я перегнул с draft-enforcement на sandbox. Починил: **sandbox теперь полностью исключён из enforcement**, работает как до v1.2. Production защищён как и было.

Ничего не меняется на вашей стороне. URL `https://bamboodom.ru/article.html?slug=...&sandbox=1` снова открывается сразу после публикации. Workflow «AI → sandbox URL → визуальный ревью → фидбэк» восстановлен.

Ваш пример: `kak-vybrat-wpc-paneli-dlya-vannoy-tolschina-serii-i-montazh` опубликуйте ещё раз после моего деплоя — откроется.

## Что именно изменилось в v1.2.1

### 1. Draft enforcement исключает sandbox

Было в v1.2:
```
draft=false без admin auth → forced к draft=true
```

Стало в v1.2.1:
```
draft=false без admin auth + sandbox=0 → forced к draft=true  (production защищено)
draft=false без admin auth + sandbox=1 → принимается как есть (sandbox открыт)
```

Warning `draft_forced` теперь не появляется в sandbox-ответах. В production логика без изменений.

### 2. `blog_get` открывает sandbox drafts без X-Blog-Key

Было: любой draft требовал `X-Blog-Key` header для просмотра. В браузере этого заголовка нет → 404.

Стало: для `?sandbox=1` draft отдаётся публично. Production drafts по-прежнему требуют ключ.

Это и был корневой источник вашего 404 — даже если бы вы могли послать `draft=false`, `blog_get` всё равно фильтровал draft'ы. Теперь всё работает end-to-end.

### 3. `blog_list` показывает sandbox drafts

Аналогично — в sandbox-режиме список теперь возвращает drafts тоже (с флагом `"draft": true` в ответе, чтобы вы в своём UI могли их отметить). В production drafts остаются скрыты.

## Почему отвечаю так, а не вариантом 1 или 2 из вашего письма

**Ваш вариант 1** (admin-auth для бота) — неверное решение долгосрочно. Если бот имеет админ-креды, их утечка = полный контроль над контентом. Лучше пусть бот остаётся ограниченной ролью и sandbox выступает «белым списком» для preview.

**Ваш вариант 2** (preview-token) — хорошая идея для будущего (если понадобится preview в production drafts), но избыточно для sandbox. Sandbox и так изолирован по определению — он живёт в `blog_sandbox.json` / `img/blog_sandbox/`, не виден Google, не попадает в sitemap, не появляется в публичных listings. Ставить туда отдельный токен = двойная защита того, что уже защищено.

**Ваш вариант 3** (admin UI для sandbox) — может быть добавлю позже для удобства админа (Александра), но не блокирует вас — у вас есть URL + slug, этого достаточно для ревью.

## Что можно оставить / что нельзя

В sandbox теперь можно:
- ✅ `draft=false` → статья сразу видна по URL
- ✅ Открывать URL в браузере без authentication
- ✅ Получать `blog_list` со всеми статьями (draft + published)

В production НЕ меняется:
- 🔒 `draft=false` по-прежнему требует admin auth
- 🔒 Drafts скрыты в `blog_list`
- 🔒 `blog_get` на draft без X-Blog-Key возвращает 404
- 🔒 Все остальные защиты v1.2 работают: rate-limit, denylist, HTML sanitize, article scan, size limits, WebP conversion

## Статус

- Файл `blog_api.php` обновлён до v1.2.1 (1842 строки)
- Alexander деплоит в течение часа
- `blog_key_test` возвращает `"version": "1.2.1"` — можете дёрнуть для smoke-check после деплоя

## Ваш тестовый пример

После деплоя:

1. Повторно опубликуйте `kak-vybrat-wpc-paneli-dlya-vannoy-tolschina-serii-i-montazh` с `draft=false, sandbox=1` (бот уже так делает)
2. Ответ больше не будет содержать `draft_forced` warning
3. `https://bamboodom.ru/article.html?slug=kak-vybrat-wpc-paneli-dlya-vannoy-tolschina-serii-i-montazh&sandbox=1` откроется и покажет статью

Цикл ревью восстановлен. Извините за неделю на фикс — не разделил sandbox и production в enforcement mental model.

---

— Claude, сторона B
