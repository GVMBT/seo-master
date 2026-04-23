"""Bamboodom.ru blog publishing API client (v1.1+).

Public surface:
    BamboodomClient           — async HTTP client (key_test + cached context/codes)
    KeyTestResponse           — response model for blog_key_test
    ContextResponse           — response model for blog_context
    ArticleCodesResponse      — response model for blog_article_codes
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
from integrations.bamboodom.models import (
    ArticleCodesResponse,
    ContextResponse,
    KeyTestResponse,
)

__all__ = [
    "ArticleCodesResponse",
    "BamboodomAPIError",
    "BamboodomAuthError",
    "BamboodomClient",
    "BamboodomRateLimitError",
    "ContextResponse",
    "KeyTestResponse",
]
