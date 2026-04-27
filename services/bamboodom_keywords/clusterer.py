"""AI-based clustering of bamboodom keywords by theme (4Y, 2026-04-27).

Calls OpenRouter directly (not through AIOrchestrator) because this is a
simple one-shot JSON task that doesn't fit the prompt-version workflow.
The model groups phrases into 4 theme labels per material:

    - "выбор"      — how to choose, what to look at, comparison criteria
    - "монтаж"     — installation, DIY, mounting steps
    - "сравнение"  — A vs B, alternatives, head-to-head
    - "use-case"   — for-room/for-purpose ("для бассейна", "в спальне")

Output: list of (keyword, cluster_label) tuples. Cluster id is assigned
locally — same label across calls within a material gets the same id.
"""

from __future__ import annotations

import json

import httpx
import structlog

log = structlog.get_logger()

_CLUSTER_MODEL = "anthropic/claude-haiku-4.5"
_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_TIMEOUT = 60.0
_MAX_KEYWORDS_PER_CALL = 200  # batch size; LLM handles 200 phrases easily

# Canonical theme labels — keep in sync between prompt and downstream UI.
THEME_LABELS: tuple[str, ...] = ("выбор", "монтаж", "сравнение", "use-case", "общее")


_SYSTEM_PROMPT = (
    "Ты SEO-кластеризатор для русскоязычных строительных запросов. "
    "На вход — JSON-массив ключевых фраз про один материал отделки "
    "(WPC панели, гибкий камень, реечные панели или алюминиевые профили). "
    "Твоя задача — присвоить каждой фразе ОДИН из 5 тематических ярлыков:\n"
    "1. \"выбор\" — как выбрать, на что смотреть, обзор, рейтинг, какие бывают\n"
    "2. \"монтаж\" — как смонтировать, своими руками, инструкция, крепление, установка\n"
    "3. \"сравнение\" — A или B, vs, чем отличается, что лучше, разница\n"
    "4. \"use-case\" — для конкретного помещения/назначения (для бассейна, на потолок, в спальне, для дачи)\n"
    "5. \"общее\" — всё остальное (бренды, цены без контекста, общие термины)\n\n"
    "ВАЖНО: ярлык всегда из этого списка дословно, никаких других значений. "
    "Если фраза подходит к нескольким — выбирай самый специфичный (use-case > сравнение > монтаж > выбор > общее)."
)


_USER_TEMPLATE = (
    "Материал: {material_label}\n\n"
    "Ключевые фразы (JSON-массив):\n{phrases_json}\n\n"
    "Верни ответ строго в виде JSON-массива объектов: "
    "[{{\"keyword\": \"...\", \"label\": \"...\"}}, ...]. "
    "Без пояснений, без markdown-обёртки ```. Только массив."
)


_MATERIAL_LABELS = {
    "wpc": "WPC панели (террасная доска, стеновые панели)",
    "flex": "гибкий камень (гибкая керамика для отделки)",
    "reiki": "реечные панели (декор для стен и потолка)",
    "profiles": "алюминиевые профили XHS (монтажная фурнитура)",
}


async def cluster_keywords(
    keywords: list[str],
    material: str,
    api_key: str,
    *,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, str]:
    """Cluster a list of phrases into theme labels.

    Returns a mapping {keyword: cluster_label}. Phrases that the LLM omits
    fall back to "общее". Empty input returns empty dict.

    The function batches input into chunks of _MAX_KEYWORDS_PER_CALL.
    """
    if not keywords:
        return {}
    material_label = _MATERIAL_LABELS.get(material, material)

    own_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=_TIMEOUT)

    out: dict[str, str] = {}
    try:
        for i in range(0, len(keywords), _MAX_KEYWORDS_PER_CALL):
            chunk = keywords[i : i + _MAX_KEYWORDS_PER_CALL]
            user = _USER_TEMPLATE.format(
                material_label=material_label,
                phrases_json=json.dumps(chunk, ensure_ascii=False),
            )
            payload = {
                "model": _CLUSTER_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
                "max_tokens": 4000,
            }
            try:
                resp = await client.post(
                    _OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                content = (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )
                # Strip optional markdown wrapper
                if content.startswith("```"):
                    content = content.strip("`").lstrip("json").strip()
                items = json.loads(content)
                for item in items:
                    kw = (item.get("keyword") or "").strip()
                    lbl = (item.get("label") or "").strip().lower()
                    if not kw:
                        continue
                    if lbl not in THEME_LABELS:
                        lbl = "общее"
                    out[kw] = lbl
            except Exception as exc:
                log.warning(
                    "bbk_cluster_chunk_failed",
                    error=str(exc)[:200],
                    chunk_size=len(chunk),
                )
                # Fallback: tag the whole chunk as "общее" so save still works
                for kw in chunk:
                    out.setdefault(kw, "общее")
    finally:
        if own_client:
            await client.aclose()

    # Anything missed → "общее"
    for kw in keywords:
        out.setdefault(kw, "общее")

    log.info(
        "bbk_cluster_done",
        material=material,
        total=len(keywords),
        labels={lbl: sum(1 for v in out.values() if v == lbl) for lbl in THEME_LABELS},
    )
    return out


def label_to_cluster_id(label: str) -> int:
    """Map theme label to a stable integer cluster_id (1..5)."""
    try:
        return THEME_LABELS.index(label) + 1
    except ValueError:
        return 5  # "общее"
