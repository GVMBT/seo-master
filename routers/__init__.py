"""Router setup — includes all sub-routers."""

from aiogram import Router

from routers import start
from routers.categories import router as categories_router
from routers.platforms import router as platforms_router
from routers.projects import router as projects_router


def setup_routers() -> Router:
    """Create top-level router with all sub-routers included."""
    router = Router()
    router.include_router(start.router)
    router.include_router(projects_router)
    router.include_router(categories_router)
    router.include_router(platforms_router)
    return router
