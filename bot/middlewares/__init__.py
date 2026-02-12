"""Aiogram middleware chain (ARCHITECTURE.md §2.1)."""

from bot.middlewares.auth import AuthMiddleware, FSMInactivityMiddleware
from bot.middlewares.db import DBSessionMiddleware
from bot.middlewares.logging import LoggingMiddleware
from bot.middlewares.throttling import ThrottlingMiddleware

__all__ = [
    "AuthMiddleware",
    "DBSessionMiddleware",
    "FSMInactivityMiddleware",
    "LoggingMiddleware",
    "ThrottlingMiddleware",
]
