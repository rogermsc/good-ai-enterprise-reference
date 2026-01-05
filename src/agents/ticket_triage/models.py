"""
Data models for the Ticket Triage Agent.

These models define the structure for:
- Input tickets
- Agent state
- Output results

All models use Pydantic for validation and serialization.
"""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TicketInput(BaseModel):
    """Input ticket for triage."""

    ticket_id: str = Field(..., description="Unique ticket identifier")
    subject: str = Field(..., description="Ticket subject line")
    body: str = Field(..., description="Ticket body/content")
    customer_email: str | None = Field(None, description="Customer email address")
    source: str = Field("email", description="Ticket source (email, chat, phone)")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class TicketState(BaseModel):
    """
    Agent state for ticket triage workflow.

    This state is passed between nodes in the LangGraph workflow.
    """

    # Input data
    ticket_id: str
    subject: str
    body: str
    customer_email: str | None = None
    source: str = "email"
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Redaction state
    redacted_subject: str | None = None
    redacted_body: str | None = None
    token_map: dict[str, str] = Field(default_factory=dict)
    pii_found: dict[str, int] = Field(default_factory=dict)

    # Classification state
    severity: str | None = None
    severity_reasoning: str | None = None

    # Actions state
    actions: list[str] = Field(default_factory=list)
    actions_reasoning: str | None = None

    # Policy state
    policy_allowed: bool = False
    policy_requires_approval: bool = False
    policy_reason: str | None = None
    policy_risk_level: str | None = None

    # Response state
    response: str | None = None
    approval_required: bool = False
    approval_id: str | None = None  # ID of pending approval request if required

    # Guardrail state
    guardrail_passed: bool | None = None
    guardrail_violations: list[dict[str, Any]] | None = None

    # Audit state
    audit_log_id: str | None = None

    # Tracking
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    total_latency_ms: int = 0
    total_cost_estimate: float = 0.0
    llm_calls: int = 0
    errors: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

    @property
    def redacted_content(self) -> str:
        """Get combined redacted content."""
        parts = []
        if self.redacted_subject:
            parts.append(f"Subject: {self.redacted_subject}")
        if self.redacted_body:
            parts.append(f"Body: {self.redacted_body}")
        return "\n".join(parts)


class TriageResult(BaseModel):
    """Result of ticket triage operation."""

    ticket_id: str
    severity: str | None
    actions: list[str]
    policy_decision: dict[str, Any]
    response: str | None
    approval_required: bool
    approval_id: str | None = None  # ID of pending approval request if required
    audit_log_id: str | None
    latency_ms: int
    cost_estimate: float
    errors: list[str] = Field(default_factory=list)
    guardrail_passed: bool | None = None
    guardrail_violations: list[dict[str, Any]] | None = None

    @classmethod
    def from_state(cls, state: TicketState) -> "TriageResult":
        """Create result from agent state."""
        return cls(
            ticket_id=state.ticket_id,
            severity=state.severity,
            actions=state.actions,
            policy_decision={
                "allowed": state.policy_allowed,
                "requires_approval": state.policy_requires_approval,
                "reason": state.policy_reason,
                "risk_level": state.policy_risk_level,
            },
            response=state.response,
            approval_required=state.approval_required,
            approval_id=state.approval_id,
            audit_log_id=state.audit_log_id,
            latency_ms=state.total_latency_ms,
            cost_estimate=state.total_cost_estimate,
            errors=state.errors,
            guardrail_passed=state.guardrail_passed,
            guardrail_violations=state.guardrail_violations,
        )
