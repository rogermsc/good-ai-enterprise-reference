"""
API routes for Webhook management.

Provides endpoints for:
- Registering webhook endpoints
- Listing and managing endpoints
- Viewing delivery history
- Testing endpoints
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from src.core.observability import get_logger
from src.core.security import SecurityContext, get_current_user
from src.core.webhooks import (
    WebhookEndpoint,
    WebhookEventType,
    WebhookManager,
    get_webhook_manager,
)

logger = get_logger()

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# Request/Response Models


class RegisterEndpointRequest(BaseModel):
    """Request to register a webhook endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=100, description="Endpoint name")
    url: HttpUrl = Field(..., description="Target URL")
    secret: str = Field(..., min_length=16, description="Secret for signature")
    events: list[WebhookEventType] = Field(
        default_factory=list,
        description="Event types to receive (empty = all)",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional headers",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata",
    )


class UpdateEndpointRequest(BaseModel):
    """Request to update a webhook endpoint."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=100)
    url: HttpUrl | None = None
    events: list[WebhookEventType] | None = None
    enabled: bool | None = None
    headers: dict[str, str] | None = None


class EndpointResponse(BaseModel):
    """Response containing endpoint details."""

    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    name: str
    url: str
    events: list[str]
    enabled: bool
    headers: dict[str, str]
    created_at: str
    metadata: dict[str, Any]


class EndpointListResponse(BaseModel):
    """Response containing list of endpoints."""

    model_config = ConfigDict(extra="forbid")

    endpoints: list[EndpointResponse]
    total: int


class DeliveryAttemptResponse(BaseModel):
    """Response containing delivery attempt details."""

    model_config = ConfigDict(extra="forbid")

    id: str
    event_id: str
    endpoint_id: str
    status: str
    attempt_number: int
    response_code: int | None
    error_message: str | None
    attempted_at: str
    duration_ms: float | None


class DeliveryHistoryResponse(BaseModel):
    """Response containing delivery history."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    attempts: list[DeliveryAttemptResponse]


class TestWebhookRequest(BaseModel):
    """Request to test a webhook endpoint."""

    model_config = ConfigDict(extra="forbid")

    event_type: WebhookEventType = Field(
        default=WebhookEventType.TICKET_CREATED,
        description="Event type to simulate",
    )
    payload: dict[str, Any] = Field(
        default_factory=lambda: {"test": True, "message": "Test webhook delivery"},
        description="Test payload",
    )


class TestWebhookResponse(BaseModel):
    """Response from webhook test."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    event_id: str
    status: str
    response_code: int | None
    error_message: str | None
    duration_ms: float | None


class EventTypesResponse(BaseModel):
    """Response listing available event types."""

    model_config = ConfigDict(extra="forbid")

    event_types: list[dict[str, str]]


def _to_response(endpoint: WebhookEndpoint) -> EndpointResponse:
    """Convert WebhookEndpoint to response model."""
    data = endpoint.to_dict()
    return EndpointResponse(**data)


# Endpoints


@router.get("/event-types", response_model=EventTypesResponse)
async def list_event_types() -> EventTypesResponse:
    """List all available webhook event types."""
    event_types = [{"value": e.value, "name": e.name} for e in WebhookEventType]
    return EventTypesResponse(event_types=event_types)


@router.post("", response_model=EndpointResponse)
async def register_endpoint(
    request: RegisterEndpointRequest,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
) -> EndpointResponse:
    """
    Register a new webhook endpoint.

    The secret must be at least 16 characters and will be used
    to sign webhook payloads with HMAC-SHA256.
    """
    endpoint = manager.register_endpoint(
        tenant_id=user.tenant_id,
        name=request.name,
        url=str(request.url),
        secret=request.secret,
        events=request.events,
        headers=request.headers,
        metadata=request.metadata,
    )
    return _to_response(endpoint)


@router.get("", response_model=EndpointListResponse)
async def list_endpoints(
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
) -> EndpointListResponse:
    """List all webhook endpoints for the tenant."""
    endpoints = manager.list_endpoints(user.tenant_id)
    return EndpointListResponse(
        endpoints=[_to_response(e) for e in endpoints],
        total=len(endpoints),
    )


@router.get("/{endpoint_id}", response_model=EndpointResponse)
async def get_endpoint(
    endpoint_id: str,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
) -> EndpointResponse:
    """Get a specific webhook endpoint."""
    endpoint = manager.get_endpoint(endpoint_id)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    if endpoint.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    return _to_response(endpoint)


@router.patch("/{endpoint_id}", response_model=EndpointResponse)
async def update_endpoint(
    endpoint_id: str,
    request: UpdateEndpointRequest,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
) -> EndpointResponse:
    """Update a webhook endpoint."""
    endpoint = manager.get_endpoint(endpoint_id)
    if endpoint is None or endpoint.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    updated = manager.update_endpoint(
        endpoint_id=endpoint_id,
        name=request.name,
        url=str(request.url) if request.url else None,
        events=request.events,
        enabled=request.enabled,
        headers=request.headers,
    )

    if updated is None:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    return _to_response(updated)


@router.delete("/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: str,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
) -> dict[str, bool]:
    """Delete a webhook endpoint."""
    endpoint = manager.get_endpoint(endpoint_id)
    if endpoint is None or endpoint.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    manager.delete_endpoint(endpoint_id)
    return {"deleted": True}


@router.post("/{endpoint_id}/test", response_model=TestWebhookResponse)
async def test_endpoint(
    endpoint_id: str,
    request: TestWebhookRequest,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
) -> TestWebhookResponse:
    """
    Test a webhook endpoint by sending a test event.

    The test event will be delivered immediately to the endpoint.
    """
    endpoint = manager.get_endpoint(endpoint_id)
    if endpoint is None or endpoint.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    # Trigger test event
    result = await manager.trigger_event(
        event_type=request.event_type,
        tenant_id=user.tenant_id,
        payload=request.payload,
        metadata={"test": True},
    )

    # Get the attempt for this endpoint
    attempt = next(
        (a for a in result.attempts if a.endpoint_id == endpoint_id),
        None,
    )

    if attempt is None:
        raise HTTPException(
            status_code=400,
            detail="Endpoint does not accept this event type",
        )

    return TestWebhookResponse(
        success=attempt.status.value == "delivered",
        event_id=result.event.id,
        status=attempt.status.value,
        response_code=attempt.response_code,
        error_message=attempt.error_message,
        duration_ms=attempt.duration_ms,
    )


@router.get("/{endpoint_id}/history", response_model=list[DeliveryAttemptResponse])
async def get_delivery_history(
    endpoint_id: str,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[WebhookManager, Depends(get_webhook_manager)],
    event_id: Annotated[str | None, Query(description="Filter by event ID")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[DeliveryAttemptResponse]:
    """Get delivery history for a webhook endpoint."""
    endpoint = manager.get_endpoint(endpoint_id)
    if endpoint is None or endpoint.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Endpoint not found")

    # Get all deliveries and filter
    if event_id:
        attempts = manager.get_delivery_history(event_id)
        attempts = [a for a in attempts if a.endpoint_id == endpoint_id]
    else:
        # Would need to iterate all events - simplified for now
        attempts = []

    return [
        DeliveryAttemptResponse(
            id=a.id,
            event_id=a.event_id,
            endpoint_id=a.endpoint_id,
            status=a.status.value,
            attempt_number=a.attempt_number,
            response_code=a.response_code,
            error_message=a.error_message,
            attempted_at=a.attempted_at.isoformat(),
            duration_ms=a.duration_ms,
        )
        for a in attempts[:limit]
    ]
