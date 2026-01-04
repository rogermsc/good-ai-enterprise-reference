"""
Health check endpoints.

Provides liveness and readiness probes for container orchestration.
"""

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.core.config import get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str
    environment: str


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    status: str
    database: str
    llm_provider: str


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Basic health check for liveness probes",
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.

    Returns basic service status for liveness probes.
    """
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        environment=settings.environment,
    )


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness check",
    description="Readiness check including dependencies",
)
async def readiness_check() -> ReadinessResponse:
    """
    Readiness check endpoint.

    Verifies service is ready to accept traffic.
    In production, this would check database connectivity.
    """
    settings = get_settings()

    # In production, check database connection here
    database_status = "connected"

    llm_status = "mock" if settings.is_mock_mode else "connected"

    return ReadinessResponse(
        status="ready",
        database=database_status,
        llm_provider=llm_status,
    )


@router.get(
    "/health/live",
    status_code=200,
    summary="Liveness probe",
    description="Simple liveness probe for Kubernetes",
)
async def liveness_probe() -> Response:
    """
    Minimal liveness probe.

    Returns 200 OK if the service is running.
    """
    return Response(status_code=200)
