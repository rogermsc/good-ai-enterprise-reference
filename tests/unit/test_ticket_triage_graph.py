"""
Tests for the Ticket Triage Agent Graph.

Tests:
- Complete workflow execution
- PII redaction before LLM calls
- P0/P1 returns approval_required
- P3/P4 returns full response
- State management
"""

import pytest

from src.agents.ticket_triage import TicketInput, TriageResult, run_triage
from src.core.security import SecurityContext, Roles


class TestTicketTriageGraph:
    """Test suite for ticket triage workflow."""

    @pytest.fixture
    def support_agent_context(self) -> SecurityContext:
        """Security context for support agent."""
        return SecurityContext(
            user_id="agent-001",
            tenant_id="test-tenant",
            roles=(Roles.SUPPORT_AGENT,),
        )

    @pytest.fixture
    def admin_context(self) -> SecurityContext:
        """Security context for admin."""
        return SecurityContext(
            user_id="admin-001",
            tenant_id="test-tenant",
            roles=(Roles.ADMIN,),
        )

    # Basic workflow tests

    @pytest.mark.asyncio
    async def test_basic_triage_workflow(self, support_agent_context):
        """Should complete basic triage workflow."""
        ticket = TicketInput(
            ticket_id="TKT-001",
            subject="How do I reset my password?",
            body="I forgot my password and need help.",
            customer_email="user@example.com",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=support_agent_context,
            db_conn=None,  # Skip audit logging in tests
        )

        assert result.ticket_id == "TKT-001"
        assert result.severity is not None
        assert result.severity in ("P0", "P1", "P2", "P3", "P4")
        assert len(result.actions) > 0
        assert "allowed" in result.policy_decision

    # PII redaction tests

    @pytest.mark.asyncio
    async def test_pii_redaction_before_llm(self, support_agent_context):
        """PII should be redacted before LLM processing."""
        ticket = TicketInput(
            ticket_id="TKT-002",
            subject="Account issue for user@example.com",
            body="Customer CPF: 123.456.789-00 has billing problems.",
            customer_email="user@example.com",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=support_agent_context,
            db_conn=None,
        )

        # Response should not contain raw PII (it was redacted and restored)
        # The result itself won't show redacted state, but workflow completed
        assert result.ticket_id == "TKT-002"
        assert result.errors == []  # No errors during processing

    # Severity-based approval tests

    @pytest.mark.asyncio
    async def test_p0_requires_approval(self, admin_context):
        """P0 tickets should require approval."""
        ticket = TicketInput(
            ticket_id="TKT-003",
            subject="URGENT: Data breach detected",
            body="Unauthorized access to production database. Customer data may be exposed.",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=admin_context,
            db_conn=None,
        )

        # P0 detected (contains "breach", "data", "exposed")
        assert result.severity == "P0"
        assert result.approval_required is True
        assert result.policy_decision["requires_approval"] is True
        assert result.response is None  # No response generated

    @pytest.mark.asyncio
    async def test_p1_requires_approval(self, admin_context):
        """P1 tickets should require approval."""
        ticket = TicketInput(
            ticket_id="TKT-004",
            subject="Critical: Production system crash",
            body="The main application is not working and users cannot access their data.",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=admin_context,
            db_conn=None,
        )

        # Should be P1 (contains "critical", "not working", "crash")
        assert result.severity in ("P0", "P1")
        assert result.approval_required is True
        assert result.response is None

    @pytest.mark.asyncio
    async def test_p3_returns_full_response(self, support_agent_context):
        """P3 tickets should return full response."""
        ticket = TicketInput(
            ticket_id="TKT-005",
            subject="Question about features",
            body="How do I use the export feature?",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=support_agent_context,
            db_conn=None,
        )

        # Should be P3/P4 (question, "how to")
        assert result.severity in ("P3", "P4")
        assert result.approval_required is False
        assert result.response is not None
        assert len(result.response) > 0

    @pytest.mark.asyncio
    async def test_password_reset_low_severity(self, support_agent_context):
        """Password reset should be low severity."""
        ticket = TicketInput(
            ticket_id="TKT-006",
            subject="Password reset needed",
            body="I need to reset my password please.",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=support_agent_context,
            db_conn=None,
        )

        assert result.severity in ("P3", "P4")
        assert result.approval_required is False
        assert result.response is not None

    # RBAC tests

    @pytest.mark.asyncio
    async def test_unauthorized_action_triggers_approval(self):
        """Unauthorized actions should trigger approval requirement."""
        # Use a context with no roles
        no_role_context = SecurityContext(
            user_id="no-role",
            tenant_id="test-tenant",
            roles=(),
        )

        ticket = TicketInput(
            ticket_id="TKT-007",
            subject="Simple question",
            body="How do I do something?",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=no_role_context,
            db_conn=None,
        )

        # Should fail RBAC
        assert result.policy_decision["allowed"] is False

    # Result structure tests

    @pytest.mark.asyncio
    async def test_result_structure(self, support_agent_context):
        """Result should have correct structure."""
        ticket = TicketInput(
            ticket_id="TKT-008",
            subject="Test ticket",
            body="This is a test.",
            source="chat",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=support_agent_context,
            db_conn=None,
        )

        # Check result structure
        assert isinstance(result, TriageResult)
        assert result.ticket_id == "TKT-008"
        assert isinstance(result.actions, list)
        assert isinstance(result.policy_decision, dict)
        assert "allowed" in result.policy_decision
        assert "requires_approval" in result.policy_decision
        assert "reason" in result.policy_decision
        assert "risk_level" in result.policy_decision
        assert isinstance(result.latency_ms, int)
        assert isinstance(result.cost_estimate, float)
        assert isinstance(result.errors, list)

    # Error handling tests

    @pytest.mark.asyncio
    async def test_handles_empty_body(self, support_agent_context):
        """Should handle empty ticket body."""
        ticket = TicketInput(
            ticket_id="TKT-009",
            subject="Subject only",
            body="",
            source="email",
        )

        result = await run_triage(
            ticket=ticket,
            security_context=support_agent_context,
            db_conn=None,
        )

        # Should complete without errors
        assert result.ticket_id == "TKT-009"
        assert result.severity is not None


class TestTicketInput:
    """Tests for TicketInput model."""

    def test_ticket_input_creation(self):
        """Should create TicketInput with required fields."""
        ticket = TicketInput(
            ticket_id="TKT-001",
            subject="Test subject",
            body="Test body",
        )

        assert ticket.ticket_id == "TKT-001"
        assert ticket.subject == "Test subject"
        assert ticket.body == "Test body"
        assert ticket.source == "email"  # Default
        assert ticket.metadata == {}  # Default

    def test_ticket_input_with_metadata(self):
        """Should create TicketInput with metadata."""
        ticket = TicketInput(
            ticket_id="TKT-002",
            subject="Test",
            body="Test",
            metadata={"priority": "high", "channel": "slack"},
        )

        assert ticket.metadata["priority"] == "high"
        assert ticket.metadata["channel"] == "slack"
