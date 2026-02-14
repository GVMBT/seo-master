"""Root router assembly — includes all sub-routers."""

from aiogram import Router

from routers.analysis import router as analysis_router
from routers.categories import router as categories_router
from routers.payments import router as payments_router
from routers.platforms import router as platforms_router
from routers.profile import router as profile_router
from routers.projects import router as projects_router
from routers.publishing import router as publishing_router
from routers.settings import router as settings_router
from routers.start import router as start_router
from routers.tariffs import router as tariffs_router


def setup_routers() -> Router:
    """Create root router with all sub-routers included."""
    root = Router(name="root")
    root.include_router(start_router)
    root.include_router(projects_router)
    root.include_router(categories_router)
    root.include_router(platforms_router)
    root.include_router(publishing_router)
    root.include_router(analysis_router)
    root.include_router(profile_router)
    root.include_router(settings_router)
    root.include_router(tariffs_router)
    root.include_router(payments_router)
    return root
