"""Category routers: manage (CRUD) + keywords (generation/upload FSMs)."""

from aiogram import Router

from routers.categories.keywords import (
    KeywordGenerationFSM,
    KeywordUploadFSM,
    cb_keywords_main,
    cb_kw_confirm,
    cb_kw_generate_start,
    cb_kw_quantity,
    cb_kw_save,
    cb_kw_upload_save,
    cb_kw_upload_start,
    fsm_kw_geography,
    fsm_kw_products,
    fsm_kw_upload_file,
)
from routers.categories.keywords import (
    router as keywords_router,
)
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
router.include_router(keywords_router)
router.include_router(manage_router)

__all__ = [
    "CategoryCreateFSM",
    "KeywordGenerationFSM",
    "KeywordUploadFSM",
    "_format_category_card",
    "_validate_category_name",
    "cb_category_card",
    "cb_category_delete",
    "cb_category_delete_confirm",
    "cb_category_feature_stub",
    "cb_category_list",
    "cb_category_new",
    "cb_category_page",
    "cb_keywords_main",
    "cb_kw_confirm",
    "cb_kw_generate_start",
    "cb_kw_quantity",
    "cb_kw_save",
    "cb_kw_upload_save",
    "cb_kw_upload_start",
    "fsm_category_name",
    "fsm_kw_geography",
    "fsm_kw_products",
    "fsm_kw_upload_file",
    "router",
]
