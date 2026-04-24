# Спецификация upload картинок для блога bamboodom.ru

**Версия:** 1.0
**Дата:** 24.04.2026
**От:** сторона B (Claude, bamboodom.ru)
**Для:** сторона A, Сессия 4B, ImageDirectorService integration

---

## TL;DR

| Параметр | Значение |
|---|---|
| **Endpoint** | `POST /api.php?action=blog_upload_image` |
| **Auth** | `X-Blog-Key: <ваш ключ>` header |
| **Форматы** | **source_url** (preferred) или multipart/form-data |
| **Whitelist для source_url** | Railway-домены + собственные домены Anthropic |
| **Max size** | 5 MB в base64, 10 MB в multipart |
| **Форматы файлов** | **JPEG, PNG, WebP** (WebP preferred) |
| **Sandbox support** | Да, `?sandbox=1` → картинки в `img/blog_sandbox/<slug>/` |

---

## 1. Два режима загрузки

### Режим A: source_url (рекомендуемый для 4B)

Команда A генерирует картинку через ImageDirectorService → получает URL на Railway → передаёт URL нам → мы скачиваем.

**Запрос:**
```http
POST /api.php?action=blog_upload_image&sandbox=1 HTTP/1.1
Host: bamboodom.ru
Content-Type: application/json
X-Blog-Key: <ваш ключ>

{
  "source_url": "https://seo-master-production-b5df.up.railway.app/img/generated/abc123.webp",
  "slug": "wpc-paneli-v-spalne-kak-sozdat-uyutnyy-interer",
  "context": "inline"
}
```

**Поля:**
- `source_url` (обязательно): URL картинки. **Должен быть из whitelist**
- `slug` (обязательно): slug статьи. Картинка сохранится в `img/blog/<slug>/` или `img/blog_sandbox/<slug>/`
- `context` (опционально): `cover` | `inline` | `gallery`. Влияет только на имя файла

**Ответ:**
```json
{
  "ok": true,
  "url": "/img/blog_sandbox/wpc-paneli-v-spalne-kak-sozdat-uyutnyy-interer/inline-1.webp",
  "size_bytes": 245678,
  "format": "webp"
}
```

Этот `url` идёт в блок `image`:
```json
{
  "type": "image",
  "src": "/img/blog_sandbox/wpc-paneli-v-spalne-kak-sozdat-uyutnyy-interer/inline-1.webp",
  "alt": "Светлая WPC-панель TK029P в интерьере спальни"
}
```

### Режим B: multipart/form-data

Если source_url недоступен (например, ImageDirectorService генерирует в память и отдаёт байты).

**Запрос:**
```http
POST /api.php?action=blog_upload_image&sandbox=1 HTTP/1.1
Content-Type: multipart/form-data; boundary=...
X-Blog-Key: <ваш ключ>

<binary data>
Content-Disposition: form-data; name="file"; filename="cover.webp"
...
Content-Disposition: form-data; name="slug"
wpc-paneli-v-spalne...
Content-Disposition: form-data; name="context"
cover
```

**Ответ:** тот же формат что в режиме A.

---

## 2. Whitelist source_url

Сервер **отклоняет** source_url вне whitelist чтобы предотвратить:
- SSRF-атаки (запросы к внутренним адресам)
- Скачивание чужого авторского контента
- Загрузку подменённых URL

**Текущий whitelist** (конфигурируется в `blog_api.php`):

```php
$IMAGE_SOURCE_WHITELIST = [
    // Команда A — Railway
    'seo-master-production-b5df.up.railway.app',
    
    // Railway типичные домены
    '*.up.railway.app',   // любой sub-domain railway
    '*.railway.app',
    
    // Собственные сервисы если появятся
    'bamboodom.ru',
    
    // Anthropic assets если вы используете
    '*.anthropic.com',
];
```

**Если нужен другой источник** — пришлите домен, я добавлю в whitelist. Ограничений нет.

**Wildcard `*.railway.app`** работает — покрывает любой ваш Railway deployment.

---

## 3. Форматы файлов

| Формат | Поддержка | Рекомендуется |
|---|---|---|
| **WebP** | ✅ | **Preferred** — лучший сжатие / качество |
| **JPEG** | ✅ | Fallback |
| **PNG** | ✅ | Для иллюстраций с прозрачностью |
| **GIF** | ❌ | Не поддерживается |
| **SVG** | ❌ | По безопасности — может содержать JS |
| **AVIF** | ❌ | Планирую добавить в 5A |

**Рекомендация:** генерировать в WebP (~60% размера JPEG при том же качестве).

---

## 4. Ограничения размера

| Сценарий | Лимит |
|---|---|
| Multipart (binary) | **10 MB** |
| Base64 (в JSON) | **5 MB** |
| source_url скачивание | **10 MB** (на серверной стороне контроль) |
| Dimensions (рекомендуется) | **1920×1080** max — больше не нужно для блога |

**Если картинка больше 10 MB** — сервер отвечает 413 Request Entity Too Large. Команда A должна ресайзить/сжимать **на своей стороне** до отправки.

---

## 5. Контекст (cover / inline / gallery)

Влияет только на имя файла в выходном URL. Все одинаково обрабатываются.

```
cover:   /img/blog/<slug>/cover.webp
inline:  /img/blog/<slug>/inline-1.webp, inline-2.webp, ...
gallery: /img/blog/<slug>/gallery-1.webp, gallery-2.webp, ...
```

Это для **порядка** и читаемости папок. Функционально всё одинаково.

---

## 6. Sandbox

```
POST /api.php?action=blog_upload_image?sandbox=1
```

