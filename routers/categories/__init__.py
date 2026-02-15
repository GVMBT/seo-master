"""Category routers: manage (CRUD) + keywords + description + reviews + prices + media."""

from aiogram import Router

from routers.categories.description import DescriptionGenerateFSM
from routers.categories.description import router as description_router
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
from routers.categories.media import router as media_router
from routers.categories.prices import PriceInputFSM
from routers.categories.prices import router as prices_router
from routers.categories.reviews import ReviewGenerationFSM
from routers.categories.reviews import router as reviews_router

router = Router(name="categories")
# Sub-routers: specific features BEFORE manage (manage has catch-all stub)
router.include_router(description_router)
router.include_router(reviews_router)
router.include_router(prices_router)
router.include_router(media_router)
router.include_router(keywords_router)
router.include_router(manage_router)

__all__ = [
    "CategoryCreateFSM",
    "DescriptionGenerateFSM",
    "KeywordGenerationFSM",
    "KeywordUploadFSM",
    "PriceInputFSM",
    "ReviewGenerationFSM",
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
