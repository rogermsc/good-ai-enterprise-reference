"""
Approvals service for human-in-the-loop workflow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from goodai.models import (
    ApprovalListResponse,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalStats,
    ApprovalStatus,
)

if TYPE_CHECKING:
    from goodai.client import GoodAIClient


class ApprovalsService:
    """
    Service for managing approval workflows.

    Example:
        # List pending approvals
        pending = await client.approvals.list_pending()
        for approval in pending.approvals:
            print(f"{approval.id}: {approval.action}")

        # Approve a request
        result = await client.approvals.approve(
            approval_id="abc-123",
            notes="Looks good, approved.",
        )
    """

    def __init__(self, client: GoodAIClient) -> None:
        self._client = client

    async def create(
        self,
        request_type: str,
        action: str,
        context: dict[str, Any] | None = None,
        priority: ApprovalPriority = ApprovalPriority.MEDIUM,
        metadata: dict[str, Any] | None = None,
    ) -> ApprovalRequest:
        """
        Create a new approval request.

        Args:
            request_type: Type of request (e.g., "ticket_response")
            action: The proposed action
            context: Additional context for approver
            priority: Request priority
            metadata: Additional metadata

        Returns:
            The created ApprovalRequest
        """
        payload = {
            "request_type": request_type,
            "action": action,
            "context": context or {},
            "priority": priority.value,
            "metadata": metadata or {},
        }

        data = await self._client._request(
            "POST",
            "/approvals",
            json=payload,
        )

        return ApprovalRequest(**data)

    async def get(self, approval_id: str) -> ApprovalRequest:
        """
        Get an approval request by ID.

        Args:
            approval_id: The approval request ID

        Returns:
            The ApprovalRequest
        """
        data = await self._client._request(
            "GET",
            f"/approvals/{approval_id}",
        )
        return ApprovalRequest(**data)

    async def list(
        self,
        status: ApprovalStatus | None = None,
        pending_only: bool = False,
        limit: int = 100,
    ) -> ApprovalListResponse:
        """
        List approval requests.

        Args:
            status: Filter by status
            pending_only: Show only pending requests
            limit: Maximum number of results

        Returns:
            ApprovalListResponse with list of requests
        """
        params: dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status.value
        if pending_only:
            params["pending_only"] = "true"

        data = await self._client._request(
            "GET",
            "/approvals",
            params=params,
        )

        return ApprovalListResponse(**data)

    async def list_pending(self, limit: int = 100) -> ApprovalListResponse:
        """
        List pending approval requests.

        Convenience method for listing only pending requests,
        sorted by priority (critical first) then by age (oldest first).

        Args:
            limit: Maximum number of results

        Returns:
            ApprovalListResponse with pending requests
        """
        data = await self._client._request(
            "GET",
            "/approvals/pending",
            params={"limit": limit},
        )
        return ApprovalListResponse(**data)

    async def get_stats(self) -> ApprovalStats:
        """
        Get approval statistics.

        Returns:
            ApprovalStats with counts and metrics
        """
        data = await self._client._request("GET", "/approvals/stats")
        return ApprovalStats(**data)

    async def approve(
        self,
        approval_id: str,
        notes: str | None = None,
    ) -> ApprovalRequest:
        """
        Approve a pending request.

        Requires appropriate role (admin, support_lead, manager, security).
        Cannot self-approve.

        Args:
            approval_id: The approval request ID
            notes: Optional notes from reviewer

        Returns:
            The updated ApprovalRequest
        """
        payload = {"notes": notes} if notes else {}

        data = await self._client._request(
            "POST",
            f"/approvals/{approval_id}/approve",
            json=payload,
        )

        return ApprovalRequest(**data["approval"])

    async def reject(
        self,
        approval_id: str,
        notes: str | None = None,
    ) -> ApprovalRequest:
        """
        Reject a pending request.

        Requires appropriate role (admin, support_lead, manager, security).

        Args:
            approval_id: The approval request ID
            notes: Reason for rejection (recommended)

        Returns:
            The updated ApprovalRequest
        """
        payload = {"notes": notes} if notes else {}

        data = await self._client._request(
            "POST",
            f"/approvals/{approval_id}/reject",
            json=payload,
        )

        return ApprovalRequest(**data["approval"])

    async def cancel(self, approval_id: str) -> ApprovalRequest:
        """
        Cancel a pending request.

        Only the original requester can cancel.

        Args:
            approval_id: The approval request ID

        Returns:
            The updated ApprovalRequest
        """
        data = await self._client._request(
            "POST",
            f"/approvals/{approval_id}/cancel",
            json={},
        )

        return ApprovalRequest(**data["approval"])
