"""Tests for Webhook notification system."""

from datetime import UTC, datetime

import pytest

from src.core.security import SecurityContext
from src.core.webhooks import (
    DeliveryStatus,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventType,
    WebhookManager,
    WebhookStore,
    get_webhook_manager,
)


class TestWebhookEndpoint:
    """Tests for WebhookEndpoint model."""

    def test_create_endpoint(self) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="Slack Notifications",
            url="https://hooks.slack.com/services/...",
            secret="webhook-secret-key",
        )

        assert endpoint.id == "endpoint-1"
        assert endpoint.enabled is True
        assert endpoint.events == []

    def test_accepts_event_all(self) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="All Events",
            url="https://example.com/webhook",
            secret="secret",
            events=[],  # Empty = all events
        )

        assert endpoint.accepts_event(WebhookEventType.TICKET_CREATED) is True
        assert endpoint.accepts_event(WebhookEventType.APPROVAL_APPROVED) is True

    def test_accepts_event_filtered(self) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="Ticket Events Only",
            url="https://example.com/webhook",
            secret="secret",
            events=[WebhookEventType.TICKET_CREATED, WebhookEventType.TICKET_TRIAGED],
        )

        assert endpoint.accepts_event(WebhookEventType.TICKET_CREATED) is True
        assert endpoint.accepts_event(WebhookEventType.TICKET_TRIAGED) is True
        assert endpoint.accepts_event(WebhookEventType.APPROVAL_APPROVED) is False

    def test_disabled_endpoint(self) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="Disabled",
            url="https://example.com/webhook",
            secret="secret",
            enabled=False,
        )

        assert endpoint.accepts_event(WebhookEventType.TICKET_CREATED) is False

    def test_to_dict_excludes_secret(self) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/webhook",
            secret="super-secret-key",
        )

        data = endpoint.to_dict()

        assert "secret" not in data
        assert data["id"] == "endpoint-1"
        assert data["url"] == "https://example.com/webhook"


class TestWebhookEvent:
    """Tests for WebhookEvent model."""

    def test_create_event(self) -> None:
        event = WebhookEvent(
            id="event-1",
            event_type=WebhookEventType.TICKET_ESCALATED,
            tenant_id="tenant-1",
            payload={"ticket_id": "123", "severity": "P0"},
        )

        assert event.id == "event-1"
        assert event.event_type == WebhookEventType.TICKET_ESCALATED
        assert event.payload["ticket_id"] == "123"

    def test_to_dict(self) -> None:
        event = WebhookEvent(
            id="event-1",
            event_type=WebhookEventType.APPROVAL_APPROVED,
            tenant_id="tenant-1",
            payload={"approval_id": "abc"},
            metadata={"source": "api"},
        )

        data = event.to_dict()

        assert data["id"] == "event-1"
        assert data["event_type"] == "approval.approved"
        assert data["payload"]["approval_id"] == "abc"


class TestWebhookStore:
    """Tests for WebhookStore."""

    @pytest.fixture
    def store(self) -> WebhookStore:
        return WebhookStore()

    def test_save_and_get_endpoint(self, store: WebhookStore) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/webhook",
            secret="secret",
        )

        store.save_endpoint(endpoint)
        retrieved = store.get_endpoint("endpoint-1")

        assert retrieved is not None
        assert retrieved.id == "endpoint-1"

    def test_get_nonexistent(self, store: WebhookStore) -> None:
        assert store.get_endpoint("nonexistent") is None

    def test_get_endpoints_for_tenant(self, store: WebhookStore) -> None:
        for i in range(3):
            tenant = "tenant-1" if i < 2 else "tenant-2"
            endpoint = WebhookEndpoint(
                id=f"endpoint-{i}",
                tenant_id=tenant,
                name=f"Endpoint {i}",
                url="https://example.com/webhook",
                secret="secret",
            )
            store.save_endpoint(endpoint)

        tenant_1_endpoints = store.get_endpoints_for_tenant("tenant-1")
        assert len(tenant_1_endpoints) == 2

        tenant_2_endpoints = store.get_endpoints_for_tenant("tenant-2")
        assert len(tenant_2_endpoints) == 1

    def test_get_endpoints_for_event(self, store: WebhookStore) -> None:
        # Endpoint that accepts all events
        store.save_endpoint(
            WebhookEndpoint(
                id="all-events",
                tenant_id="tenant-1",
                name="All",
                url="https://example.com/all",
                secret="secret",
                events=[],
            )
        )

        # Endpoint that only accepts ticket events
        store.save_endpoint(
            WebhookEndpoint(
                id="ticket-only",
                tenant_id="tenant-1",
                name="Tickets",
                url="https://example.com/tickets",
                secret="secret",
                events=[WebhookEventType.TICKET_CREATED],
            )
        )

        # Query for ticket event
        ticket_endpoints = store.get_endpoints_for_event(
            "tenant-1",
            WebhookEventType.TICKET_CREATED,
        )
        assert len(ticket_endpoints) == 2

        # Query for approval event
        approval_endpoints = store.get_endpoints_for_event(
            "tenant-1",
            WebhookEventType.APPROVAL_APPROVED,
        )
        assert len(approval_endpoints) == 1
        assert approval_endpoints[0].id == "all-events"

    def test_delete_endpoint(self, store: WebhookStore) -> None:
        endpoint = WebhookEndpoint(
            id="endpoint-1",
            tenant_id="tenant-1",
            name="Test",
            url="https://example.com/webhook",
            secret="secret",
        )

        store.save_endpoint(endpoint)
        assert store.delete_endpoint("endpoint-1") is True
        assert store.get_endpoint("endpoint-1") is None
        assert store.delete_endpoint("endpoint-1") is False


