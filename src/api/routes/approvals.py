"""
API routes for Human-in-the-Loop approval workflow.

Provides endpoints for:
- Listing pending approvals
- Viewing approval details
- Approving/rejecting requests
- Cancelling requests
- Statistics
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.core.approvals import (
    ApprovalManager,
    ApprovalPriority,
    ApprovalRequest,
    ApprovalStatus,
    get_approval_manager,
)
from src.core.observability import get_logger
from src.core.security import SecurityContext, get_current_user

logger = get_logger()

router = APIRouter(prefix="/approvals", tags=["approvals"])


# Request/Response Models


class CreateApprovalRequest(BaseModel):
    """Request to create an approval."""

    model_config = ConfigDict(extra="forbid")

    request_type: str = Field(..., description="Type of request", min_length=1)
    action: str = Field(..., description="The proposed action", min_length=1)
    context: dict = Field(default_factory=dict, description="Additional context")
    priority: ApprovalPriority = Field(
        default=ApprovalPriority.MEDIUM,
        description="Request priority",
    )
    metadata: dict = Field(default_factory=dict, description="Additional metadata")


class ReviewRequest(BaseModel):
    """Request to approve or reject."""

    model_config = ConfigDict(extra="forbid")

    notes: str | None = Field(None, description="Review notes")


class ApprovalResponse(BaseModel):
    """Response containing approval details."""

    model_config = ConfigDict(extra="forbid")

    id: str
    request_type: str
    action: str
    context: dict
    requester: dict
    status: str
    priority: str
    created_at: str
    expires_at: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    review_notes: str | None
    metadata: dict
    is_expired: bool
    is_pending: bool


class ApprovalListResponse(BaseModel):
    """Response containing list of approvals."""

    model_config = ConfigDict(extra="forbid")

    approvals: list[ApprovalResponse]
    total: int


class ApprovalActionResponse(BaseModel):
    """Response for approval actions."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    message: str
    approval: ApprovalResponse


class ApprovalStatsResponse(BaseModel):
    """Response containing approval statistics."""

    model_config = ConfigDict(extra="forbid")

    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    pending_count: int
    average_wait_seconds: float | None


def _to_response(request: ApprovalRequest) -> ApprovalResponse:
    """Convert ApprovalRequest to response model."""
    data = request.to_dict()
    return ApprovalResponse(**data)


# Endpoints


@router.post("", response_model=ApprovalResponse)
async def create_approval(
    request: CreateApprovalRequest,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
) -> ApprovalResponse:
    """
    Create a new approval request.

    This is typically called internally when the policy engine
    requires approval for an action.
    """
    approval = manager.create_request(
        request_type=request.request_type,
        action=request.action,
        context=request.context,
        requester=user,
        priority=request.priority,
        metadata=request.metadata,
    )
    return _to_response(approval)


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
    status: Annotated[ApprovalStatus | None, Query(description="Filter by status")] = None,
    pending_only: Annotated[bool, Query(description="Show only pending")] = False,
    limit: Annotated[int, Query(ge=1, le=500, description="Max results")] = 100,
) -> ApprovalListResponse:
    """
    List approval requests for the tenant.

    By default, shows all approvals. Use filters to narrow results.
    """
    if pending_only:
        approvals = manager.get_pending_requests(user.tenant_id, limit)
    else:
        approvals = manager.store.get_by_tenant(user.tenant_id, status, limit)

    return ApprovalListResponse(
        approvals=[_to_response(a) for a in approvals],
        total=len(approvals),
    )


@router.get("/pending", response_model=ApprovalListResponse)
async def list_pending_approvals(
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
    limit: Annotated[int, Query(ge=1, le=500, description="Max results")] = 100,
) -> ApprovalListResponse:
    """
    List pending approval requests for the tenant.

    Sorted by priority (critical first) then by creation time (oldest first).
    """
    approvals = manager.get_pending_requests(user.tenant_id, limit)
    return ApprovalListResponse(
        approvals=[_to_response(a) for a in approvals],
        total=len(approvals),
    )


@router.get("/stats", response_model=ApprovalStatsResponse)
async def get_approval_stats(
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
) -> ApprovalStatsResponse:
    """Get approval statistics for the tenant."""
    stats = manager.get_stats(user.tenant_id)
    return ApprovalStatsResponse(**stats)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
) -> ApprovalResponse:
    """Get a specific approval request."""
    approval = manager.get_request(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found")

    # Ensure same tenant
    if approval.requester.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="Approval not found")

    return _to_response(approval)


@router.post("/{approval_id}/approve", response_model=ApprovalActionResponse)
async def approve_request(
    approval_id: str,
    review: ReviewRequest,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
) -> ApprovalActionResponse:
    """
    Approve a pending request.

    Requires appropriate role (admin, support_lead, manager, or security).
    Cannot self-approve.
    """
    result = manager.approve(
        request_id=approval_id,
        reviewer=user,
        notes=review.notes,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return ApprovalActionResponse(
        success=True,
        message=result.message,
        approval=_to_response(result.request),
    )


@router.post("/{approval_id}/reject", response_model=ApprovalActionResponse)
async def reject_request(
    approval_id: str,
    review: ReviewRequest,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
) -> ApprovalActionResponse:
    """
    Reject a pending request.

    Requires appropriate role (admin, support_lead, manager, or security).
    """
    result = manager.reject(
        request_id=approval_id,
        reviewer=user,
        notes=review.notes,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return ApprovalActionResponse(
        success=True,
        message=result.message,
        approval=_to_response(result.request),
    )


@router.post("/{approval_id}/cancel", response_model=ApprovalActionResponse)
async def cancel_request(
    approval_id: str,
    user: Annotated[SecurityContext, Depends(get_current_user)],
    manager: Annotated[ApprovalManager, Depends(get_approval_manager)],
) -> ApprovalActionResponse:
    """
    Cancel a pending request.

    Only the original requester can cancel their request.
    """
    result = manager.cancel(
        request_id=approval_id,
        requester=user,
    )

    if not result.success:
        raise HTTPException(status_code=400, detail=result.message)

    return ApprovalActionResponse(
        success=True,
        message=result.message,
        approval=_to_response(result.request),
    )
