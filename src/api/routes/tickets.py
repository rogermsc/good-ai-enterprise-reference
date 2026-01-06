"""
Ticket triage API endpoints.

Provides endpoints for:
- Submitting tickets for triage
- Retrieving triage results
- Streaming triage responses (SSE)
"""

from collections.abc import AsyncGenerator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse as FastAPIStreamingResponse
from pydantic import BaseModel, Field, field_validator

from src.agents.ticket_triage import TicketInput, run_triage
from src.core.security import get_security_context
from src.core.streaming import SSEEventType, StreamingResponse
from src.db.connection import get_connection

router = APIRouter(prefix="/tickets", tags=["tickets"])


class TicketRequest(BaseModel):
    """Request body for ticket triage."""

    ticket_id: str = Field(
        ...,
        description="Unique ticket identifier",
        min_length=1,
        max_length=100,
    )
    subject: str = Field(
        ...,
        description="Ticket subject line",
        min_length=1,
        max_length=500,
    )
    body: str = Field(
        ...,
        description="Ticket body content",
        min_length=1,
        max_length=50000,
    )
    customer_email: str | None = Field(
        None,
        description="Customer email address",
        max_length=255,
    )
    source: str = Field(
        "email",
        description="Ticket source (email, chat, phone)",
        max_length=50,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: str) -> str:
        """Validate ticket ID format."""
        # Remove any null bytes or control characters
        if "\x00" in v or any(ord(c) < 32 for c in v):
            raise ValueError("Ticket ID contains invalid characters")
        return v.strip()

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Validate source is from allowed values."""
        allowed_sources = {"email", "chat", "phone", "web", "api", "internal"}
        if v.lower() not in allowed_sources:
            raise ValueError(f"Source must be one of: {', '.join(allowed_sources)}")
        return v.lower()


class TriageResponse(BaseModel):
    """Response from ticket triage."""

    ticket_id: str
    severity: str | None
    actions: list[str]
    policy_decision: dict[str, Any]
    response: str | None
    approval_required: bool
    audit_log_id: str | None
    latency_ms: int
    cost_estimate: float
    errors: list[str] = Field(default_factory=list)


@router.post(
    "/triage",
    response_model=TriageResponse,
    summary="Triage a support ticket",
    description="""
    Submit a support ticket for AI-powered triage.

    The agent will:
    1. Redact PII (CPF, CNPJ, emails, phones)
    2. Classify severity (P0-P4)
    3. Recommend actions
    4. Check policy (RBAC, severity rules)
    5. Generate customer response (if approved)
    6. Log to audit trail

    **Authentication:** Requires X-User-Id, X-Tenant-Id, and X-Roles headers.

    **Policy:** P0/P1 tickets require approval before response generation.
    """,
    responses={
        200: {
            "description": "Triage completed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "ticket_id": "TKT-2026-001",
                        "severity": "P2",
                        "actions": ["classify", "respond", "notify_customer"],
                        "policy_decision": {
                            "allowed": True,
                            "requires_approval": False,
                            "reason": "All policy checks passed",
                            "risk_level": "low",
                        },
                        "response": "Thank you for contacting us...",
                        "approval_required": False,
                        "audit_log_id": "550e8400-e29b-41d4-a716-446655440000",
                        "latency_ms": 1250,
                        "cost_estimate": 0.0045,
                        "errors": [],
                    }
                }
            },
        },
        401: {"description": "Missing authentication headers"},
        403: {"description": "Policy denied the request"},
    },
)
async def triage_ticket(
    request: Request,
    ticket: TicketRequest,
) -> TriageResponse:
    """
    Triage a support ticket.

    Runs the full triage workflow:
    - PII redaction
    - Severity classification
    - Action recommendation
    - Policy check
    - Response generation (if approved)
    - Audit logging

    Returns triage result with policy decision.
    """
    # Get security context from headers
    try:
        security_context = get_security_context(request)
    except HTTPException:
        raise

    # Convert request to agent input
    ticket_input = TicketInput(
        ticket_id=ticket.ticket_id,
        subject=ticket.subject,
        body=ticket.body,
        customer_email=ticket.customer_email,
        source=ticket.source,
        metadata=ticket.metadata,
    )

    # Run triage with database connection for audit logging
    try:
        async with get_connection() as conn:
            result = await run_triage(
                ticket=ticket_input,
                security_context=security_context,
                db_conn=conn,
            )
    except Exception as e:
        # Run without database if connection fails
        result = await run_triage(
            ticket=ticket_input,
            security_context=security_context,
            db_conn=None,
        )
        # Add error to result
        result.errors.append(f"Database connection failed: {e!s}")

    # Check if policy denied
    if not result.policy_decision.get("allowed", True):
        reason = result.policy_decision.get("reason", "Policy check failed")
        risk_level = result.policy_decision.get("risk_level", "unknown")
        raise HTTPException(
            status_code=403,
            detail=f"Policy denied the request: {reason} (risk level: {risk_level})",
        )

    return TriageResponse(
        ticket_id=result.ticket_id,
        severity=result.severity,
        actions=result.actions,
        policy_decision=result.policy_decision,
        response=result.response,
        approval_required=result.approval_required,
        audit_log_id=result.audit_log_id,
        latency_ms=result.latency_ms,
        cost_estimate=result.cost_estimate,
        errors=result.errors,
    )


@router.get(
    "/triage/{ticket_id}",
    summary="Get triage result",
    description="Retrieve triage result for a ticket (placeholder for future implementation)",
)
async def get_triage_result(
    request: Request,
    ticket_id: str,
) -> dict[str, str]:
    """
    Get triage result for a ticket.

    This is a placeholder for future implementation.
    Would retrieve stored triage results from the database.
    """
    # Get security context
    security_context = get_security_context(request)

    return {
        "message": "Not implemented",
        "ticket_id": ticket_id,
        "tenant_id": security_context.tenant_id,
    }


@router.post(
    "/triage/stream",
    summary="Stream ticket triage (SSE)",
    description="""
    Submit a support ticket for AI-powered triage with streaming response.

    Returns Server-Sent Events (SSE) stream with:
    - progress: Updates on each processing stage
    - token: Individual tokens as they are generated
    - done: Final result with metadata
    - error: Error information if something fails

    **Event format:**
    ```
    event: progress
    data: {"status": "pii_redaction", "node": "pii_redact"}

    event: token
    data: {"token": "Thank "}

    event: done
    data: {"status": "complete", "severity": "P2", "latency_ms": 1250}
    ```

    **Authentication:** Requires X-User-Id, X-Tenant-Id, and X-Roles headers.
    """,
    response_class=FastAPIStreamingResponse,
    responses={
        200: {
            "description": "SSE stream of triage events",
            "content": {"text/event-stream": {}},
        },
        401: {"description": "Missing authentication headers"},
    },
)
async def triage_ticket_stream(
    request: Request,
    ticket: TicketRequest,
) -> FastAPIStreamingResponse:
    """
    Stream ticket triage as Server-Sent Events.

    Provides real-time updates during triage:
    - Progress events for each workflow stage
    - Token events for streaming response
    - Done event with final metadata
    """
    # Get security context from headers
    try:
        security_context = get_security_context(request)
    except HTTPException:
        raise

    request_id = str(uuid4())

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for triage workflow."""
        stream = StreamingResponse(request_id)

        # Convert request to agent input
        ticket_input = TicketInput(
            ticket_id=ticket.ticket_id,
            subject=ticket.subject,
            body=ticket.body,
            customer_email=ticket.customer_email,
            source=ticket.source,
            metadata=ticket.metadata,
        )

        yield stream.progress("starting", message="Initializing triage")

        try:
            # Run triage with database connection
            yield stream.progress("connecting_db", message="Connecting to database")

            try:
                async with get_connection() as conn:
                    yield stream.progress("pii_redaction", message="Redacting PII")
                    yield stream.progress("classification", message="Classifying severity")
                    yield stream.progress("policy_check", message="Checking policy")

                    result = await run_triage(
                        ticket=ticket_input,
                        security_context=security_context,
                        db_conn=conn,
                    )
            except Exception:
                yield stream.progress("db_fallback", message="Running without database")
                result = await run_triage(
                    ticket=ticket_input,
                    security_context=security_context,
                    db_conn=None,
                )

            # Stream response tokens if available
            if result.response:
                yield stream.progress("generating_response", message="Generating response")
                words = result.response.split()
                for i, word in enumerate(words):
                    token = word + (" " if i < len(words) - 1 else "")
                    yield stream.token(token)

            # Send final result
            yield stream.done(
                {
                    "status": "complete",
                    "ticket_id": result.ticket_id,
                    "severity": result.severity,
                    "actions": result.actions,
                    "policy_decision": result.policy_decision,
                    "approval_required": result.approval_required,
                    "audit_log_id": result.audit_log_id,
                    "latency_ms": result.latency_ms,
                    "cost_estimate": result.cost_estimate,
                    "errors": result.errors,
                }
            )

        except Exception as e:
            yield stream.event(
                SSEEventType.ERROR,
                {"error": str(e), "code": "TRIAGE_ERROR"},
            )

    return FastAPIStreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )
