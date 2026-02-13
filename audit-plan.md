Стоп. Этот план пытается сделать слишком много и в неправильный момент. Разберу по пунктам.

---

## Главная проблема: Phase mixing

Вы на Phase 8 (платежи). Этот план создаёт **полноценные клиенты** для DataForSEO и Firecrawl — это Phase 10. Claude Code хочет написать 2 новых сервиса с retry, error handling, тестами — и всё это будет лежать мёртвым кодом до Phase 10. А когда дойдёте до Phase 10, спеки DataForSEO/Firecrawl могут измениться, API могут обновиться, и код придётся переписывать.

**Правило: не пишите клиенты к API, которые не будете вызывать в текущей фазе.**

---

## Что НУЖНО сделать сейчас (перед Phase 8):

**✅ Правильно:**

- **1a. article_v5.yaml → article_v6.yaml** — да, промпт уже используется в Phase 6 тестах, обновить сейчас правильно. Но проверить: если `ArticleService.generate()` ссылается на `article_v5` по имени, то переименование сломает код
- **2. GenerationContext dataclass** — да, но `GenerationContext | dict[str, Any]` — плохая идея. Union type усложняет всё. Лучше: расширить существующий `GenerationRequest.context: dict` и добавить `GenerationContext` как фабрику/builder, который собирает dict. Так старый код не ломается
- **3. validate_images_meta()** — да, маленькое дополнение к существующему валидатору
- **8. Docstrings** — да, тривиально
- **9. DB migration** — да, три nullable колонки, ничего не ломает
- **10. Config** — да, optional поля с defaults

**❌ Не сейчас:**

- **4. FirecrawlClient** — Phase 10. Сейчас это мёртвый код
- **5. DataForSEOClient** — Phase 10. Мёртвый код
- **6. exports для несуществующих клиентов** — Phase 10
- **Тесты для FirecrawlClient/DataForSEOClient** — Phase 10

**⚠️ Нужно, но план неправильный:**

- **1b. keywords_cluster_v3.yaml** — YAML seed создать можно, но `keywords_v2.yaml as E03 fallback` значит что при любой ошибке нового пайплайна бот падает на старый. Это правильно, но нужно убедиться что KeywordService понимает оба формата. План не трогает `KeywordService.generate()` — только docstring. Этого мало
- **7. Cluster-aware rotation** — это **меняет работающий код** rotation в `publications.py`. Если кластерных данных ещё нет (Phase 10), а rotation уже cluster-aware — что произойдёт? План говорит "legacy mode fallback", но это нужно тщательно проверить. Одна ошибка — и автопубликация ломается

---

## Конкретные технические проблемы в плане:

**GenerationContext — слишком много полей с None:**

```python
main_phrase: str | None = None
secondary_phrases: str | None = None  
cluster_volume: int | None = None
main_volume: int | None = None
main_difficulty: int | None = None
cluster_type: str | None = None
competitor_analysis: str | None = None
competitor_gaps: str | None = None
```

14 optional полей — это не dataclass, это "мешок с данными". PromptEngine при рендеринге должен проверять каждое поле на None. Лучше:

```python
@dataclass
class ClusterContext:
    """Добавляется в Phase 10 когда есть DataForSEO данные"""
    main_phrase: str
    secondary_phrases: list[str]
    cluster_volume: int
    cluster_type: str

@dataclass 
class CompetitorContext:
    """Добавляется в Phase 10 когда есть Firecrawl данные"""
    analysis: str
    gaps: str
    avg_word_count: int

@dataclass
class GenerationContext:
    # Обязательные (есть всегда)
    company_name: str
    specialization: str
    keyword: str  # backward compat
    language: str = "ru"
    # Опциональные блоки (появляются в Phase 10)
    cluster: ClusterContext | None = None
    competitor: CompetitorContext | None = None
    images_count: int = 4
    # ... остальные
```

Так PromptEngine проверяет `if context.cluster:` один раз, а не 6 полей по отдельности.

**Rotation — опасное изменение:**

```python
# План:
if keywords[0] has "cluster_name" -> cluster mode, else legacy mode
```

Проверка формата данных в runtime через duck typing — хрупко. Если один keyword случайно имеет поле `cluster_name` а остальные нет — баг. Лучше явный флаг в категории:

```python
# В categories table:
keywords_format: "legacy" | "clustered"  # или просто проверять наличие clusters JSONB
```

**article_v6.yaml — max_tokens 8000 → 12000:**

Это увеличивает стоимость каждой генерации на 50% по output tokens. При Claude Sonnet: $15/M output → дополнительные 4000 tokens = +$0.06 на статью. При 5000 статей/мес = +$300/мес. Это нужно, если статьи реально станут длиннее (динамическая длина из конкурентного анализа). Но пока конкурентного анализа нет — зачем платить больше? Оставить 8000, поднять в Phase 10 когда появятся данные о конкурентах.

---

## Мой вердикт: разбить на два этапа

**Этап A — сейчас перед Phase 8 (30 минут):**

```
1. article_v5.yaml → article_v6.yaml (обновить промпт, 
   добавить images_meta в JSON-формат, оставить max_tokens 8000)
2. keywords_cluster_v3.yaml — создать YAML seed (не подключать)
3. validate_images_meta() — добавить метод
4. GenerationContext — добавить с вложенными dataclasses 
   (ClusterContext, CompetitorContext)
5. DB migration — 3 nullable колонки
6. Config — 3 optional env vars
7. Docstrings — обновить ссылки v5→v6
8. Тесты — для validate_images_meta() и GenerationContext
```

**Этап B — Phase 10 (когда дойдёте):**

```
1. FirecrawlClient + тесты
2. DataForSEOClient + тесты  
3. SerperClient + тесты
4. Cluster-aware rotation в publications.py
5. KeywordService — новый метод cluster()
6. max_tokens 8000 → 12000
7. Полная интеграция competitor_analysis в промпт
```

Скажите Claude Code:

> Раздели план на два этапа. Этап A — сейчас: промпт v6, YAML seed для clustering, validate_images_meta(), GenerationContext dataclass с вложенными ClusterContext/CompetitorContext, DB migration (3 колонки), config (3 env vars), docstrings, тесты для нового кода. Этап B (Phase 10) — FirecrawlClient, DataForSEOClient, cluster rotation, KeywordService.cluster(). НЕ создавай FirecrawlClient и DataForSEOClient сейчас — это мёртвый код до Phase 10. max_tokens оставь 8000, поднимем когда появится конкурентный анализ. Выполни только Этап A.
