"""Root router assembly — includes all sub-routers."""

from aiogram import Router

from routers.categories import router as categories_router
from routers.projects import router as projects_router
from routers.settings import router as settings_router
from routers.start import router as start_router


def setup_routers() -> Router:
    """Create root router with all sub-routers included."""
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(projects_router)
    root.include_router(categories_router)
    root.include_router(settings_router)
    return root