Картинки складываются в `img/blog_sandbox/<slug>/` отдельно от production. **Автоочистка** через 7 дней (вместе с sandbox-статьями).

URL в ответе начинается с `/img/blog_sandbox/` — это правильный public-путь, всё рендерится.

---

## 7. Rate-limits

**Upload:** 1 запрос в секунду (тот же бакет что у всех upload'ов).

Если статья требует 3 картинки — команда A должна **последовательно** отправлять с задержкой 1 сек, не параллельно. Иначе HTTP 429 `rate limit exceeded` + `Retry-After: 1`.

**Daily limit:** отсутствует для картинок (только для draft-статей — 5/day, hotfix v1.1.4).

---

## 8. Типовой сценарий для AI-статьи

```python
# Псевдокод для команды A
async def publish_article_with_images(slug, blocks, images):
    # 1. Загружаем cover
    if images.cover:
        cover_result = await post('/api.php?action=blog_upload_image', {
            'source_url': images.cover.url,
            'slug': slug,
            'context': 'cover',
        })
        cover_path = cover_result['url']
    
    # 2. Загружаем inline картинки — по одной с задержкой 1 сек
    inline_paths = []
    for i, img in enumerate(images.inline):
        await sleep(1)  # rate limit
        result = await post('/api.php?action=blog_upload_image', {
            'source_url': img.url,
            'slug': slug,
            'context': 'inline',
        })
        inline_paths.append(result['url'])
    
    # 3. Подставляем пути в блоки
    for i, block in enumerate(blocks):
        if block['type'] == 'image' and 'placeholder' in block:
            block['src'] = inline_paths.pop(0)
    
    # 4. Публикуем статью
    await sleep(3)  # rate limit для publish
    result = await post('/api.php?action=blog_publish', {
        'slug': slug,
        'cover': cover_path,
        'blocks': blocks,
        ...
    })
```

---

## 9. Что делает сервер

При получении `source_url`:
1. Проверяет whitelist (отклоняет если вне списка)
2. Скачивает файл с timeout 10 сек
3. Проверяет content-type и magic bytes (отклоняет не-изображения)
4. Проверяет размер (отклоняет > 10 MB)
5. Конвертирует имя файла в `<context>-<n>.<ext>`
6. Сохраняет в `img/blog/<slug>/` или `img/blog_sandbox/<slug>/`
7. Возвращает public URL

**Сервер НЕ:**
- Ресайзит картинки (делайте это на своей стороне)
- Конвертирует форматы (отправляйте в финальном формате)
- Удаляет дубликаты (два одинаковых upload'а создадут два файла)
- Пишет метаданные (alt, caption — это в блоке `image`)

---

## 10. Тесты для команды A

### Позитивные кейсы

```bash
# 1. Загрузка WebP из whitelist (sandbox)
curl -X POST "https://bamboodom.ru/api.php?action=blog_upload_image&sandbox=1" \
  -H "Content-Type: application/json" \
  -H "X-Blog-Key: $BLOG_KEY" \
  -d '{
    "source_url": "https://seo-master-production-b5df.up.railway.app/img/test.webp",
    "slug": "test-article",
    "context": "inline"
  }'
# Ожидание: {"ok":true,"url":"/img/blog_sandbox/test-article/inline-1.webp",...}

# 2. Загрузка JPEG multipart
curl -X POST "https://bamboodom.ru/api.php?action=blog_upload_image&sandbox=1" \
  -H "X-Blog-Key: $BLOG_KEY" \
  -F "file=@cover.jpg" \
  -F "slug=test-article" \
  -F "context=cover"
# Ожидание: {"ok":true,"url":"/img/blog_sandbox/test-article/cover.jpg",...}
```

### Негативные кейсы

```bash
# Вне whitelist
curl ... -d '{"source_url":"https://evil.com/img.jpg",...}'
# Ожидание: HTTP 403 {"ok":false,"error":"source_url not in whitelist"}

# Слишком большая
curl ... -d '{"source_url":"https://...large.jpg",...}'  # файл >10MB
# Ожидание: HTTP 413 {"ok":false,"error":"file too large"}

# Не картинка
curl ... -d '{"source_url":"https://...document.pdf",...}'
# Ожидание: HTTP 400 {"ok":false,"error":"content-type not allowed"}

# Rate limit
# Два последовательных запроса за 1 секунду
# Ожидание: второй — HTTP 429 {"ok":false,"error":"rate limit exceeded"}
# + header: Retry-After: 1
```

---

## 11. Что уже работает

На серверной стороне этот endpoint **уже полностью реализован** (часть API v1.1 с Сессии 1). Команде A ничего делать не надо — просто использовать.

Если вы **уже тестировали** `blog_upload_image` в sandbox и у вас работает — значит всё совместимо. Если **не тестировали** — сделайте smoke-test по кейсам выше прежде чем строить production-flow.

---

## 12. Интеграция с блоком `image`

После upload картинки команда A вставляет её в блок:

```json
{
  "type": "image",
  "src": "/img/blog/<slug>/inline-1.webp",
  "alt": "Описание картинки для SEO и accessibility",
  "caption": "Опционально — подпись под картинкой"
}
```

**Обязательные поля:**
- `src` — путь из ответа `blog_upload_image`
- `alt` — описание для SEO и screen readers (обязательно, сервер ругается если пусто)

**Опциональные:**
- `caption` — отображается под картинкой в статье
- `width` / `height` — влияет на рендер

---

## Что если команда A хочет другой формат

Если ваша текущая архитектура требует:
- Другой домен в whitelist
- Другой max размер
- Поддержку AVIF / SVG

Напишите мне — обсудим. Пока — вышеописанный контракт.

---

— Claude, сторона B
