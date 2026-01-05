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
from src.core.audit_log import AuditLogger, AuditLogPayload
from src.core.config import get_settings
from src.core.guardrails import GuardrailAction, GuardrailPipeline
from src.core.llm_gateway import LLMGateway
from src.core.pii_redaction import PIIRedactor
from src.core.policy_engine import PolicyEngine
from src.core.security import SecurityContext


class TriageNodes:
    """
    Node implementations for ticket triage workflow.

    Each method is a node that can be used in a LangGraph graph.
    """

    def __init__(
        self,
        security_context: SecurityContext,
        db_conn: asyncpg.Connection | None = None,
    ):
        """
        Initialize nodes with dependencies.

        Args:
            security_context: User authentication context
            db_conn: Optional database connection for audit logging
        """
        self.security_context = security_context
        self.db_conn = db_conn
        self.settings = get_settings()
        self.pii_redactor = PIIRedactor()
        self.policy_engine = PolicyEngine()
        self.llm_gateway = LLMGateway(self.settings)
        self.audit_logger = AuditLogger()
        self.guardrail_pipeline = GuardrailPipeline()

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
        """
        severity = state.severity or "P3"
        actions = state.actions or []

        decision = self.policy_engine.evaluate(
            severity=severity,
            proposed_actions=actions,
            user_context=self.security_context,
        )

        return {
            "policy_allowed": decision.allowed,
            "policy_requires_approval": decision.requires_approval,
            "policy_reason": decision.reason,
            "policy_risk_level": decision.risk_level,
            "approval_required": decision.requires_approval,
        }

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
        Node: Write audit log entry.

        Records all operation details for compliance.
        """
        if self.db_conn is None:
            # Skip audit logging if no connection
            return {
                "audit_log_id": None,
                "completed_at": datetime.now(UTC),
            }

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

            return {
                "audit_log_id": audit_id,
                "completed_at": datetime.now(UTC),
            }

        except Exception as e:
            return {
                "audit_log_id": None,
                "completed_at": datetime.now(UTC),
                "errors": [*state.errors, f"Audit log error: {e!s}"],
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
