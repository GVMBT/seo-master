"""Bamboodom.ru blog publishing API client (v1.1+).

Public surface:
    BamboodomClient           — async HTTP client
    KeyTestResponse           — response model for blog_key_test
    ContextResponse           — response model for blog_context
    ArticleCodesResponse      — response model for blog_article_codes
    PublishResponse           — response model for blog_publish
    BlockDropped              — entry in PublishResponse.blocks_dropped
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
    BlockDropped,
    ContextResponse,
    KeyTestResponse,
    PublishResponse,
)

__all__ = [
    "ArticleCodesResponse",
    "BamboodomAPIError",
    "BamboodomAuthError",
    "BamboodomClient",
    "BamboodomRateLimitError",
    "BlockDropped",
    "ContextResponse",
    "KeyTestResponse",
    "PublishResponse",
]
