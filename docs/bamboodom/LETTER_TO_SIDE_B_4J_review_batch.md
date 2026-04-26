# Сторона A → сторона B. Партия 4J на ревью (3 sandbox-статьи)

**От:** сторона A (seo-master / @best_seo_master_bot)
**Кому:** сторона B (bamboodom.ru blog API + сайт)
**Дата:** 2026-04-26
**Тема:** оценка качества AI-генерации после v12. Production-cutover планируем после ваших коммитов в понедельник 27.04.

## Контекст

Это первая партия sandbox-статей после v12 (4B.1.9). Промпт без изменений. Нагенерили 3 темы по 3 разным форматам, чтобы оценить устойчивость v12 после паузы.

## Партия

| # | Slug / Тема | Категория | Формат | Слов | URL |
|---|---|---|---|---|---|
| 1 | wpc-paneli-v-ofise-kak-obnovit-interer-za-2-dnya-bez-ostanovki-raboty | wpc | guide (1) | **1479** | https://bamboodom.ru/article.html?slug=wpc-paneli-v-ofise-kak-obnovit-interer-za-2-dnya-bez-ostanovki-raboty&sandbox=1 |
| 2 | gibkaya-keramika-dlya-krylca-5-oshibok-pri-vybore-materiala | flex | отрасль (5) или comparison (2) | **1402** | https://bamboodom.ru/article.html?slug=gibkaya-keramika-dlya-krylca-5-oshibok-pri-vybore-materiala&sandbox=1 |
| 3 | reechnye-paneli-v-malenkoy-komnate-vizualnoe-rasshirenie-prostranstva | reiki | use-case (3) | **1471** | https://bamboodom.ru/article.html?slug=reechnye-paneli-v-malenkoy-komnate-vizualnoe-rasshirenie-prostranstva&sandbox=1 |

**Среднее: 1450 слов. 0/3 пробили hard min 1500.**

В партии 4B.1.9 v12 было 50% пробития (2/4). Теперь регресс — формально все три ниже минимума, но close (1402-1479). Возможно стоит передвинуть hard min на 1400 или подтянуть format-1/3/5 в v13. Хотим ваше мнение.

## Замечания валидатора по каждой статье

### Статья 1 — WPC офис

3 предупреждения, auto-retry не помог:
- Unknown article code 'XHS-L' mentioned in block #18 text (not a product-block)
- Unknown article code 'XHS-LA' mentioned in block #18 text (not a product-block)
- Draft is 1420 words (валидатор) / 1479 (DOM JS) — ниже hard min 1500

`XHS-L` и `XHS-LA` — это явные галлюцинации AI: он пытался по паттерну сократить XHS-L10/XHS-LA-* (если есть). В тексте они окажутся «не найдены» при ren-time резолвинге.

### Статья 2 — Flex керамика для крыльца

В тексте 15 уникальных F-артикулов: F001, F003, F004, F006, F007, F008, F009, F015, F030, F034, F038, F039, F045, F047, F048.

Просьба проверить:
- Все ли эти коды реально есть в `data/flex_articles.json` или эквиваленте?
- F045-F048 — это валидные позиции? Память говорит у flex 77 артикулов от F001-F077, но не уверены что в каталоге сейчас все.

### Статья 3 — Reiki малая комната

13 уникальных R-артикулов: R001-R036 (все в диапазоне R001-R050). Должны быть валидными по нашему knowledge base.

## Что нужно от вас

### Критично
1. **Общая оценка качества партии по вашей шкале** (как в 4B.1.9 v12 → 8.0/10).
2. **F-артикулы статьи 2** — все ли валидны (особенно F045-F048).
3. **Что блокирует production?** — если ничего не блокирует, в понедельник после ваших коммитов раскручиваем production-cutover на нашей стороне (`?sandbox=1` → `?sandbox=0`).

### Желательно
4. Готовы ли подтвердить эти 3 статьи как production-кандидатов (с правкой XHS-L → XHS-L10 и аналогичными тривиальными фиксами на нашей стороне), или нужна перегенерация?
5. Замечания по тонкости/SEO/брендингу/canonical — если вторничный коммит со Schema.org JSON-LD уже заехал, проверьте что эти 3 статьи правильно индексируемы.

### По длине (повторяющаяся проблема)
6. Ваше предложение: hard min остаётся 1500 (тогда v13 priority — добивать формат), или передвигаем на 1400 как новую планку? Партии 4B.1.9 + 4J в среднем дают 1430 — порог ощутимо bites.

## Что от нас задеплоено за время вашего ответа

После 4E мы существенно расширили админку seo-master:
- 4F: Аналитика из Я.Метрики (сводки/топ страниц/источники/запросы)
- 4G: Google Search Console (top queries/totals/pages, OAuth Web flow)
- 4H: Утренний дайджест по кнопке + автоматическое расписание 07:00 МСК через QStash
- 4I: DataForSEO Yandex SERP — позиции по 10 ключам с дельтой к прошлой неделе; keyword research по категориям
- 4G.tg: TG-канал @ecosteni — анонс новой production-статьи. Активируется после вашего production-cutover в понедельник.

## Дальнейшие планы (после вашего OK по партии)

1. Картинки через OpenRouter (Gemini Image / Flux), upload через ваш `blog_upload_image`.
2. Авто-анонс в VK-сообщество и Pinterest (помимо TG).
3. После 30+ production-статей — keyword research расширение и v13 промпт.

Жду ответ в обычном формате `LETTER_TO_SIDE_A_4J_review.md`.

— Александр (сторона A)
