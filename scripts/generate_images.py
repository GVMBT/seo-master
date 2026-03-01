"""Generate bot UI images via OpenRouter Gemini API.

Usage:
    uv run python scripts/generate_images.py [--prompt "custom prompt"] [--name filename]
    uv run python scripts/generate_images.py --all  # generate all bot images
"""

from __future__ import annotations

import argparse
import base64
import binascii
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
ASSETS_DIR = Path(__file__).parent.parent / "assets"
ASSETS_DIR.mkdir(exist_ok=True)

# Model for image generation
IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"

# Style guide for consistency across all images
STYLE_PREFIX = (
    "Modern flat illustration style, clean vector-like design, "
    "professional color palette (deep navy #1A2744, bright teal #00C9A7, "
    "warm orange #FF6B35, light gray #F5F7FA background), "
    "polished, high quality, sharp details. "
    "Any text MUST be in Russian (Cyrillic script), spelled correctly, "
    "rendered crisp and legible. "
)

# All bot images to generate
IMAGE_PROMPTS: dict[str, dict[str, str]] = {
    "avatar": {
        "prompt": (
            "Square app icon for a Telegram bot called «SEO Master». "
            "Bold letters «SM» in the center, stylized as a modern tech logo. "
            "Behind the letters: a subtle glowing neural network pattern. "
            "A small upward rocket trail accent from the bottom-right. "
            "Icon style, must be recognizable at 64x64 pixels. "
            "Deep navy background with teal and orange gradient accents."
        ),
        "aspect_ratio": "1:1",
    },
    "welcome": {
        "prompt": (
            "Welcome banner for a Telegram bot. "
            "Title text: «SEO Master» in large bold font at the top center. "
            "Subtitle: «AI-контент для вашего бизнеса» below the title in smaller text. "
            "Center: a friendly teal robot character holding a glowing document/article. "
            "Floating around it: a bar chart trending up, a magnifying glass with 'SEO', "
            "a WordPress icon, a Telegram paper plane, image thumbnails, keyword tags. "
            "Bottom: a subtle gradient line separating the illustration from whitespace. "
            "Professional, welcoming, tech-forward atmosphere."
        ),
        "aspect_ratio": "16:9",
    },
    "tariffs": {
        "prompt": (
            "Three pricing tier cards for a token-based service, arranged left to right. "
            "Card 1 (left, smallest, teal border): header «Старт», "
            "big text «500» with a small coin icon, subtitle «500 ₽». "
            "Card 2 (center, medium, navy border, slight glow): header «Стандарт», "
            "big text «2 000», subtitle «1 600 ₽», a 'popular' ribbon/badge. "
            "Card 3 (right, largest, orange-gold border, bright glow): header «Про», "
            "big text «5 000», subtitle «3 000 ₽», a star/premium icon. "
            "Golden token coins scattered between the cards. "
            "Each card has a subtle shadow and rounded corners. "
            "Clean white background with soft gradient."
        ),
        "aspect_ratio": "16:9",
    },
    "payment_success": {
        "prompt": (
            "Celebration banner for successful payment. "
            "Center: a large glowing green checkmark inside a circle. "
            "Text above: «Оплата прошла!» in bold. "
            "Text below: «Токены начислены» in lighter font. "
            "Golden coins and colorful confetti falling from top. "
            "Subtle sparkle particles around the checkmark. "
            "Joyful, rewarding feeling. Light background with warm gradient."
        ),
        "aspect_ratio": "16:9",
    },
    "empty_projects": {
        "prompt": (
            "Empty state illustration for 'no projects yet'. "
            "Center: an open empty briefcase/portfolio with a large teal «+» button above it. "
            "A small friendly robot standing next to it, gesturing towards the plus. "
            "Text below: «Создайте первый проект» in medium font. "
            "Soft, encouraging, light pastel background. "
            "Clean and simple, not cluttered."
        ),
        "aspect_ratio": "4:3",
    },
    "empty_categories": {
        "prompt": (
            "Empty state illustration for 'no content categories'. "
            "Center: an open empty folder with a sparkle/star emerging from it. "
            "Floating translucent tags nearby: «SEO», «Рецепты», «Технологии» — "
            "as example topics fading in from transparent to visible. "
            "Text below: «Добавьте тему контента» in medium font. "
            "Soft pastel colors, inviting mood."
        ),
        "aspect_ratio": "4:3",
    },
    "empty_connections": {
        "prompt": (
            "Empty state illustration for 'no platform connections'. "
            "Center: a hub/circle with connection ports radiating outward. "
            "Around it: recognizable platform icons — WordPress 'W', Telegram paper plane, "
            "VK logo, Pinterest 'P' — as puzzle pieces floating nearby, ready to snap in. "
            "One piece (WordPress) is being placed by a small robot hand. "
            "Text below: «Подключите платформу» in medium font. "
            "Technical but friendly, light background."
        ),
        "aspect_ratio": "4:3",
    },
    "generation_progress": {
        "prompt": (
            "Content generation pipeline banner with 4 stages as connected nodes, left to right. "
            "Stage 1: magnifying glass icon, label «Сбор данных». "
            "Stage 2: bar chart icon, label «Анализ». "
            "Stage 3: pen/document icon with AI sparkle, label «Генерация». "
            "Stage 4: image/photo icon, label «Изображения». "
            "A glowing teal progress line connects all 4 stages. "
            "Stages 1-2 have green checkmarks (done), stage 3 has a pulsing glow (active), "
            "stage 4 is dimmed (pending). "
            "Wide banner, clean layout, professional."
        ),
        "aspect_ratio": "16:9",
    },
    "error": {
        "prompt": (
            "Friendly error illustration. "
            "Center: a small cute teal robot looking confused, "
            "with a yellow warning triangle above its head. "
            "A tangled cable/wire in front of it. "
            "A circular 'retry' arrow icon glowing nearby. "
            "Text at bottom: «Попробуйте ещё раз» in medium font. "
            "Warm soft colors, NOT scary — encouraging and light."
        ),
        "aspect_ratio": "4:3",
    },
    "referral": {
        "prompt": (
            "Referral program banner. "
            "Left side: a person icon sending a glowing link/chain to the right. "
            "Right side: another person icon receiving it. "
            "Between them: golden coins flowing along the link path. "
            "A large «10%» in bold orange text in the center-top area. "
            "Text below: «Приглашайте друзей» in bold, «получайте бонус с каждой покупки» smaller. "
            "Gift box with a ribbon accent in the corner. "
            "Warm, generous, rewarding mood."
        ),
        "aspect_ratio": "16:9",
    },
    "project_card": {
        "prompt": (
            "Project card illustration for a content management bot. "
            "Center: a sleek project folder/binder with a glowing company logo placeholder. "
            "Around it: floating icons — a globe (website), a document with sparkle (content), "
            "a calendar (schedule), connection plugs (platforms). "
            "Organized, structured, professional feel. "
            "Clean light background with subtle grid pattern."
        ),
        "aspect_ratio": "4:3",
    },
    "profile": {
        "prompt": (
            "User profile illustration for a Telegram bot. "
            "Center: a circular user avatar placeholder with a subtle glow ring around it. "
            "Below: a small dashboard with stats — bar chart, token counter, "
            "notification bell, referral link icon. "
            "Gear/settings icon in the corner. "
            "Personal, warm, organized feeling. Clean light background."
        ),
        "aspect_ratio": "4:3",
    },
    "admin": {
        "prompt": (
            "Admin panel illustration. "
            "Center: a control panel/dashboard with multiple screens and monitors. "
            "Showing: a user count graph, API cost meter, system health indicators "
            "(green checkmarks for DB and Redis), broadcast megaphone icon. "
            "A shield/admin badge in the top corner. "
            "Professional, technical, commanding. "
            "Dark navy background with teal and orange data visualization accents."
        ),
        "aspect_ratio": "4:3",
    },
}


