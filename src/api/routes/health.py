"""
Health check endpoints.

Provides liveness and readiness probes for container orchestration,
as well as LLM provider health status.
"""

from datetime import datetime

from fastapi import APIRouter, Response
from pydantic import BaseModel

from src.core.config import get_settings
from src.core.llm_resilience import ProviderStatus, get_provider_manager

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


class ProviderHealthStatus(BaseModel):
    """Individual LLM provider health status."""

    provider: str
    status: str
    circuit_state: str
    failure_count: int
    last_success: datetime | None = None
    last_failure: datetime | None = None
    avg_latency_ms: float | None = None


class ProvidersHealthResponse(BaseModel):
    """Response for provider health check."""

    status: str
    healthy_providers: int
    total_providers: int
    providers: list[ProviderHealthStatus]


@router.get(
    "/health/providers",
    response_model=ProvidersHealthResponse,
    summary="LLM Provider health",
    description="Health status of LLM providers including circuit breaker states",
)
async def provider_health() -> ProvidersHealthResponse:
    """
    Get health status of all LLM providers.

    Returns the circuit breaker state, failure counts, and latency
    metrics for each configured provider.
    """
    manager = get_provider_manager()
    health_list = manager.get_health()

    providers = [
        ProviderHealthStatus(
            provider=h.provider,
            status=h.status.value,
            circuit_state=h.circuit_state.value,
            failure_count=h.failure_count,
            last_success=h.last_success,
            last_failure=h.last_failure,
            avg_latency_ms=h.avg_latency_ms,
        )
        for h in health_list
    ]

    healthy_count = sum(1 for h in health_list if h.status == ProviderStatus.HEALTHY)
    total_count = len(health_list)

    overall_status = "healthy" if healthy_count > 0 else "degraded"

    return ProvidersHealthResponse(
        status=overall_status,
        healthy_providers=healthy_count,
        total_providers=total_count,
        providers=providers,
    )
