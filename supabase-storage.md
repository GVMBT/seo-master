Вы выбрали правильный вариант. Base64 в JSONB — ловушка, которая выглядит простой, но создаёт реальные проблемы. Объясню почему.

**Base64 в JSONB — почему плохо на практике:**

4 изображения статьи × ~1.5MB PNG × 1.33 (base64 overhead) = **~8MB на одну запись** article_previews. PostgreSQL сохранит это в TOAST, но каждый SELECT этой строки (при нажатии "Опубликовать") вытягивает 8MB через wire. Vacuum на таблице с такими blob-ами — медленный. WAL-логи раздуваются. При 50 одновременных превью — 400MB в TOAST, при cleanup каждые 24ч PostgreSQL должен vacuum-ить гигабайты. Supabase Pro даёт 8GB — 5% БД уйдёт на временные картинки.

И главное: **Upstash Redis**. Между `generating` → `preview` в FSM state.data тоже нужно где-то держать ссылку на изображения. Если вы кладёте base64 в JSONB, возникает соблазн передать его через FSM state — а Upstash тарифицирует по объёму команд.

**Supabase Storage — почему подходит:**

Он уже в стеке (нулевая новая инфраструктура). Конкретная реализация:

```python
# services/storage.py
class ImageStorage:
    def __init__(self, supabase_client):
        self.bucket = "article-previews"  # создать один раз
    
    async def upload(self, image_bytes: bytes, preview_id: int, index: int) -> str:
        path = f"{preview_id}/{index}.png"
        await self.supabase.storage.from_(self.bucket).upload(
            path, image_bytes, {"content-type": "image/png"}
        )
        # Signed URL с TTL 25h (чуть больше preview TTL)
        return await self.supabase.storage.from_(self.bucket).create_signed_url(
            path, expires_in=90000
        )
    
    async def download(self, path: str) -> bytes:
        """При публикации: скачать → отдать publisher-у."""
        return await self.supabase.storage.from_(self.bucket).download(path)
    
    async def cleanup(self, preview_id: int):
        """Вызывается из /api/cleanup вместе с удалением article_previews."""
        await self.supabase.storage.from_(self.bucket).remove(
            [f"{preview_id}/{i}.png" for i in range(10)]  # safe over-delete
        )
```

**article_previews.images** остаётся JSONB, но хранит пути, а не blob-ы:

```json
[
  {"path": "42/0.png", "signed_url": "https://xxx.supabase.co/storage/v1/...", "width": 1024, "height": 1024},
  {"path": "42/1.png", "signed_url": "...", "width": 1024, "height": 1024}
]
```

**Bucket policy:** поставить lifecycle rule `expire_after: 48h` как страховку (если cleanup не сработал).

**Flow для publishers** — одно изменение в BasePublisher:

```python
# Было (implicit): publisher получает bytes напрямую
# Стало: publisher получает bytes через storage.download()

async def execute_publish(preview: ArticlePreview, storage: ImageStorage):
    images_bytes = [
        await storage.download(img["path"]) 
        for img in preview.images
    ]
    await publisher.publish(PublishRequest(..., images=images_bytes))
```

**Autopublish (QStash)** — изображения генерируются и публикуются в одном запросе, в Storage не попадают вообще. Storage нужен только для manual flow с Telegraph-превью.

Единственный минус: лишний round-trip при публикации (download из Storage → upload на платформу). При ~1.5MB и Supabase в том же регионе — ~200ms. Некритично.