def generate_image(
    prompt: str,
    name: str,
    aspect_ratio: str = "1:1",
) -> Path | None:
    """Generate a single image via OpenRouter Gemini API."""
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set in .env")
        return None

    full_prompt = STYLE_PREFIX + prompt

    print(f"Generating '{name}' ({aspect_ratio})...")

    with httpx.Client(timeout=120) as client:
        resp = client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": IMAGE_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": full_prompt,
                    }
                ],
                "modalities": ["image", "text"],
                "image_config": {
                    "aspect_ratio": aspect_ratio,
                },
                "max_tokens": 1024,
            },
        )

    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:500]}")
        return None

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        print(f"  ERROR: No choices in response: {data}")
        return None

    # Extract image from response — OpenRouter returns images in message.images[]
    message = choices[0].get("message", {})
    images = message.get("images", [])

    # Fallback: check content (list of parts) if images field is empty
    image_data = None
    if images:
        img = images[0]
        url = ""
        if isinstance(img, dict):
            url = img.get("image_url", {}).get("url", "")
        elif isinstance(img, str):
            url = img
        if url.startswith("data:image/"):
            image_data = url.split(",", 1)[1] if "," in url else None
    else:
        content = message.get("content", "")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:image/"):
                        image_data = url.split(",", 1)[1] if "," in url else None
                    break

    if not image_data:
        print("  ERROR: No image data found in response")
        print(f"  Message keys: {list(message.keys())}")
        text = message.get("content", "")
        if isinstance(text, str) and text:
            print(f"  Text response: {text[:200]}")
        return None

    # Decode and save
    try:
        img_bytes = base64.b64decode(image_data)
    except binascii.Error as e:
        print(f"  ERROR decoding base64: {e}")
        return None

    # Detect format from header bytes
    if img_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        ext = "png"
    elif img_bytes[:4] == b"RIFF":
        ext = "webp"
    elif img_bytes[:3] == b"\xff\xd8\xff":
        ext = "jpg"
    else:
        ext = "png"

    out_path = ASSETS_DIR / f"{name}.{ext}"
    out_path.write_bytes(img_bytes)
    size_kb = len(img_bytes) / 1024
    print(f"  Saved: {out_path} ({size_kb:.1f} KB)")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate bot UI images")
    parser.add_argument("--prompt", help="Custom prompt for single image")
    parser.add_argument("--name", default="custom", help="Output filename (without extension)")
    parser.add_argument("--aspect-ratio", default="1:1", help="Aspect ratio (1:1, 16:9, 4:3)")
    parser.add_argument("--all", action="store_true", help="Generate all predefined images")
    parser.add_argument("--only", nargs="+", choices=list(IMAGE_PROMPTS.keys()), help="Generate specific images")
    args = parser.parse_args()

    if args.all:
        results: dict[str, Path | None] = {}
        for i, (img_name, img_config) in enumerate(IMAGE_PROMPTS.items()):
            if i > 0:
                time.sleep(2)
            path = generate_image(
                prompt=img_config["prompt"],
                name=img_name,
                aspect_ratio=img_config["aspect_ratio"],
            )
            results[img_name] = path
            print()

        print("\n=== Results ===")
        for img_name, path in results.items():
            status = f"OK: {path}" if path else "FAILED"
            print(f"  {img_name}: {status}")

    elif args.only:
        for img_name in args.only:
            config = IMAGE_PROMPTS[img_name]
            generate_image(
                prompt=config["prompt"],
                name=img_name,
                aspect_ratio=config["aspect_ratio"],
            )
            print()

    elif args.prompt:
        generate_image(
            prompt=args.prompt,
            name=args.name,
            aspect_ratio=args.aspect_ratio,
        )
    else:
        print("Usage:")
        print("  --all              Generate all images")
        print("  --only avatar welcome  Generate specific images")
        print('  --prompt "..."     Custom prompt')
        print()
        print("Available images:", ", ".join(IMAGE_PROMPTS.keys()))


if __name__ == "__main__":
    main()