class TestWebhookManager:
    """Tests for WebhookManager."""

    @pytest.fixture
    def manager(self) -> WebhookManager:
        return WebhookManager()

    def test_register_endpoint(self, manager: WebhookManager) -> None:
        endpoint = manager.register_endpoint(
            tenant_id="tenant-1",
            name="Slack",
            url="https://hooks.slack.com/...",
            secret="secret-key-12345678",
            events=[WebhookEventType.TICKET_ESCALATED],
        )

        assert endpoint.id is not None
        assert endpoint.name == "Slack"
        assert len(endpoint.events) == 1

    def test_list_endpoints(self, manager: WebhookManager) -> None:
        for i in range(3):
            manager.register_endpoint(
                tenant_id="tenant-1",
                name=f"Endpoint {i}",
                url=f"https://example.com/{i}",
                secret="secret-key-12345678",
            )

        endpoints = manager.list_endpoints("tenant-1")
        assert len(endpoints) == 3

    def test_update_endpoint(self, manager: WebhookManager) -> None:
        endpoint = manager.register_endpoint(
            tenant_id="tenant-1",
            name="Original",
            url="https://example.com/webhook",
            secret="secret-key-12345678",
        )

        updated = manager.update_endpoint(
            endpoint_id=endpoint.id,
            name="Updated",
            enabled=False,
        )

        assert updated is not None
        assert updated.name == "Updated"
        assert updated.enabled is False

    def test_delete_endpoint(self, manager: WebhookManager) -> None:
        endpoint = manager.register_endpoint(
            tenant_id="tenant-1",
            name="To Delete",
            url="https://example.com/webhook",
            secret="secret-key-12345678",
        )

        assert manager.delete_endpoint(endpoint.id) is True
        assert manager.get_endpoint(endpoint.id) is None

    def test_sign_payload(self, manager: WebhookManager) -> None:
        payload = '{"test": "data"}'
        secret = "my-secret-key"

        signature = manager._sign_payload(payload, secret)

        assert signature is not None
        assert len(signature) == 64  # SHA256 hex digest

    def test_verify_signature(self, manager: WebhookManager) -> None:
        payload = '{"event": "test"}'
        secret = "secret-key"

        signature = manager._sign_payload(payload, secret)

        # Verify with prefix
        assert manager.verify_signature(payload, f"sha256={signature}", secret) is True

        # Verify without prefix
        assert manager.verify_signature(payload, signature, secret) is True

        # Invalid signature
        assert manager.verify_signature(payload, "invalid", secret) is False

    @pytest.mark.asyncio
    async def test_trigger_event_no_endpoints(self, manager: WebhookManager) -> None:
        result = await manager.trigger_event(
            event_type=WebhookEventType.TICKET_CREATED,
            tenant_id="tenant-1",
            payload={"ticket_id": "123"},
        )

        assert result.success is True
        assert len(result.attempts) == 0

    @pytest.mark.asyncio
    async def test_trigger_event_with_endpoint(self, manager: WebhookManager) -> None:
        # Register endpoint (will fail delivery since URL doesn't exist)
        manager.register_endpoint(
            tenant_id="tenant-1",
            name="Test",
            url="https://httpbin.org/status/200",
            secret="secret-key-12345678",
            events=[WebhookEventType.TICKET_CREATED],
        )

        result = await manager.trigger_event(
            event_type=WebhookEventType.TICKET_CREATED,
            tenant_id="tenant-1",
            payload={"ticket_id": "123"},
        )

        assert result.event.event_type == WebhookEventType.TICKET_CREATED
        assert len(result.attempts) == 1


class TestWebhookEventTypes:
    """Tests for WebhookEventType enum."""

    def test_ticket_events(self) -> None:
        assert WebhookEventType.TICKET_CREATED.value == "ticket.created"
        assert WebhookEventType.TICKET_TRIAGED.value == "ticket.triaged"
        assert WebhookEventType.TICKET_ESCALATED.value == "ticket.escalated"

    def test_approval_events(self) -> None:
        assert WebhookEventType.APPROVAL_REQUESTED.value == "approval.requested"
        assert WebhookEventType.APPROVAL_APPROVED.value == "approval.approved"
        assert WebhookEventType.APPROVAL_REJECTED.value == "approval.rejected"

    def test_system_events(self) -> None:
        assert WebhookEventType.ALERT_TRIGGERED.value == "alert.triggered"
        assert WebhookEventType.QUOTA_WARNING.value == "quota.warning"


class TestGlobalWebhookManager:
    """Tests for global webhook manager."""

    def test_singleton(self) -> None:
        manager1 = get_webhook_manager()
        manager2 = get_webhook_manager()
        assert manager1 is manager2
