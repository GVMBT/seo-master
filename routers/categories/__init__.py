"""Category routers: manage (CRUD)."""

from aiogram import Router

from routers.categories.manage import (
    CategoryCreateFSM,
    _format_category_card,
    _validate_category_name,
    cb_category_card,
    cb_category_delete,
    cb_category_delete_confirm,
    cb_category_feature_stub,
    cb_category_list,
    cb_category_new,
    cb_category_page,
    fsm_category_name,
)
from routers.categories.manage import (
    router as manage_router,
)

router = Router(name="categories")
router.include_router(manage_router)

__all__ = [
    "CategoryCreateFSM",
    "_format_category_card",
    "_validate_category_name",
    "cb_category_card",
    "cb_category_delete",
    "cb_category_delete_confirm",
    "cb_category_feature_stub",
    "cb_category_list",
    "cb_category_new",
    "cb_category_page",
    "fsm_category_name",
    "router",
]
