"""Seed prompt_versions table from YAML files in services/ai/prompts/.

Usage:
    uv run python scripts/seed_prompts.py

Requires: SUPABASE_URL and SUPABASE_KEY env vars (or .env file).
Skips existing (task_type, version) pairs — safe to re-run.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

# Map filename patterns to (task_type, version)
_PROMPT_MAP: dict[str, tuple[str, str]] = {
    "article_v7.yaml": ("article", "v7"),
    "article_v6.yaml": ("article", "v6"),
    "article_outline_v1.yaml": ("article_outline", "v1"),
    "article_critique_v1.yaml": ("article_critique", "v1"),
    "social_v3.yaml": ("social_post", "v3"),
    "keywords_v2.yaml": ("keywords", "v2"),
    "keywords_cluster_v3.yaml": ("keywords", "v3"),
    "image_v1.yaml": ("image", "v1"),
    "review_v1.yaml": ("review", "v1"),
    "description_v1.yaml": ("description", "v1"),
    "competitor_analysis_v1.yaml": ("competitor_analysis", "v1"),
}

# Which versions are active by default
_ACTIVE: set[tuple[str, str]] = {
    ("article", "v7"),
    ("article_outline", "v1"),
    ("article_critique", "v1"),
    ("social_post", "v3"),
    ("keywords", "v3"),
    ("image", "v1"),
    ("review", "v1"),
    ("description", "v1"),
    ("competitor_analysis", "v1"),
}


async def main() -> None:
    from postgrest import AsyncPostgrestClient

    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]

    client = AsyncPostgrestClient(
        f"{url}/rest/v1",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )

    prompts_dir = Path(__file__).resolve().parent.parent / "services" / "ai" / "prompts"
    seeded = 0
    skipped = 0

    for filename, (task_type, version) in _PROMPT_MAP.items():
        filepath = prompts_dir / filename
        if not filepath.exists():
            print(f"  SKIP {filename} — file not found")
            skipped += 1
            continue

        yaml_content = filepath.read_text(encoding="utf-8")
        is_active = (task_type, version) in _ACTIVE

        # Upsert: skip if exists
        try:
            resp = await (
                client.from_("prompt_versions").select("id").eq("task_type", task_type).eq("version", version).execute()
            )
            if resp.data:
                print(f"  EXISTS {task_type}/{version} — skip")
                skipped += 1
                continue

            await (
                client.from_("prompt_versions")
                .insert(
                    {
                        "task_type": task_type,
                        "version": version,
                        "prompt_yaml": yaml_content,
                        "is_active": is_active,
                    }
                )
                .execute()
            )
            label = "ACTIVE" if is_active else "inactive"
            print(f"  SEED {task_type}/{version} [{label}]")
            seeded += 1
        except Exception as e:
            print(f"  ERROR {task_type}/{version}: {e}")

    await client.aclose()
    print(f"\nDone: {seeded} seeded, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(main())
