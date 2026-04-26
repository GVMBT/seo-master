"""OpenRouter image generation (4K.1).

OpenRouter поддерживает text→image модели через chat-completions endpoint:
- google/gemini-2.5-flash-image-preview — Gemini 2.5 Image (Imagen 3)
- black-forest-labs/flux-1.1-pro — Flux 1.1 Pro

Возвращает URL картинки (если модель отдаёт её через response_format=url)
или base64 для случаев когда нет внешнего URL.

Используется через OPENROUTER_API_KEY (уже в env).
"""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from bot.config import get_settings

log = structlog.get_logger()

_API_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "google/gemini-2.5-flash-image-preview"
_DEFAULT_TIMEOUT = 60.0
_MAX_RETRIES = 1


class OpenRouterImageError(Exception):
    """Generic error from OpenRouter image generation."""


@dataclass
class ImageResult:
    """Сгенерированная картинка."""

    url: str | None = None
    data_b64: str | None = None  # если модель не отдала URL
    mime_type: str = "image/png"


class OpenRouterImageClient:
    """Async-клиент для генерации картинок через OpenRouter."""

    def __init__(
        self,
        api_key: str = "",
        model: str = _DEFAULT_MODEL,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        s = get_settings()
        self._api_key = api_key or s.openrouter_api_key.get_secret_value()
        self._model = model
        self._timeout = timeout

    async def generate(
        self,
        prompt: str,
        *,
        aspect_ratio: str = "16:9",
        size: str = "1024x576",
    ) -> ImageResult:
        """Генерирует картинку по промпту.

        OpenRouter chat-completions с image_generation: true для image моделей.
        Ответ содержит content с image_url или base64.
        """
        if not self._api_key:
            raise OpenRouterImageError("OPENROUTER_API_KEY не настроен")
        if not prompt:
            raise OpenRouterImageError("Empty prompt")

        # Формат для image gen через OpenRouter (Gemini Image)
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "modalities": ["image", "text"],
        }

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://bamboodom.ru",
            "X-Title": "bamboodom-recrawl-bot",
        }

        last_err: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(
                        f"{_API_BASE}/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=self._timeout,
                    )
                if resp.status_code >= 500 and attempt < _MAX_RETRIES:
                    await asyncio.sleep(1.5)
                    continue
                if resp.status_code >= 400:
                    raise OpenRouterImageError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                return self._parse_response(resp.json())
            except httpx.TimeoutException as exc:
                last_err = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1.5)
                    continue
                raise OpenRouterImageError(f"Timeout: {exc}") from exc
            except httpx.RequestError as exc:
                last_err = exc
                if attempt < _MAX_RETRIES:
                    await asyncio.sleep(1.5)
                    continue
                raise OpenRouterImageError(f"Network: {exc}") from exc

        raise OpenRouterImageError(f"Exhausted retries: {last_err!r}")

    @staticmethod
    def _parse_response(data: dict[str, Any]) -> ImageResult:
        choices = data.get("choices") or []
        if not choices:
            raise OpenRouterImageError(f"No choices in response: {data}")
        msg = (choices[0] or {}).get("message") or {}

        # Gemini Image в OpenRouter возвращает images: [{type, image_url:{url}}]
        # или прямо в content
        images = msg.get("images") or []
        if images:
            for it in images:
                if not isinstance(it, dict):
                    continue
                # Формат: {"type": "image_url", "image_url": {"url": "data:image/png;base64,..." | "https://..."}}
                iu = it.get("image_url")
                url = iu.get("url") or "" if isinstance(iu, dict) else iu or ""
                if isinstance(url, str) and url.startswith("data:"):
                    # data:image/png;base64,XXXX
                    head, _, b64 = url.partition(",")
                    mime = "image/png"
                    if "image/" in head:
                        mime = head.split(":", 1)[1].split(";", 1)[0]
                    return ImageResult(data_b64=b64, mime_type=mime)
                if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
                    return ImageResult(url=url)

        # Альтернатива: content может быть list со строкой+image
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "image_url":
                    iu = part.get("image_url") or {}
                    url = iu.get("url") if isinstance(iu, dict) else iu
                    if isinstance(url, str) and url.startswith("data:"):
                        head, _, b64 = url.partition(",")
                        return ImageResult(data_b64=b64, mime_type="image/png")
                    if isinstance(url, str):
                        return ImageResult(url=url)

        raise OpenRouterImageError(f"No image in response: {str(data)[:300]}")

    @staticmethod
    def decode_b64(b64: str) -> bytes:
        """Helper: декодирует base64 → bytes для записи в файл."""
        return base64.b64decode(b64)
