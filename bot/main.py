"""Bot startup: webhook, middleware chain, client lifecycle."""

import asyncio
import logging

import httpx
import sentry_sdk
import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import ErrorEvent
from aiohttp import web

from bot.config import Settings, get_settings
from bot.exceptions import AppError
from bot.middlewares import (
    AuthMiddleware,
    DBSessionMiddleware,
    FSMInactivityMiddleware,
    LoggingMiddleware,
    ThrottlingMiddleware,
)
from cache.client import RedisClient
from cache.fsm_storage import UpstashFSMStorage
from db.client import SupabaseClient
from services.ai.orchestrator import AIOrchestrator
from services.ai.prompt_engine import PromptEngine
from services.ai.rate_limiter import RateLimiter
from services.storage import ImageStorage

log = structlog.get_logger()

# Graceful shutdown coordination (ARCHITECTURE.md §5.7)
SHUTDOWN_EVENT: asyncio.Event = asyncio.Event()
PUBLISH_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(10)


def _init_sentry(dsn: str) -> None:
    """Initialize Sentry SDK if DSN is configured."""
    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0.1)
        log.info("sentry_initialized")


def create_bot(settings: Settings) -> Bot:
    """Create Bot instance with HTML parse mode."""
    return Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def create_http_client() -> httpx.AsyncClient:
    """Create shared httpx client (ARCHITECTURE.md §2.2)."""
    return httpx.AsyncClient(
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        timeout=httpx.Timeout(30.0, connect=5.0),
    )


def create_dispatcher(
    db: SupabaseClient,
    redis: RedisClient,
    http_client: httpx.AsyncClient,
    settings: Settings,
) -> Dispatcher:
    """Create Dispatcher with FSM storage and full middleware chain."""
    storage = UpstashFSMStorage(redis, state_ttl=settings.fsm_ttl_seconds)
    dp = Dispatcher(storage=storage)

    # Outer middleware (#1): inject shared clients for ALL updates
    dp.update.outer_middleware(DBSessionMiddleware(db, redis, http_client))

    # Inner middleware (#2-#5) on all event types we handle
    for observer in (dp.message, dp.callback_query, dp.pre_checkout_query):
        observer.middleware(AuthMiddleware(settings.admin_ids))
        observer.middleware(ThrottlingMiddleware(redis))
        observer.middleware(FSMInactivityMiddleware(settings.fsm_inactivity_timeout))
        observer.middleware(LoggingMiddleware())

    # Global error handler
    dp.errors.register(_global_error_handler)

    return dp


async def _global_error_handler(event: ErrorEvent) -> bool:
    """Catch all unhandled exceptions: log + Sentry capture + notify user.

    FSM is NOT cleared on error (user can retry).
    """
    # Suppress harmless "message is not modified" errors (double-click on same button)
    if isinstance(event.exception, TelegramBadRequest) and "is not modified" in str(event.exception):
        log.debug("message_not_modified", exc_info=False)
        return True

    sentry_sdk.capture_exception(event.exception)

    log.error(
        "unhandled_error",
        exception=str(event.exception),
        exc_info=event.exception,
    )

    user_message = "Произошла ошибка. Попробуйте позже."
    if isinstance(event.exception, AppError):
        user_message = event.exception.user_message

    # Try to send error message to user
    update = event.update
    if update and update.message:
        await update.message.answer(user_message)
    elif update and update.callback_query:
        await update.callback_query.answer(user_message[:200], show_alert=True)
    elif update and update.pre_checkout_query:
        await update.pre_checkout_query.answer(ok=False, error_message=user_message[:255])

    return True  # error handled, don't propagate


async def on_startup(bot: Bot, settings: Settings) -> None:
    """Set webhook on startup."""
    url = settings.railway_public_url
    if url:
        await bot.set_webhook(
            url=f"{url}/webhook",
            secret_token=settings.telegram_webhook_secret.get_secret_value(),
            allowed_updates=[
                "message",
                "callback_query",
                "pre_checkout_query",
                "my_chat_member",
            ],
        )
        log.info("webhook_set", url=url)
    else:
        log.warning("no_railway_url", msg="RAILWAY_PUBLIC_URL not set, webhook not configured")


