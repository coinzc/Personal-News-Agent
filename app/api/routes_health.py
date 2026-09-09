"""Service health and liveness endpoints."""

from fastapi import APIRouter, Request

from app import __version__
from app.config import Settings
from app.schemas.health import HealthResponse

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
