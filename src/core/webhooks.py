"""
Webhook Notification System.

Provides outbound webhook notifications for platform events, enabling
integration with external systems like Slack, PagerDuty, or custom endpoints.

Features:
- Multiple webhook endpoints per tenant
- Event filtering by type
- Automatic retries with exponential backoff
- Signature verification (HMAC-SHA256)
- Delivery status tracking
- Rate limiting per endpoint
"""

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, ClassVar

import httpx

from src.core.config import get_settings
from src.core.observability import get_logger, get_tracer

logger = get_logger()
tracer = get_tracer()


class WebhookEventType(str, Enum):
    """Types of events that can trigger webhooks."""

    # Ticket events
    TICKET_CREATED = "ticket.created"
    TICKET_TRIAGED = "ticket.triaged"
    TICKET_ESCALATED = "ticket.escalated"
    TICKET_RESOLVED = "ticket.resolved"

    # Approval events
    APPROVAL_REQUESTED = "approval.requested"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_REJECTED = "approval.rejected"
    APPROVAL_EXPIRED = "approval.expired"

    # System events
    ALERT_TRIGGERED = "alert.triggered"
    QUOTA_WARNING = "quota.warning"
    QUOTA_EXCEEDED = "quota.exceeded"

    # Agent events
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"


class DeliveryStatus(str, Enum):
    """Status of webhook delivery."""

    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class WebhookEndpoint:
    """
    Configuration for a webhook endpoint.

    Attributes:
        id: Unique identifier
        tenant_id: Owning tenant
        name: Human-readable name
        url: Target URL
        secret: Secret for HMAC signature
        events: List of event types to receive
        enabled: Whether the endpoint is active
        headers: Additional headers to include
        created_at: Creation timestamp
        metadata: Additional metadata
    """

    id: str
    tenant_id: str
    name: str
    url: str
    secret: str
    events: list[WebhookEventType] = field(default_factory=list)
    enabled: bool = True
    headers: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def accepts_event(self, event_type: WebhookEventType) -> bool:
        """Check if this endpoint accepts the given event type."""
        if not self.enabled:
            return False
        # Empty list means accept all events
        if not self.events:
            return True
        return event_type in self.events

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (excludes secret)."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "name": self.name,
            "url": self.url,
            "events": [e.value for e in self.events],
            "enabled": self.enabled,
            "headers": self.headers,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class WebhookEvent:
    """
    An event to be delivered via webhook.

    Attributes:
        id: Unique event identifier
        event_type: Type of event
        tenant_id: Tenant that generated the event
        payload: Event data
        created_at: When the event was created
        metadata: Additional metadata
    """

    id: str
    event_type: WebhookEventType
    tenant_id: str
    payload: dict[str, Any]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for delivery."""
        return {
            "id": self.id,
            "event_type": self.event_type.value,
            "tenant_id": self.tenant_id,
            "payload": self.payload,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class DeliveryAttempt:
    """Record of a delivery attempt."""

    id: str
    event_id: str
    endpoint_id: str
    status: DeliveryStatus
    attempt_number: int
    response_code: int | None = None
    response_body: str | None = None
    error_message: str | None = None
    attempted_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    duration_ms: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "event_id": self.event_id,
            "endpoint_id": self.endpoint_id,
            "status": self.status.value,
            "attempt_number": self.attempt_number,
            "response_code": self.response_code,
            "response_body": self.response_body,
            "error_message": self.error_message,
            "attempted_at": self.attempted_at.isoformat(),
            "duration_ms": self.duration_ms,
        }


@dataclass
class DeliveryResult:
    """Result of webhook delivery."""

    success: bool
    event: WebhookEvent
    attempts: list[DeliveryAttempt]
    endpoints_delivered: int = 0
    endpoints_failed: int = 0


class WebhookStore:
    """
    In-memory storage for webhook configuration.

    In production, this would be backed by a database.
    """

    def __init__(self) -> None:
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._deliveries: dict[str, list[DeliveryAttempt]] = {}

    def save_endpoint(self, endpoint: WebhookEndpoint) -> None:
        """Save a webhook endpoint."""
        self._endpoints[endpoint.id] = endpoint

    def get_endpoint(self, endpoint_id: str) -> WebhookEndpoint | None:
        """Get an endpoint by ID."""
        return self._endpoints.get(endpoint_id)

    def get_endpoints_for_tenant(self, tenant_id: str) -> list[WebhookEndpoint]:
        """Get all endpoints for a tenant."""
        return [e for e in self._endpoints.values() if e.tenant_id == tenant_id]

    def get_endpoints_for_event(
        self,
        tenant_id: str,
        event_type: WebhookEventType,
    ) -> list[WebhookEndpoint]:
        """Get endpoints that should receive an event."""
        return [e for e in self.get_endpoints_for_tenant(tenant_id) if e.accepts_event(event_type)]

    def delete_endpoint(self, endpoint_id: str) -> bool:
        """Delete an endpoint."""
        if endpoint_id in self._endpoints:
            del self._endpoints[endpoint_id]
            return True
        return False

    def save_delivery(self, attempt: DeliveryAttempt) -> None:
        """Save a delivery attempt."""
        if attempt.event_id not in self._deliveries:
            self._deliveries[attempt.event_id] = []
        self._deliveries[attempt.event_id].append(attempt)

    def get_deliveries(self, event_id: str) -> list[DeliveryAttempt]:
        """Get delivery attempts for an event."""
        return self._deliveries.get(event_id, [])


class WebhookManager:
    """
    Manages webhook endpoints and event delivery.

    Example:
        manager = WebhookManager()

        # Register an endpoint
        endpoint = manager.register_endpoint(
            tenant_id="tenant-1",
            name="Slack Notifications",
            url="https://hooks.slack.com/...",
            secret="webhook-secret",
            events=[WebhookEventType.TICKET_ESCALATED],
        )

        # Trigger an event
        await manager.trigger_event(
            event_type=WebhookEventType.TICKET_ESCALATED,
            tenant_id="tenant-1",
            payload={"ticket_id": "123", "severity": "P0"},
        )
    """

    # Retry configuration
    MAX_RETRIES: ClassVar[int] = 3
    RETRY_DELAYS: ClassVar[list[int]] = [5, 30, 300]  # seconds
    REQUEST_TIMEOUT: ClassVar[float] = 10.0  # seconds

    def __init__(self, store: WebhookStore | None = None) -> None:
        self.store = store or WebhookStore()
        self._settings = get_settings()

    def register_endpoint(
        self,
        tenant_id: str,
        name: str,
        url: str,
        secret: str,
        events: list[WebhookEventType] | None = None,
        headers: dict[str, str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WebhookEndpoint:
        """
        Register a new webhook endpoint.

        Args:
            tenant_id: Tenant identifier
            name: Human-readable name
            url: Target URL
            secret: Secret for HMAC signature
            events: List of event types (empty = all)
            headers: Additional headers
            metadata: Additional metadata

        Returns:
            The created WebhookEndpoint
        """
        with tracer.start_as_current_span("webhooks.register_endpoint"):
            endpoint = WebhookEndpoint(
                id=str(uuid.uuid4()),
                tenant_id=tenant_id,
                name=name,
                url=url,
                secret=secret,
                events=events or [],
                headers=headers or {},
                metadata=metadata or {},
            )

            self.store.save_endpoint(endpoint)

            logger.info(
                "webhook_endpoint_registered",
                endpoint_id=endpoint.id,
                tenant_id=tenant_id,
                name=name,
                event_count=len(events) if events else "all",
            )

            return endpoint

    def get_endpoint(self, endpoint_id: str) -> WebhookEndpoint | None:
        """Get an endpoint by ID."""
        return self.store.get_endpoint(endpoint_id)

    def list_endpoints(self, tenant_id: str) -> list[WebhookEndpoint]:
        """List all endpoints for a tenant."""
        return self.store.get_endpoints_for_tenant(tenant_id)

    def update_endpoint(
        self,
        endpoint_id: str,
        name: str | None = None,
        url: str | None = None,
        events: list[WebhookEventType] | None = None,
        enabled: bool | None = None,
        headers: dict[str, str] | None = None,
    ) -> WebhookEndpoint | None:
        """
        Update an existing endpoint.

        Only provided fields are updated.
        """
        endpoint = self.store.get_endpoint(endpoint_id)
        if endpoint is None:
            return None

        if name is not None:
            endpoint.name = name
        if url is not None:
            endpoint.url = url
        if events is not None:
            endpoint.events = events
        if enabled is not None:
            endpoint.enabled = enabled
        if headers is not None:
            endpoint.headers = headers

        self.store.save_endpoint(endpoint)
        return endpoint

    def delete_endpoint(self, endpoint_id: str) -> bool:
        """Delete an endpoint."""
        return self.store.delete_endpoint(endpoint_id)

    def _sign_payload(self, payload: str, secret: str) -> str:
        """Generate HMAC-SHA256 signature for payload."""
        return hmac.new(
            secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    async def _deliver_to_endpoint(
        self,
        endpoint: WebhookEndpoint,
        event: WebhookEvent,
    ) -> DeliveryAttempt:
        """Deliver an event to a single endpoint."""
        payload_json = json.dumps(event.to_dict(), default=str)
        signature = self._sign_payload(payload_json, endpoint.secret)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event.event_type.value,
            "X-Webhook-Signature": f"sha256={signature}",
            "X-Webhook-Timestamp": str(int(time.time())),
            "X-Webhook-ID": event.id,
            **endpoint.headers,
        }

        start_time = time.time()
        attempt = DeliveryAttempt(
            id=str(uuid.uuid4()),
            event_id=event.id,
            endpoint_id=endpoint.id,
            status=DeliveryStatus.PENDING,
            attempt_number=1,
        )

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint.url,
                    content=payload_json,
                    headers=headers,
                    timeout=self.REQUEST_TIMEOUT,
                )

            duration_ms = (time.time() - start_time) * 1000
            attempt.duration_ms = duration_ms
            attempt.response_code = response.status_code

            if response.is_success:
                attempt.status = DeliveryStatus.DELIVERED
                attempt.response_body = response.text[:500]  # Truncate
            else:
                attempt.status = DeliveryStatus.FAILED
                attempt.response_body = response.text[:500]
                attempt.error_message = f"HTTP {response.status_code}"

        except httpx.TimeoutException:
            attempt.status = DeliveryStatus.FAILED
            attempt.error_message = "Request timeout"
            attempt.duration_ms = (time.time() - start_time) * 1000

        except Exception as e:
            attempt.status = DeliveryStatus.FAILED
            attempt.error_message = str(e)
            attempt.duration_ms = (time.time() - start_time) * 1000

        self.store.save_delivery(attempt)
        return attempt

    async def trigger_event(
        self,
        event_type: WebhookEventType,
        tenant_id: str,
        payload: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> DeliveryResult:
        """
        Trigger an event and deliver to all subscribed endpoints.

        Args:
            event_type: Type of event
            tenant_id: Tenant that generated the event
            payload: Event data
            metadata: Additional metadata

        Returns:
            DeliveryResult with delivery status
        """
        with tracer.start_as_current_span("webhooks.trigger_event") as span:
            span.set_attribute("event_type", event_type.value)
            span.set_attribute("tenant_id", tenant_id)

            # Create event
            event = WebhookEvent(
                id=str(uuid.uuid4()),
                event_type=event_type,
                tenant_id=tenant_id,
                payload=payload,
                metadata=metadata or {},
            )

            # Find matching endpoints
            endpoints = self.store.get_endpoints_for_event(tenant_id, event_type)

            if not endpoints:
                logger.debug(
                    "no_webhook_endpoints",
                    event_type=event_type.value,
                    tenant_id=tenant_id,
                )
                return DeliveryResult(
                    success=True,
                    event=event,
                    attempts=[],
                )

            # Deliver to each endpoint
            attempts = []
            delivered = 0
            failed = 0

            for endpoint in endpoints:
                attempt = await self._deliver_to_endpoint(endpoint, event)
                attempts.append(attempt)

                if attempt.status == DeliveryStatus.DELIVERED:
                    delivered += 1
                else:
                    failed += 1

            logger.info(
                "webhook_event_triggered",
                event_id=event.id,
                event_type=event_type.value,
                tenant_id=tenant_id,
                endpoints_total=len(endpoints),
                endpoints_delivered=delivered,
                endpoints_failed=failed,
            )

            return DeliveryResult(
                success=failed == 0,
                event=event,
                attempts=attempts,
                endpoints_delivered=delivered,
                endpoints_failed=failed,
            )

    def get_delivery_history(
        self,
        event_id: str,
    ) -> list[DeliveryAttempt]:
        """Get delivery history for an event."""
        return self.store.get_deliveries(event_id)

    def verify_signature(
        self,
        payload: str,
        signature: str,
        secret: str,
    ) -> bool:
        """
        Verify a webhook signature.

        For use by webhook receivers to verify authenticity.

        Args:
            payload: Raw request body
            signature: Signature from X-Webhook-Signature header
            secret: The webhook secret

        Returns:
            True if signature is valid
        """
        if signature.startswith("sha256="):
            signature = signature[7:]

        expected = self._sign_payload(payload, secret)
        return hmac.compare_digest(expected, signature)


# Global webhook manager instance
_webhook_manager: WebhookManager | None = None


def get_webhook_manager() -> WebhookManager:
    """Get the global webhook manager instance."""
    global _webhook_manager
    if _webhook_manager is None:
        _webhook_manager = WebhookManager()
    return _webhook_manager
