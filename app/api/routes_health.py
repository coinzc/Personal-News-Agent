"""Service health and readiness endpoints."""

import asyncio

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import __version__
from app.config import Settings
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Check service liveness")
async def health(request: Request) -> HealthResponse:
    """Return process-level health without requiring external dependencies."""

    settings: Settings = request.app.state.settings
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        timezone=settings.timezone,
    )


async def _check_database(container: object) -> str:
    try:
        session_factory = container.session_factory  # type: ignore[attr-defined]
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "failed"


async def _check_redis(container: object) -> str:
    try:
        await container.redis.ping()  # type: ignore[attr-defined]
        return "ok"
    except Exception:
        return "failed"


@router.get("/ready", response_model=ReadinessResponse, summary="Check dependency readiness")
async def readiness(request: Request) -> ReadinessResponse | JSONResponse:
    """Return readiness only when PostgreSQL and Redis respond successfully."""

    settings: Settings = request.app.state.settings
    container = getattr(request.app.state, "container", None)
    checks = {"database": "failed", "redis": "failed"}
    if container is not None:
        database, redis = await asyncio.gather(_check_database(container), _check_redis(container))
        checks = {"database": database, "redis": redis}
    status = "ok" if all(value == "ok" for value in checks.values()) else "not_ready"
    response = ReadinessResponse(
        status=status,
        service=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        timezone=settings.timezone,
        checks=checks,
    )
    if status != "ok":
        return JSONResponse(status_code=503, content=response.model_dump())
    return response
