"""Projects sub-router — list, create, card."""

from aiogram import Router

from routers.projects import card, create
from routers.projects import list as project_list

router = Router()
router.include_router(project_list.router)
router.include_router(create.router)
router.include_router(card.router)
