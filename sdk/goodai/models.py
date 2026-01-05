"""
Data models for the Good AI SDK.

All models use Pydantic for validation and serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthStatus(BaseModel):
    """Health check response from the API."""

    model_config = ConfigDict(extra="ignore")

    status: str
    version: str
    environment: str
    timestamp: datetime | None = None


class TokenResponse(BaseModel):
    """JWT token response from authentication."""

    model_config = ConfigDict(extra="ignore")

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str | None = None


class TicketTriageResult(BaseModel):
    """Result of ticket triage analysis."""

    model_config = ConfigDict(extra="ignore")

    severity: str = Field(..., description="Ticket severity (P0-P4)")
    category: str | None = Field(None, description="Issue category")
    suggested_response: str | None = Field(None, description="AI-suggested response")
    recommended_actions: list[str] = Field(
        default_factory=list,
        description="Recommended actions",
    )
    requires_approval: bool = Field(
        default=False,
        description="Whether human approval is required",
    )
    approval_id: str | None = Field(None, description="ID if approval is pending")
    pii_detected: bool = Field(
        default=False,
        description="Whether PII was detected and redacted",
    )
    processing_time_ms: float | None = Field(None, description="Processing time")


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


class ApprovalRequest(BaseModel):
    """An approval request awaiting human review."""

    model_config = ConfigDict(extra="ignore")

    id: str
    request_type: str
    action: str
    context: dict[str, Any]
    requester: dict[str, Any]
    status: ApprovalStatus
    priority: ApprovalPriority
    created_at: datetime
    expires_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    review_notes: str | None = None
    is_expired: bool = False
    is_pending: bool = True


class ApprovalListResponse(BaseModel):
    """List of approval requests."""

    model_config = ConfigDict(extra="ignore")

    approvals: list[ApprovalRequest]
    total: int


class ApprovalStats(BaseModel):
    """Statistics about approval requests."""

    model_config = ConfigDict(extra="ignore")

    total: int
    by_status: dict[str, int]
    by_priority: dict[str, int]
    pending_count: int
    average_wait_seconds: float | None = None


class APIError(Exception):
    """Exception raised for API errors."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.details = details or {}

    def __str__(self) -> str:
        if self.status_code:
            return f"[{self.status_code}] {self.message}"
        return self.message
