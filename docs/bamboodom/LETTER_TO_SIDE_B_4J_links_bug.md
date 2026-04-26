# Сторона A → сторона B. Баг: ссылки на товары в article.html lowercase'ятся

**От:** сторона A (seo-master / @best_seo_master_bot)
**Кому:** сторона B (bamboodom.ru blog API + сайт)
**Дата:** 2026-04-26
**Тема:** все ссылки на товарные страницы в статьях ведут на 404 — case-sensitivity

## Симптом

В партии 4J все три статьи имеют битые ссылки на товары. Шаблон `article.html` рендерит product-блоки с lowercase article_code в URL — но физические страницы товаров на сервере uppercase.

## Доказательство

**Sandbox-статья 1 (WPC офис):**
https://bamboodom.ru/article.html?slug=wpc-paneli-v-ofise-kak-obnovit-interer-za-2-dnya-bez-ostanovki-raboty&sandbox=1

**Ссылки в DOM (3 product-блока):**
- `/texture/tk029p.html`
- `/texture/tk181b.html`
- `/texture/tk196m.html`

Все три — **lowercase**. JS-проверка `fetch HEAD`:
- `https://bamboodom.ru/texture/tk029p.html` → **404**
- `https://bamboodom.ru/texture/TK029P.html` → **200** ✓

То есть сервер case-sensitive (что нормально для nginx), а шаблон сейчас вписывает в `href` lowercase копию article_code, не оригинал.

## Где предположительно баг

В `article.html` шаблоне (или в `blog_build_article_info` PHP), при формировании URL продукта что-то типа:

```php
// БАГ:
$href = "/texture/" . strtolower($article_code) . ".html";

// ДОЛЖНО:
$href = "/texture/" . $article_code . ".html";
```

Аналогичное вероятно для всех 4 категорий — `/texture/`, `/flex-texture/`, `/reiki/`, `/profile/`. Стоит проверить все четыре.

## Что нужно от вас

1. **Найти место в шаблоне** где строится `href` для product-блока, убрать `strtolower()` (или эквивалент).
2. **Проверить все 4 категории** — TK*/F*/R*/XHS-* — нет ли других мест с приведением к нижнему регистру.
3. **Существующие 3 sandbox-статьи (4J)** автоматически заработают после деплоя фикса (страница рендерится на лету из payload).
4. **Прислать `commit B done`** когда будет готово.

## Дополнительно

С нашей стороны мы пайлоадим article_code uppercase, как они приходят из `blog_article_codes` endpoint. Менять что-то на стороне A не нужно. Это зона B полностью.

Это блокер для production-cutover в понедельник. Если оставить как есть — все production-статьи будут с битыми ссылками на товары, что ужасно для SEO/конверсии. Просим успеть до завтра.

— Александр (сторона A)
