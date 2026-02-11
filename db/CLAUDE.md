# Модуль db/ — База данных

## 13 таблиц (docs/ARCHITECTURE.md §3)
users, projects, platform_connections, categories, platform_content_overrides,
platform_schedules, publication_logs, token_expenses, payments,
site_audits, site_brandings, article_previews, prompt_versions

## Паттерн Repository
- Все запросы через repository, НЕ напрямую
- Параметризованные запросы ВСЕГДА (никакого f-string SQL)
- credentials: шифрование/расшифровка ТОЛЬКО в repository layer (CredentialManager)
- Supabase client: async, service_role key

## Критические паттерны

### Удаление с QStash (E11, E24)
```python
async def delete_category(category_id):
    schedules = await repo.get_schedules_by_category(category_id)
    for s in schedules:
        for sid in (s.qstash_schedule_ids or []):
            await qstash.schedules.delete(sid)
    await repo.delete_category(category_id)  # CASCADE
```

### Credentials
- platform_connections.credentials: TEXT + Fernet encryption (НЕ JSONB)
- CredentialManager: encrypt(dict) → str, decrypt(str) → dict
- UNIQUE(project_id, platform_type, identifier)

### Наследование настроек контента (F41)
```python
def get_content_settings(category_id, platform_type):
    override = overrides.get(category_id, platform_type)
    if override and override.image_settings is not None:
        return override
    return categories.get(category_id)  # fallback
```

### Ротация ключевых фраз (docs/API_CONTRACTS.md §6)
1. Все фразы категории, отсортированные volume DESC, difficulty ASC
2. Исключить использованные за 7 дней (publication_logs)
3. Первая доступная (round-robin с приоритетом)
4. Все на cooldown → LRU (самая давняя)
5. < 5 фраз → предупреждение (E22, E23)
