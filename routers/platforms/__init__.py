"""Platform routers: connections, settings."""

from aiogram import Router

from routers.platforms.connections import router as connections_router
from routers.platforms.settings import router as settings_router

router = Router(name="platforms")
router.include_router(connections_router)
router.include_router(settings_router)

__all__ = ["router"]
