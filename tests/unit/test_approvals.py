"""Tests for Human-in-the-Loop approval system."""

from datetime import UTC, datetime, timedelta

import pytest

from src.core.approvals import (
    ApprovalManager,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalStatus,
    ApprovalStore,
    get_approval_manager,
)
from src.core.security import SecurityContext


class TestApprovalRequest:
    """Tests for ApprovalRequest model."""

    def test_create_request(self) -> None:
        requester = SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )
        request = ApprovalRequest(
            id="req-1",
            request_type="ticket_response",
            action="send_response",
            context={"ticket_id": "123"},
            requester=requester,
        )

        assert request.id == "req-1"
        assert request.status == ApprovalStatus.PENDING
        assert request.priority == ApprovalPriority.MEDIUM
        assert request.is_pending is True
        assert request.is_expired is False

    def test_expiration_based_on_priority(self) -> None:
        requester = SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )

        # Critical priority - 1 hour expiration
        critical = ApprovalRequest(
            id="req-1",
            request_type="test",
            action="test",
            context={},
            requester=requester,
            priority=ApprovalPriority.CRITICAL,
        )
        expected_expires = critical.created_at + timedelta(hours=1)
        assert abs((critical.expires_at - expected_expires).total_seconds()) < 1

        # Low priority - 72 hour expiration
        low = ApprovalRequest(
            id="req-2",
            request_type="test",
            action="test",
            context={},
            requester=requester,
            priority=ApprovalPriority.LOW,
        )
        expected_expires = low.created_at + timedelta(hours=72)
        assert abs((low.expires_at - expected_expires).total_seconds()) < 1

    def test_is_expired(self) -> None:
        requester = SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )

        # Create expired request
        past = datetime.now(UTC) - timedelta(hours=2)
        request = ApprovalRequest(
            id="req-1",
            request_type="test",
            action="test",
            context={},
            requester=requester,
            created_at=past,
            expires_at=past + timedelta(hours=1),
        )

        assert request.is_expired is True
        assert request.is_pending is False

    def test_serialization(self) -> None:
        requester = SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )
        request = ApprovalRequest(
            id="req-1",
            request_type="ticket_response",
            action="send_response",
            context={"ticket_id": "123"},
            requester=requester,
            metadata={"source": "api"},
        )

        data = request.to_dict()
        restored = ApprovalRequest.from_dict(data)

        assert restored.id == request.id
        assert restored.request_type == request.request_type
        assert restored.action == request.action
        assert restored.requester.user_id == request.requester.user_id
        assert restored.metadata == request.metadata


