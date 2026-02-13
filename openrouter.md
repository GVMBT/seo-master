Поправки к плану Phase 6 перед стартом:
КРИТИЧНО: Исправить model slug — google/gemini-2.5-flash-image → google/gemini-3-pro-image-preview в MODEL_CHAINS.

Убрать streaming из Phase 6. generate() — non-streaming с response_format: json_schema + plugins: [{"id": "response-healing"}]. generate_stream() — stub raise NotImplementedError("Phase 7+"). Причина: статья отдаётся через Telegraph-превью, стримить JSON в чат бессмысленно. F34 закрывается progress indicator-ом (таймер + editMessageText) — задача роутера, не AI service.

require_parameters: true — добавить как default в provider config для ВСЕХ запросов с response_format: json_schema. Без этого fallback-модели могут попасть на провайдера без поддержки structured outputs (документация OpenRouter подтверждает).

heal_response — один путь (non-streaming only). OpenRouter response-healing plugin чинит синтаксис JSON (missing brackets, trailing commas, markdown wrappers). Application-level heal_response как backup: json.loads() → regex fixes → бюджетная модель → GenerationError. После успешного parse — проверять обязательные поля схемы (plugin НЕ проверяет schema adherence, только syntax).

asyncio.Semaphore(10) в AIOrchestrator.__init__ — backpressure при autopublish storm (200 QStash webhooks в 09:00).

PROMPT_CACHE_TTL — поднять 300 → 3600. Промпты меняются только при sync_prompts CLI.

CompetitorAnalysisService — пометить "deferred P2". YAML seed competitor_analysis_v1.yaml создаётся, service файл — нет.



ImageService response parsing — ответ Gemini содержит content array с items типа "image" (base64 data URL) и "text", не просто строку. Парсить choices[0].message.content как list, извлекать image items.



Никаких LangChain / Instructor / LiteLLM. OpenAI SDK (AsyncOpenAI) + OpenRouter достаточно. Единственная новая зависимость — nh3.



ImageService возвращает list[GeneratedImage] (bytes), storage.upload() вызывается caller-ом (router или ArticleService), не внутри ImageService.
