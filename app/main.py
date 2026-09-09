"""FastAPI application entrypoint and application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.routes_health import router as health_router
from app.config import Settings, get_settings
from app.logging_config import configure_logging, logger


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a configured FastAPI app, suitable for production and tests."""

    app_settings = settings or get_settings()
    configure_logging(app_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = app_settings
        logger.info("Starting {} v{}", app_settings.app_name, __version__)
        try:
            yield
        finally:
            logger.info("Stopping {}", app_settings.app_name)

    app = FastAPI(
        title=app_settings.app_name,
        version=__version__,
        debug=app_settings.debug,
        lifespan=lifespan,
    )
    app.include_router(health_router)
    return app


app = create_app()
