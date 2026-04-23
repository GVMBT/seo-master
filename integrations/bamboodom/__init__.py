"""Bamboodom.ru blog publishing API client (v1.1+).

Public surface (Session 1):
    BamboodomClient           — async HTTP client
    KeyTestResponse           — pydantic model for blog_key_test response
    BamboodomAPIError         — base exception
    BamboodomAuthError        — 401 or missing/empty key
    BamboodomRateLimitError   — 429 with Retry-After
"""

from integrations.bamboodom.client import BamboodomClient
from integrations.bamboodom.exceptions import (
    BamboodomAPIError,
    BamboodomAuthError,
    BamboodomRateLimitError,
)
from integrations.bamboodom.models import KeyTestResponse

__all__ = [
    "BamboodomAPIError",
    "BamboodomAuthError",
    "BamboodomClient",
    "BamboodomRateLimitError",
    "KeyTestResponse",
]
