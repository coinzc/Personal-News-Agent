"""Health endpoint response schemas."""

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Basic liveness information for load balancers and operators."""

    model_config = ConfigDict(extra="forbid")
    status: str
    service: str
    version: str
    environment: str
    timezone: str