async def on_shutdown(
    bot: Bot,
    db: SupabaseClient,
    http_client: httpx.AsyncClient,
    redis: RedisClient,
    timeout: int = 120,
) -> None:
    """Clean up on shutdown with graceful drain (ARCHITECTURE.md §5.7).

    Sets SHUTDOWN_EVENT, then waits for all PUBLISH_SEMAPHORE permits to be
    released (meaning no in-flight publish tasks), up to ``timeout`` seconds.
    """
    SHUTDOWN_EVENT.set()
    log.info("shutdown_started", drain_timeout=timeout)

    # Wait for all 10 semaphore permits to become available (no in-flight tasks).
    # Single timeout wraps entire loop — total drain time is capped at `timeout` seconds.
    acquired = 0
    try:
        async with asyncio.timeout(timeout):
            for _ in range(10):
                await PUBLISH_SEMAPHORE.acquire()
                acquired += 1
    except TimeoutError:
        log.warning("shutdown_drain_timeout", acquired=acquired, total=10)
    finally:
        for _ in range(acquired):
            PUBLISH_SEMAPHORE.release()

    # NOTE: do NOT call bot.delete_webhook() here.
    # During Railway zero-downtime deploys, the old container's shutdown
    # races with the new container's startup — delete_webhook() would
    # clear the webhook that the new container just set. The new container's
    # set_webhook() in on_startup() is sufficient to overwrite.
    await bot.session.close()
    await http_client.aclose()
    await db.close()
    # Redis (Upstash HTTP) is stateless — no close needed, but param kept for consistency
    _ = redis
    log.info("shutdown_complete")


