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

### Phase 9 repository methods
- **PublicationsRepository.delete_old_logs(cutoff_iso)** — deletes publication_logs older than cutoff; used by CleanupService._delete_old_logs()
- **PreviewsRepository.get_active_drafts_by_project(project_id)** — non-expired draft previews for a project (E42: refund before project delete)
- **PreviewsRepository.get_expired_drafts()** — expired draft previews for daily cleanup
- **PreviewsRepository.atomic_mark_expired(preview_id)** — CAS update (status='draft' -> 'expired'), returns None if already processed (prevents double refund)

### Ротация кластеров ключевых фраз (docs/API_CONTRACTS.md §6)
1. Все кластеры категории, filter cluster_type="article"
2. Сортировка: total_volume DESC, avg_difficulty ASC
3. Исключить кластеры, использованные за 7 дней (publication_logs.keyword = main_phrase)
4. Первый доступный кластер (round-robin с приоритетом)
5. Все на cooldown → LRU (самый давний main_phrase)
6. < 3 кластеров → предупреждение (E22, E23)
- **NOTE**: текущий код (Phase 2) работает с flat-форматом. Рефакторинг на кластеры — Phase 10
