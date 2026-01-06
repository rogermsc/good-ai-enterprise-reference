"""
LangGraph nodes for the Ticket Triage Agent.

Each node is a function that:
1. Takes the current state
2. Performs a specific operation
3. Returns updated state

Nodes are composed into a graph in graph.py.
"""

import json
import time
from datetime import UTC, datetime
from typing import Any

import asyncpg

from src.agents.ticket_triage.models import TicketState
from src.core.approvals import ApprovalManager, ApprovalPriority, get_approval_manager
from src.core.audit_log import AuditLogger, AuditLogPayload
from src.core.config import get_settings
from src.core.guardrails import GuardrailAction, GuardrailPipeline
from src.core.llm_gateway import LLMGateway
from src.core.observability import get_logger
from src.core.pii_redaction import PIIRedactor
from src.core.policy_engine import PolicyEngine
from src.core.security import SecurityContext
from src.core.webhooks import WebhookEventType, WebhookManager, get_webhook_manager

logger = get_logger()


class TriageNodes:
    """
    Node implementations for ticket triage workflow.

    Each method is a node that can be used in a LangGraph graph.
    """

    def __init__(
        self,
        security_context: SecurityContext,
        db_conn: asyncpg.Connection | None = None,
        approval_manager: ApprovalManager | None = None,
        webhook_manager: WebhookManager | None = None,
    ):
        """
        Initialize nodes with dependencies.

        Args:
            security_context: User authentication context
            db_conn: Optional database connection for audit logging
            approval_manager: Manager for approval workflow
            webhook_manager: Manager for webhook notifications
        """
        self.security_context = security_context
        self.db_conn = db_conn
        self.settings = get_settings()
        self.pii_redactor = PIIRedactor()
        self.policy_engine = PolicyEngine()
        self.llm_gateway = LLMGateway(self.settings)
        self.audit_logger = AuditLogger()
        self.guardrail_pipeline = GuardrailPipeline()
        self.approval_manager = approval_manager or get_approval_manager()
        self.webhook_manager = webhook_manager or get_webhook_manager()

    async def ingest_ticket(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Ingest and validate ticket input.

        This is typically the entry point of the workflow.
        """
        return {
            "started_at": datetime.now(UTC),
        }

    async def pii_redact(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Redact PII from ticket content.

        Tokenizes sensitive data before LLM processing.
        """
        start_time = time.time()

        # Redact subject
        subject_result = self.pii_redactor.redact(state.subject)

        # Redact body
        body_result = self.pii_redactor.redact(state.body)

        # Merge token maps
        combined_token_map = {
            **subject_result.token_map,
            **body_result.token_map,
        }

        # Merge PII found counts
        combined_pii_found: dict[str, int] = {}
        for pii_type, count in subject_result.patterns_found.items():
            combined_pii_found[pii_type] = combined_pii_found.get(pii_type, 0) + count
        for pii_type, count in body_result.patterns_found.items():
            combined_pii_found[pii_type] = combined_pii_found.get(pii_type, 0) + count

        latency_ms = int((time.time() - start_time) * 1000)

        return {
            "redacted_subject": subject_result.redacted_text,
            "redacted_body": body_result.redacted_text,
            "token_map": combined_token_map,
            "pii_found": combined_pii_found,
            "total_latency_ms": state.total_latency_ms + latency_ms,
        }

    async def classify_severity(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Classify ticket severity using LLM.

        Uses redacted content to classify as P0-P4.
        """
        start_time = time.time()

        # Use redacted content for classification
        content = state.redacted_content

        try:
            response = await self.llm_gateway.classify_severity(content)

            # Parse severity from response
            severity = response.content.strip().upper()
            if severity not in ("P0", "P1", "P2", "P3", "P4"):
                # Default to P3 if parsing fails
                severity = "P3"

            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "severity": severity,
                "total_latency_ms": state.total_latency_ms + latency_ms,
                "total_cost_estimate": state.total_cost_estimate + response.cost_estimate,
                "llm_calls": state.llm_calls + 1,
            }

        except Exception as e:
            return {
                "severity": "P3",  # Default on error
                "errors": [*state.errors, f"Classification error: {e!s}"],
            }

    async def recommend_actions(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Recommend actions based on ticket and severity.
        """
        start_time = time.time()

        content = state.redacted_content
        severity = state.severity or "P3"

        try:
            response = await self.llm_gateway.recommend_actions(content, severity)

            # Parse actions from JSON response
            try:
                actions = json.loads(response.content)
                if not isinstance(actions, list):
                    actions = ["classify", "respond"]
            except json.JSONDecodeError:
                actions = ["classify", "respond"]

            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "actions": actions,
                "total_latency_ms": state.total_latency_ms + latency_ms,
                "total_cost_estimate": state.total_cost_estimate + response.cost_estimate,
                "llm_calls": state.llm_calls + 1,
            }

        except Exception as e:
            return {
                "actions": ["classify", "respond"],
                "errors": [*state.errors, f"Action recommendation error: {e!s}"],
            }

    async def policy_check(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Evaluate proposed actions against policy engine.

        This is the critical security gate - all actions must pass policy.
        If approval is required, creates an ApprovalRequest for human review.
        """
        severity = state.severity or "P3"
        actions = state.actions or []

        decision = self.policy_engine.evaluate(
            severity=severity,
            proposed_actions=actions,
            user_context=self.security_context,
        )

        result: dict[str, Any] = {
            "policy_allowed": decision.allowed,
            "policy_requires_approval": decision.requires_approval,
            "policy_reason": decision.reason,
            "policy_risk_level": decision.risk_level,
            "approval_required": decision.requires_approval,
        }

        # Create approval request if required
        if decision.requires_approval:
            # Map severity to approval priority
            priority_map = {
                "P0": ApprovalPriority.CRITICAL,
                "P1": ApprovalPriority.HIGH,
                "P2": ApprovalPriority.MEDIUM,
                "P3": ApprovalPriority.LOW,
                "P4": ApprovalPriority.LOW,
            }
            priority = priority_map.get(severity, ApprovalPriority.MEDIUM)

            approval = self.approval_manager.create_request(
                request_type="ticket_response",
                action=f"Generate response for {severity} ticket",
                context={
                    "ticket_id": state.ticket_id,
                    "severity": severity,
                    "proposed_actions": actions,
                    "policy_reason": decision.reason,
                    "risk_level": decision.risk_level,
                },
                requester=self.security_context,
                priority=priority,
                metadata={
                    "redacted_subject": state.redacted_subject,
                    "source": state.source,
                },
            )
            result["approval_id"] = approval.id

            # Trigger webhook for approval request (fire-and-forget, don't block on failure)
            try:
                await self.webhook_manager.trigger_event(
                    event_type=WebhookEventType.APPROVAL_REQUESTED,
                    tenant_id=self.security_context.tenant_id,
                    payload={
                        "approval_id": approval.id,
                        "ticket_id": state.ticket_id,
                        "severity": severity,
                        "priority": priority.value,
                        "reason": decision.reason,
                    },
                )
            except Exception as e:
                logger.error("webhook_trigger_failed", event="APPROVAL_REQUESTED", error=str(e))

        return result

    async def generate_response(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Generate customer response.

        Only runs if policy allows (no approval required).
        Validates output through guardrails before returning.
        """
        # Skip if approval required
        if state.approval_required:
            return {
                "response": None,
            }

        start_time = time.time()

        content = state.redacted_content
        severity = state.severity or "P3"
        actions = state.actions or []

        try:
            llm_response = await self.llm_gateway.generate_response(
                ticket_content=content,
                severity=severity,
                actions=actions,
            )

            response_text = llm_response.content

            # Run guardrails on LLM output before restoring PII
            guardrail_result = self.guardrail_pipeline.run(
                response_text,
                context={
                    "domain": "support",
                    "severity": severity,
                    "ticket_id": state.ticket_id,
                },
            )

            # Handle guardrail violations
            if guardrail_result.action_taken == GuardrailAction.BLOCK:
                return {
                    "response": None,
                    "errors": [
                        *state.errors,
                        f"Response blocked by guardrails: {[v.message for v in guardrail_result.violations]}",
                    ],
                    "guardrail_violations": [
                        {
                            "guardrail": v.guardrail_name,
                            "severity": v.severity.value,
                            "message": v.message,
                        }
                        for v in guardrail_result.violations
                    ],
                }

            # Use filtered content if guardrails applied redaction
            if guardrail_result.filtered_content:
                response_text = guardrail_result.filtered_content

            # Restore PII in response if token map exists
            if state.token_map:
                response_text = self.pii_redactor.restore(
                    response_text,
                    state.token_map,
                )

            latency_ms = int((time.time() - start_time) * 1000)

            return {
                "response": response_text,
                "total_latency_ms": state.total_latency_ms + latency_ms,
                "total_cost_estimate": state.total_cost_estimate + llm_response.cost_estimate,
                "llm_calls": state.llm_calls + 1,
                "guardrail_passed": guardrail_result.passed,
                "guardrail_violations": [
                    {
                        "guardrail": v.guardrail_name,
                        "severity": v.severity.value,
                        "message": v.message,
                    }
                    for v in guardrail_result.violations
                ]
                if guardrail_result.violations
                else None,
            }

        except Exception as e:
            return {
                "response": None,
                "errors": [*state.errors, f"Response generation error: {e!s}"],
            }

    async def write_audit_log(self, state: TicketState) -> dict[str, Any]:
        """
        Node: Write audit log entry and trigger completion webhook.

        Records all operation details for compliance.
        Triggers TICKET_TRIAGED webhook for external system integration.
        """
        audit_id = None
        completed_at = datetime.now(UTC)

        # Write audit log if database connection available
        if self.db_conn is not None:
            try:
                payload = AuditLogPayload(
                    ticket_id=state.ticket_id,
                    user_id=self.security_context.user_id,
                    tenant_id=self.security_context.tenant_id,
                    redacted_input=state.redacted_content,
                    token_map=state.token_map,
                    model_name=self.settings.model_name,
                    provider=self.settings.llm_provider,
                    severity=state.severity or "unknown",
                    actions=state.actions,
                    policy_decision={
                        "allowed": state.policy_allowed,
                        "requires_approval": state.policy_requires_approval,
                        "reason": state.policy_reason,
                        "risk_level": state.policy_risk_level,
                    },
                    final_response=state.response,
                    latency_ms=state.total_latency_ms,
                    cost_estimate=state.total_cost_estimate,
                    metadata={
                        "pii_found": state.pii_found,
                        "llm_calls": state.llm_calls,
                        "errors": state.errors,
                    },
                )

                audit_id = await self.audit_logger.write(self.db_conn, payload)

            except Exception as e:
                return {
                    "audit_log_id": None,
                    "completed_at": completed_at,
                    "errors": [*state.errors, f"Audit log error: {e!s}"],
                }

        # Trigger TICKET_TRIAGED webhook (fire-and-forget, don't block on failure)
        try:
            await self.webhook_manager.trigger_event(
                event_type=WebhookEventType.TICKET_TRIAGED,
                tenant_id=self.security_context.tenant_id,
                payload={
                    "ticket_id": state.ticket_id,
                    "severity": state.severity,
                    "actions": state.actions,
                    "approval_required": state.approval_required,
                    "approval_id": state.approval_id,
                    "response_generated": state.response is not None,
                    "latency_ms": state.total_latency_ms,
                    "errors": state.errors if state.errors else None,
                },
            )
        except Exception as e:
            logger.error("webhook_trigger_failed", event="TICKET_TRIAGED", error=str(e))

        # Trigger escalation webhook if high severity
        if state.severity in ("P0", "P1"):
            try:
                await self.webhook_manager.trigger_event(
                    event_type=WebhookEventType.TICKET_ESCALATED,
                    tenant_id=self.security_context.tenant_id,
                    payload={
                        "ticket_id": state.ticket_id,
                        "severity": state.severity,
                        "approval_required": state.approval_required,
                        "approval_id": state.approval_id,
                        "reason": state.policy_reason,
                    },
                )
            except Exception as e:
                logger.error("webhook_trigger_failed", event="TICKET_ESCALATED", error=str(e))

        return {
            "audit_log_id": audit_id,
            "completed_at": completed_at,
        }


def should_generate_response(state: TicketState | dict[str, Any]) -> str:
    """
    Conditional edge: Determine if response should be generated.

    Returns the next node name based on policy decision.

    Note: LangGraph passes state as dict, so we handle both types.
    """
    if isinstance(state, dict):
        approval_required = state.get("approval_required", False)
    else:
        approval_required = state.approval_required

    if approval_required:
        return "write_audit_log"
    return "generate_response"
