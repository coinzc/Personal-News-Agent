"""FastAPI application entrypoint and application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes_agent import router as agent_router
from app.api.routes_digest import router as digest_router
from app.api.routes_health import router as health_router
from app.api.routes_wechat import router as wechat_router
from app.config import Settings, get_settings
from app.logging_config import configure_logging, logger
from app.runtime import ApplicationContainer
from app.scheduler import build_scheduler


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured FastAPI app, suitable for production and tests."""

    app_settings = settings or get_settings()
    configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        container = ApplicationContainer.from_settings(app_settings)
        app.state.container = container
        scheduler = None
        if app_settings.enable_scheduler:
            scheduler = build_scheduler(
                container.generate_and_send_daily_digest,
                run_collect=container.collect_news,
                collection_interval_minutes=app_settings.news_collection_interval_minutes,
                timezone=app_settings.timezone,
            )
            scheduler.start()
            app.state.scheduler = scheduler
        logger.info("Starting {} v{}", app_settings.app_name, __version__)
        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            await container.aclose()
            logger.info("Stopping {}", app_settings.app_name)

    app = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    app.include_router(agent_router)
    app.include_router(digest_router)
    app.include_router(wechat_router)
    return app


app = create_app()
