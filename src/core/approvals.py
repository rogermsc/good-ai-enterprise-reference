"""
Human-in-the-Loop Approval System.

Provides a workflow for managing human approvals of AI-proposed actions.
When the Policy Engine requires approval, requests are queued here for
human review before execution.

Features:
- Approval request creation and tracking
- Approve/reject workflow with audit trail
- Expiration handling for stale requests
- Multi-level approval chains
- Notification hooks for integration
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Any, ClassVar

from src.core.config import get_settings
from src.core.observability import get_logger, get_tracer
from src.core.security import SecurityContext

logger = get_logger()
tracer = get_tracer()


class ApprovalStatus(str, Enum):
    """Status of an approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalPriority(str, Enum):
    """Priority level for approval requests."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class ApprovalRequest:
    """
    A request awaiting human approval.

    Attributes:
        id: Unique identifier
        request_type: Type of request (e.g., "ticket_response", "data_access")
        action: The proposed action to approve
        context: Additional context for the approver
        requester: Who initiated the request
        status: Current approval status
        priority: Request priority
        created_at: When the request was created
        expires_at: When the request expires
        reviewed_by: Who approved/rejected
        reviewed_at: When it was reviewed
        review_notes: Notes from the reviewer
        metadata: Additional request metadata
    """

    id: str
    request_type: str
    action: str
    context: dict[str, Any]
    requester: SecurityContext
    status: ApprovalStatus = ApprovalStatus.PENDING
    priority: ApprovalPriority = ApprovalPriority.MEDIUM
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set default expiration if not provided."""
        if self.expires_at is None:
            # Default expiration based on priority
            expiration_hours = {
                ApprovalPriority.CRITICAL: 1,
                ApprovalPriority.HIGH: 4,
                ApprovalPriority.MEDIUM: 24,
                ApprovalPriority.LOW: 72,
            }
            hours = expiration_hours.get(self.priority, 24)
            self.expires_at = self.created_at + timedelta(hours=hours)

    @property
    def is_expired(self) -> bool:
        """Check if the request has expired."""
        if self.expires_at is None:
            return False
        return datetime.now(UTC) > self.expires_at

    @property
    def is_pending(self) -> bool:
        """Check if the request is still pending."""
        return self.status == ApprovalStatus.PENDING and not self.is_expired

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "request_type": self.request_type,
            "action": self.action,
            "context": self.context,
            "requester": {
                "user_id": self.requester.user_id,
                "tenant_id": self.requester.tenant_id,
                "roles": list(self.requester.roles),
            },
            "status": self.status.value,
            "priority": self.priority.value,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_notes": self.review_notes,
            "metadata": self.metadata,
            "is_expired": self.is_expired,
            "is_pending": self.is_pending,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalRequest":
        """Create from dictionary."""
        requester_data = data["requester"]
        requester = SecurityContext(
            user_id=requester_data["user_id"],
            tenant_id=requester_data["tenant_id"],
            roles=tuple(requester_data.get("roles", [])),
        )
        return cls(
            id=data["id"],
            request_type=data["request_type"],
            action=data["action"],
            context=data["context"],
            requester=requester,
            status=ApprovalStatus(data["status"]),
            priority=ApprovalPriority(data["priority"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            expires_at=(
                datetime.fromisoformat(data["expires_at"]) if data.get("expires_at") else None
            ),
            reviewed_by=data.get("reviewed_by"),
            reviewed_at=(
                datetime.fromisoformat(data["reviewed_at"]) if data.get("reviewed_at") else None
            ),
            review_notes=data.get("review_notes"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ApprovalResult:
    """Result of an approval action."""

    success: bool
    request: ApprovalRequest
    message: str


class ApprovalStore:
    """
    In-memory storage for approval requests.

    In production, this would be backed by a database.
    """

    def __init__(self) -> None:
        self._requests: dict[str, ApprovalRequest] = {}

    def save(self, request: ApprovalRequest) -> None:
        """Save an approval request."""
        self._requests[request.id] = request

    def get(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        return self._requests.get(request_id)

    def get_by_tenant(
        self,
        tenant_id: str,
        status: ApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        """Get approval requests for a tenant."""
        requests = [r for r in self._requests.values() if r.requester.tenant_id == tenant_id]

        if status is not None:
            requests = [r for r in requests if r.status == status]

        # Sort by priority (critical first) then by created_at (oldest first)
        priority_order = [
            ApprovalPriority.CRITICAL,
            ApprovalPriority.HIGH,
            ApprovalPriority.MEDIUM,
            ApprovalPriority.LOW,
        ]
        requests.sort(
            key=lambda r: (
                priority_order.index(r.priority),
                r.created_at,
            )
        )

        return requests[:limit]

    def get_pending(self, tenant_id: str, limit: int = 100) -> list[ApprovalRequest]:
        """Get pending approval requests for a tenant."""
        return [
            r for r in self.get_by_tenant(tenant_id, ApprovalStatus.PENDING, limit) if r.is_pending
        ]

    def delete(self, request_id: str) -> bool:
        """Delete an approval request."""
        if request_id in self._requests:
            del self._requests[request_id]
            return True
        return False

    def clear(self, tenant_id: str | None = None) -> int:
        """Clear approval requests, optionally for a specific tenant."""
        if tenant_id is None:
            count = len(self._requests)
            self._requests.clear()
            return count

        to_delete = [r.id for r in self._requests.values() if r.requester.tenant_id == tenant_id]
        for request_id in to_delete:
            del self._requests[request_id]
        return len(to_delete)


class ApprovalManager:
    """
    Manages the human-in-the-loop approval workflow.

    Example:
        manager = ApprovalManager()

        # Create approval request
        request = manager.create_request(
            request_type="ticket_response",
            action="send_customer_response",
            context={"ticket_id": "123", "response": "..."},
            requester=security_context,
            priority=ApprovalPriority.HIGH,
        )

        # Approve the request
        result = manager.approve(
            request_id=request.id,
            reviewer=admin_context,
            notes="Looks good",
        )
    """

    # Roles that can approve requests
    APPROVER_ROLES: ClassVar[set[str]] = {
        "admin",
        "support_lead",
        "manager",
        "security",
    }

    def __init__(self, store: ApprovalStore | None = None) -> None:
        self.store = store or ApprovalStore()
        self._settings = get_settings()

    def create_request(
        self,
        request_type: str,
        action: str,
        context: dict[str, Any],
        requester: SecurityContext,
        priority: ApprovalPriority = ApprovalPriority.MEDIUM,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """
        Create a new approval request.

        Args:
            request_type: Type of request
            action: The proposed action
            context: Additional context for the approver
            requester: Who is requesting approval
            priority: Request priority
            metadata: Additional metadata

        Returns:
            The created approval request
        """
        with tracer.start_as_current_span("approvals.create_request") as span:
            request = ApprovalRequest(
                id=str(uuid.uuid4()),
                request_type=request_type,
                action=action,
                context=context,
                requester=requester,
                priority=priority,
                metadata=metadata or {},
            )

            self.store.save(request)

            span.set_attribute("approval_id", request.id)
            span.set_attribute("request_type", request_type)
            span.set_attribute("priority", priority.value)

            logger.info(
                "approval_request_created",
                approval_id=request.id,
                request_type=request_type,
                action=action,
                priority=priority.value,
                requester_id=requester.user_id,
                tenant_id=requester.tenant_id,
            )

            return request

    def get_request(self, request_id: str) -> ApprovalRequest | None:
        """Get an approval request by ID."""
        return self.store.get(request_id)

    def get_pending_requests(
        self,
        tenant_id: str,
        limit: int = 100,
    ) -> list[ApprovalRequest]:
        """Get pending approval requests for a tenant."""
        return self.store.get_pending(tenant_id, limit)

    def _can_review(
        self,
        request: ApprovalRequest,
        reviewer: SecurityContext,
    ) -> tuple[bool, str]:
        """Check if the reviewer can approve/reject this request."""
        # Must be same tenant
        if request.requester.tenant_id != reviewer.tenant_id:
            return False, "Reviewer must be in the same tenant"

        # Cannot self-approve
        if request.requester.user_id == reviewer.user_id:
            return False, "Cannot approve your own request"

        # Must have approver role
        has_approver_role = any(role in self.APPROVER_ROLES for role in reviewer.roles)
        if not has_approver_role:
            return False, f"Must have one of these roles to approve: {self.APPROVER_ROLES}"

        return True, "Authorized to review"

    def approve(
        self,
        request_id: str,
        reviewer: SecurityContext,
        notes: str | None = None,
    ) -> ApprovalResult:
        """
        Approve a pending request.

        Args:
            request_id: ID of the request to approve
            reviewer: Who is approving
            notes: Optional notes from the reviewer

        Returns:
            ApprovalResult with success status
        """
        with tracer.start_as_current_span("approvals.approve") as span:
            span.set_attribute("approval_id", request_id)
            span.set_attribute("reviewer_id", reviewer.user_id)

            request = self.store.get(request_id)
            if request is None:
                return ApprovalResult(
                    success=False,
                    request=ApprovalRequest(
                        id=request_id,
                        request_type="unknown",
                        action="unknown",
                        context={},
                        requester=reviewer,
                    ),
                    message="Approval request not found",
                )

            # Check if already processed
            if request.status != ApprovalStatus.PENDING:
                return ApprovalResult(
                    success=False,
                    request=request,
                    message=f"Request already {request.status.value}",
                )

            # Check expiration
            if request.is_expired:
                request.status = ApprovalStatus.EXPIRED
                self.store.save(request)
                return ApprovalResult(
                    success=False,
                    request=request,
                    message="Request has expired",
                )

            # Check authorization
            can_review, reason = self._can_review(request, reviewer)
            if not can_review:
                return ApprovalResult(
                    success=False,
                    request=request,
                    message=reason,
                )

            # Approve
            request.status = ApprovalStatus.APPROVED
            request.reviewed_by = reviewer.user_id
            request.reviewed_at = datetime.now(UTC)
            request.review_notes = notes
            self.store.save(request)

            logger.info(
                "approval_request_approved",
                approval_id=request_id,
                reviewer_id=reviewer.user_id,
                request_type=request.request_type,
            )

            return ApprovalResult(
                success=True,
                request=request,
                message="Request approved successfully",
            )

    def reject(
        self,
        request_id: str,
        reviewer: SecurityContext,
        notes: str | None = None,
    ) -> ApprovalResult:
        """
        Reject a pending request.

        Args:
            request_id: ID of the request to reject
            reviewer: Who is rejecting
            notes: Reason for rejection (recommended)

        Returns:
            ApprovalResult with success status
        """
        with tracer.start_as_current_span("approvals.reject") as span:
            span.set_attribute("approval_id", request_id)
            span.set_attribute("reviewer_id", reviewer.user_id)

            request = self.store.get(request_id)
            if request is None:
                return ApprovalResult(
                    success=False,
                    request=ApprovalRequest(
                        id=request_id,
                        request_type="unknown",
                        action="unknown",
                        context={},
                        requester=reviewer,
                    ),
                    message="Approval request not found",
                )

            # Check if already processed
            if request.status != ApprovalStatus.PENDING:
                return ApprovalResult(
                    success=False,
                    request=request,
                    message=f"Request already {request.status.value}",
                )

            # Check authorization
            can_review, reason = self._can_review(request, reviewer)
            if not can_review:
                return ApprovalResult(
                    success=False,
                    request=request,
                    message=reason,
                )

            # Reject
            request.status = ApprovalStatus.REJECTED
            request.reviewed_by = reviewer.user_id
            request.reviewed_at = datetime.now(UTC)
            request.review_notes = notes
            self.store.save(request)

            logger.info(
                "approval_request_rejected",
                approval_id=request_id,
                reviewer_id=reviewer.user_id,
                request_type=request.request_type,
                notes=notes,
            )

            return ApprovalResult(
                success=True,
                request=request,
                message="Request rejected",
            )

    def cancel(
        self,
        request_id: str,
        requester: SecurityContext,
    ) -> ApprovalResult:
        """
        Cancel a pending request (by the original requester).

        Args:
            request_id: ID of the request to cancel
            requester: The original requester

        Returns:
            ApprovalResult with success status
        """
        request = self.store.get(request_id)
        if request is None:
            return ApprovalResult(
                success=False,
                request=ApprovalRequest(
                    id=request_id,
                    request_type="unknown",
                    action="unknown",
                    context={},
                    requester=requester,
                ),
                message="Approval request not found",
            )

        # Only original requester can cancel
        if request.requester.user_id != requester.user_id:
            return ApprovalResult(
                success=False,
                request=request,
                message="Only the original requester can cancel",
            )

        if request.status != ApprovalStatus.PENDING:
            return ApprovalResult(
                success=False,
                request=request,
                message=f"Request already {request.status.value}",
            )

        request.status = ApprovalStatus.CANCELLED
        self.store.save(request)

        logger.info(
            "approval_request_cancelled",
            approval_id=request_id,
            requester_id=requester.user_id,
        )

        return ApprovalResult(
            success=True,
            request=request,
            message="Request cancelled",
        )

    def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """Get approval statistics for a tenant."""
        all_requests = self.store.get_by_tenant(tenant_id)

        status_counts = {status.value: 0 for status in ApprovalStatus}
        priority_counts = {priority.value: 0 for priority in ApprovalPriority}

        for request in all_requests:
            status_counts[request.status.value] += 1
            priority_counts[request.priority.value] += 1

        pending_requests = [r for r in all_requests if r.is_pending]
        avg_wait_time = None
        if pending_requests:
            wait_times = [
                (datetime.now(UTC) - r.created_at).total_seconds() for r in pending_requests
            ]
            avg_wait_time = sum(wait_times) / len(wait_times)

        return {
            "total": len(all_requests),
            "by_status": status_counts,
            "by_priority": priority_counts,
            "pending_count": len(pending_requests),
            "average_wait_seconds": avg_wait_time,
        }


# Global approval manager instance
_approval_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    """Get the global approval manager instance."""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