def create_app() -> web.Application:
    """Create aiohttp application with webhook handler.

    Entry point for Railway deployment.
    """
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    settings = get_settings()

    # Configure structlog for JSON output (Railway deployment)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Initialize Sentry
    _init_sentry(settings.sentry_dsn)

    # Create shared clients (ARCHITECTURE.md §2.2)
    db = SupabaseClient(
        url=settings.supabase_url,
        key=settings.supabase_key.get_secret_value(),
    )
    redis = RedisClient(
        url=settings.upstash_redis_url,
        token=settings.upstash_redis_token.get_secret_value(),
    )
    http_client = create_http_client()
    bot = create_bot(settings)
    dp = create_dispatcher(db, redis, http_client, settings)

    # TODO: re-add routers after frontend rewrite
    # from routers import setup_routers
    # dp.include_router(setup_routers())

    # Register lifecycle hooks (async closures, not sync lambdas)
    async def _startup() -> None:
        await on_startup(bot, settings)
        # Store bot username for Pinterest OAuth deep links (api/auth.py)
        bot_info = await bot.get_me()
        app["bot_username"] = bot_info.username or ""

    async def _shutdown() -> None:
        await on_shutdown(bot, db, http_client, redis, timeout=settings.railway_graceful_shutdown_timeout)

    dp.startup.register(_startup)
    dp.shutdown.register(_shutdown)

    # Setup aiohttp webhook
    app = web.Application()
    webhook_handler = SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.telegram_webhook_secret.get_secret_value(),
    )
    webhook_handler.register(app, path="/webhook")
    setup_application(app, dp, bot=bot)

    # AI services (Phase 6)
    prompt_engine = PromptEngine(db, redis)
    rate_limiter = RateLimiter(redis)
    ai_orchestrator = AIOrchestrator(
        http_client=http_client,
        api_key=settings.openrouter_api_key.get_secret_value(),
        prompt_engine=prompt_engine,
        rate_limiter=rate_limiter,
        site_url=settings.railway_public_url,
    )
    image_storage = ImageStorage(
        supabase_url=settings.supabase_url,
        supabase_key=settings.supabase_key.get_secret_value(),
        http_client=http_client,
    )

    # External service clients (Phase 10)
    from services.external.dataforseo import DataForSEOClient
    from services.external.firecrawl import FirecrawlClient
    from services.external.pagespeed import PageSpeedClient
    from services.external.serper import SerperClient

    firecrawl_client = FirecrawlClient(
        api_key=settings.firecrawl_api_key.get_secret_value(),
        http_client=http_client,
    )
    serper_client = SerperClient(
        api_key=settings.serper_api_key.get_secret_value(),
        http_client=http_client,
        redis=redis,
    )
    pagespeed_client = PageSpeedClient(http_client=http_client)
    dataforseo_client = DataForSEOClient(
        login=settings.dataforseo_login,
        password=settings.dataforseo_password.get_secret_value(),
        http_client=http_client,
    )

    # Store shared clients on app for API handlers (ARCHITECTURE.md §2.3)
    app["db"] = db
    app["redis"] = redis
    app["http_client"] = http_client
    app["ai_orchestrator"] = ai_orchestrator
    app["image_storage"] = image_storage
    app["bot"] = bot
    app["settings"] = settings
    app["firecrawl_client"] = firecrawl_client
    app["serper_client"] = serper_client
    app["pagespeed_client"] = pagespeed_client
    app["dataforseo_client"] = dataforseo_client

    # Payment services (Phase 8)
    from services.payments.stars import StarsPaymentService
    from services.payments.yookassa import YooKassaPaymentService

    stars_service = StarsPaymentService(db=db, admin_ids=settings.admin_ids)
    yookassa_service = YooKassaPaymentService(
        db=db,
        http_client=http_client,
        shop_id=settings.yookassa_shop_id,
        secret_key=settings.yookassa_secret_key.get_secret_value(),
        return_url=settings.yookassa_return_url,
        admin_ids=settings.admin_ids,
    )

    # Inject services into dp.workflow_data for Aiogram routers (Phase 8+)
    dp.workflow_data["ai_orchestrator"] = ai_orchestrator
    dp.workflow_data["prompt_engine"] = prompt_engine
    dp.workflow_data["rate_limiter"] = rate_limiter
    dp.workflow_data["image_storage"] = image_storage
    dp.workflow_data["stars_service"] = stars_service
    dp.workflow_data["yookassa_service"] = yookassa_service
    dp.workflow_data["firecrawl_client"] = firecrawl_client
    dp.workflow_data["serper_client"] = serper_client
    dp.workflow_data["pagespeed_client"] = pagespeed_client
    dp.workflow_data["dataforseo_client"] = dataforseo_client

    # Scheduler service (Phase 9)
    from services.scheduler import SchedulerService

    scheduler_service = SchedulerService(
        db=db,
        qstash_token=settings.qstash_token.get_secret_value(),
        base_url=settings.railway_public_url,
    )
    dp.workflow_data["scheduler_service"] = scheduler_service

    # Store payment services on app for webhook handlers
    app["yookassa_service"] = yookassa_service
    app["scheduler_service"] = scheduler_service

    # Pinterest OAuth callback (needed for ConnectPinterestFSM)
    from api.auth import pinterest_callback

    app.router.add_get("/api/auth/pinterest/callback", pinterest_callback)

    # YooKassa webhook + renewal (Phase 8 + Phase 10)
    from api.renew import renew_handler
    from api.yookassa import yookassa_webhook

    app.router.add_post("/api/yookassa/webhook", yookassa_webhook)
    app.router.add_post("/api/yookassa/renew", renew_handler)

    # API routes (Phase 9: QStash webhooks, health)
    from api.cleanup import cleanup_handler
    from api.health import health_handler
    from api.notify import notify_handler
    from api.publish import publish_handler

    app.router.add_post("/api/publish", publish_handler)
    app.router.add_post("/api/cleanup", cleanup_handler)
    app.router.add_post("/api/notify", notify_handler)
    app.router.add_get("/api/health", health_handler)

    return app
