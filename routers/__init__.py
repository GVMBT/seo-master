"""Router setup — includes all sub-routers."""

from aiogram import Router

from routers import payments, profile, start, tariffs
from routers.admin import router as admin_router
from routers.categories import router as categories_router
from routers.platforms import router as platforms_router
from routers.projects import router as projects_router
from routers.publishing import router as publishing_router


def setup_routers() -> Router:
    """Create top-level router with all sub-routers included.

    Order matters: specific routers first, start.router LAST
    (it contains catch-all handlers like pipeline_stale_catchall).
    """
    router = Router()
    router.include_router(projects_router)
    router.include_router(categories_router)
    router.include_router(platforms_router)
    router.include_router(profile.router)
    router.include_router(tariffs.router)
    router.include_router(payments.router)
    router.include_router(publishing_router)
    router.include_router(admin_router)
    router.include_router(start.router)  # last: /start, /cancel, nav, stubs, catch-alls
    return router
