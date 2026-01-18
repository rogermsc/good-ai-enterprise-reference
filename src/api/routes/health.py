"""
Health check endpoints.

Provides liveness and readiness probes for container orchestration.
"""

import logging

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.core.config import get_settings
from src.db.connection import get_pool

logger = logging.getLogger(__name__)
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
async def readiness_check() -> ReadinessResponse | Response:
    """
    Readiness check endpoint.

    Verifies service is ready to accept traffic by checking:
    - Database connectivity (executes a simple query)
    - LLM provider availability
    """
    settings = get_settings()

    # Check database connectivity
    database_status = "disconnected"
    try:
        pool = await get_pool()
        async with pool.connection() as conn:
            await conn.fetchval("SELECT 1")
        database_status = "connected"
    except Exception as e:
        logger.warning("Database health check failed: %s", str(e))
        database_status = "disconnected"

    llm_status = "mock" if settings.is_mock_mode else "connected"

    # Return 503 if database is not connected
    if database_status != "connected":
        return Response(
            status_code=503,
            content='{"status": "not_ready", "database": "disconnected"}',
            media_type="application/json",
        )

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