class TestApprovalStore:
    """Tests for ApprovalStore."""

    @pytest.fixture
    def store(self) -> ApprovalStore:
        return ApprovalStore()

    @pytest.fixture
    def requester(self) -> SecurityContext:
        return SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )

    def test_save_and_get(self, store: ApprovalStore, requester: SecurityContext) -> None:
        request = ApprovalRequest(
            id="req-1",
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        store.save(request)
        retrieved = store.get("req-1")

        assert retrieved is not None
        assert retrieved.id == "req-1"

    def test_get_nonexistent(self, store: ApprovalStore) -> None:
        assert store.get("nonexistent") is None

    def test_get_by_tenant(self, store: ApprovalStore) -> None:
        for i in range(3):
            tenant = "tenant-1" if i < 2 else "tenant-2"
            requester = SecurityContext(
                user_id=f"user-{i}",
                tenant_id=tenant,
                roles=["support_agent"],
            )
            request = ApprovalRequest(
                id=f"req-{i}",
                request_type="test",
                action="test",
                context={},
                requester=requester,
            )
            store.save(request)

        tenant_1_requests = store.get_by_tenant("tenant-1")
        assert len(tenant_1_requests) == 2

        tenant_2_requests = store.get_by_tenant("tenant-2")
        assert len(tenant_2_requests) == 1

    def test_get_pending(self, store: ApprovalStore, requester: SecurityContext) -> None:
        # Create pending and approved requests
        pending = ApprovalRequest(
            id="req-1",
            request_type="test",
            action="test",
            context={},
            requester=requester,
            status=ApprovalStatus.PENDING,
        )
        approved = ApprovalRequest(
            id="req-2",
            request_type="test",
            action="test",
            context={},
            requester=requester,
            status=ApprovalStatus.APPROVED,
        )

        store.save(pending)
        store.save(approved)

        pending_requests = store.get_pending("tenant-1")
        assert len(pending_requests) == 1
        assert pending_requests[0].id == "req-1"

    def test_delete(self, store: ApprovalStore, requester: SecurityContext) -> None:
        request = ApprovalRequest(
            id="req-1",
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        store.save(request)
        assert store.delete("req-1") is True
        assert store.get("req-1") is None
        assert store.delete("req-1") is False

    def test_clear(self, store: ApprovalStore, requester: SecurityContext) -> None:
        for i in range(5):
            request = ApprovalRequest(
                id=f"req-{i}",
                request_type="test",
                action="test",
                context={},
                requester=requester,
            )
            store.save(request)

        cleared = store.clear()
        assert cleared == 5
        assert len(store.get_by_tenant("tenant-1")) == 0

    def test_priority_ordering(self, store: ApprovalStore, requester: SecurityContext) -> None:
        # Create requests with different priorities
        for priority in [ApprovalPriority.LOW, ApprovalPriority.CRITICAL, ApprovalPriority.MEDIUM]:
            request = ApprovalRequest(
                id=f"req-{priority.value}",
                request_type="test",
                action="test",
                context={},
                requester=requester,
                priority=priority,
            )
            store.save(request)

        requests = store.get_by_tenant("tenant-1")
        assert requests[0].priority == ApprovalPriority.CRITICAL
        assert requests[1].priority == ApprovalPriority.MEDIUM
        assert requests[2].priority == ApprovalPriority.LOW


class TestApprovalManager:
    """Tests for ApprovalManager."""

    @pytest.fixture
    def manager(self) -> ApprovalManager:
        return ApprovalManager()

    @pytest.fixture
    def requester(self) -> SecurityContext:
        return SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )

    @pytest.fixture
    def approver(self) -> SecurityContext:
        return SecurityContext(
            user_id="admin-1",
            tenant_id="tenant-1",
            roles=["admin"],
        )

    def test_create_request(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
    ) -> None:
        request = manager.create_request(
            request_type="ticket_response",
            action="send_response",
            context={"ticket_id": "123"},
            requester=requester,
            priority=ApprovalPriority.HIGH,
        )

        assert request.id is not None
        assert request.request_type == "ticket_response"
        assert request.status == ApprovalStatus.PENDING

    def test_approve_request(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
        approver: SecurityContext,
    ) -> None:
        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        result = manager.approve(
            request_id=request.id,
            reviewer=approver,
            notes="Looks good",
        )

        assert result.success is True
        assert result.request.status == ApprovalStatus.APPROVED
        assert result.request.reviewed_by == "admin-1"
        assert result.request.review_notes == "Looks good"

    def test_reject_request(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
        approver: SecurityContext,
    ) -> None:
        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        result = manager.reject(
            request_id=request.id,
            reviewer=approver,
            notes="Not appropriate",
        )

        assert result.success is True
        assert result.request.status == ApprovalStatus.REJECTED
        assert result.request.review_notes == "Not appropriate"

    def test_cannot_self_approve(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
    ) -> None:
        # Make requester an admin so they would otherwise have permission
        requester_admin = SecurityContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=["admin"],
        )

        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester_admin,
        )

        result = manager.approve(
            request_id=request.id,
            reviewer=requester_admin,
        )

        assert result.success is False
        assert "Cannot approve your own request" in result.message

    def test_cannot_approve_without_role(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
    ) -> None:
        other_agent = SecurityContext(
            user_id="user-2",
            tenant_id="tenant-1",
            roles=["support_agent"],  # Not an approver role
        )

        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        result = manager.approve(
            request_id=request.id,
            reviewer=other_agent,
        )

        assert result.success is False
        assert "Must have one of these roles" in result.message

    def test_cannot_approve_different_tenant(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
    ) -> None:
        other_tenant_admin = SecurityContext(
            user_id="admin-2",
            tenant_id="tenant-2",
            roles=["admin"],
        )

        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        result = manager.approve(
            request_id=request.id,
            reviewer=other_tenant_admin,
        )

        assert result.success is False
        assert "same tenant" in result.message

    def test_cannot_approve_twice(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
        approver: SecurityContext,
    ) -> None:
        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        # First approval succeeds
        manager.approve(request_id=request.id, reviewer=approver)

        # Second approval fails
        result = manager.approve(request_id=request.id, reviewer=approver)

        assert result.success is False
        assert "already approved" in result.message

    def test_cancel_request(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
    ) -> None:
        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        result = manager.cancel(
            request_id=request.id,
            requester=requester,
        )

        assert result.success is True
        assert result.request.status == ApprovalStatus.CANCELLED

    def test_only_requester_can_cancel(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
    ) -> None:
        other_user = SecurityContext(
            user_id="user-2",
            tenant_id="tenant-1",
            roles=["support_agent"],
        )

        request = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        result = manager.cancel(
            request_id=request.id,
            requester=other_user,
        )

        assert result.success is False
        assert "original requester" in result.message

    def test_approve_nonexistent(
        self,
        manager: ApprovalManager,
        approver: SecurityContext,
    ) -> None:
        result = manager.approve(
            request_id="nonexistent",
            reviewer=approver,
        )

        assert result.success is False
        assert "not found" in result.message

    def test_get_pending_requests(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
        approver: SecurityContext,
    ) -> None:
        # Create some requests
        for _ in range(3):
            manager.create_request(
                request_type="test",
                action="test",
                context={},
                requester=requester,
            )

        # Approve one
        pending = manager.get_pending_requests("tenant-1")
        manager.approve(request_id=pending[0].id, reviewer=approver)

        # Should have 2 pending now
        pending = manager.get_pending_requests("tenant-1")
        assert len(pending) == 2

    def test_get_stats(
        self,
        manager: ApprovalManager,
        requester: SecurityContext,
        approver: SecurityContext,
    ) -> None:
        # Create requests with different statuses
        req1 = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
            priority=ApprovalPriority.HIGH,
        )
        req2 = manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
            priority=ApprovalPriority.CRITICAL,
        )
        manager.create_request(
            request_type="test",
            action="test",
            context={},
            requester=requester,
        )

        manager.approve(request_id=req1.id, reviewer=approver)
        manager.reject(request_id=req2.id, reviewer=approver)

        stats = manager.get_stats("tenant-1")

        assert stats["total"] == 3
        assert stats["by_status"]["approved"] == 1
        assert stats["by_status"]["rejected"] == 1
        assert stats["by_status"]["pending"] == 1
        assert stats["pending_count"] == 1


class TestGlobalApprovalManager:
    """Tests for global approval manager."""

    def test_singleton(self) -> None:
        manager1 = get_approval_manager()
        manager2 = get_approval_manager()
        assert manager1 is manager2
