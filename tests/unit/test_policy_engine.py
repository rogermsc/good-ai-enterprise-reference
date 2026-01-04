"""
Tests for the Policy Engine.

Tests:
- Severity-based approval requirements (P0/P1)
- RBAC enforcement
- Action-based approval requirements
- Decision aggregation
"""


from src.core.policy_engine import Actions, PolicyDecision, PolicyEngine, RiskLevel
from src.core.security import Roles, SecurityContext


class TestPolicyEngine:
    """Test suite for PolicyEngine."""

    def setup_method(self):
        """Set up test fixtures."""
        self.engine = PolicyEngine()

    # Severity-based tests

    def test_p0_requires_approval(self):
        """P0 (Critical) severity should require approval."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.ADMIN,),  # Even admin needs approval for P0
        )

        decision = self.engine.evaluate(
            severity="P0",
            proposed_actions=[Actions.CLASSIFY, Actions.RESPOND],
            user_context=context,
        )

        assert decision.allowed is True
        assert decision.requires_approval is True
        assert decision.risk_level == RiskLevel.CRITICAL.value
        assert "P0" in decision.reason

    def test_p1_requires_approval(self):
        """P1 (High) severity should require approval."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT,),
        )

        decision = self.engine.evaluate(
            severity="P1",
            proposed_actions=[Actions.CLASSIFY],
            user_context=context,
        )

        assert decision.allowed is True
        assert decision.requires_approval is True
        assert decision.risk_level == RiskLevel.HIGH.value

    def test_p2_no_approval_required(self):
        """P2 (Medium) severity should not require approval."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT,),
        )

        decision = self.engine.evaluate(
            severity="P2",
            proposed_actions=[Actions.CLASSIFY, Actions.RESPOND],
            user_context=context,
        )

        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_p3_no_approval_required(self):
        """P3 (Low) severity should not require approval."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[Actions.CLASSIFY, Actions.RESPOND],
            user_context=context,
        )

        assert decision.allowed is True
        assert decision.requires_approval is False
        assert decision.risk_level == RiskLevel.LOW.value

    # RBAC tests

    def test_support_agent_allowed_actions(self):
        """Support agent should be allowed basic actions."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[
                Actions.READ_TICKET,
                Actions.CLASSIFY,
                Actions.RESPOND,
                Actions.NOTIFY_CUSTOMER,
            ],
            user_context=context,
        )

        assert decision.allowed is True

    def test_support_agent_denied_escalation(self):
        """Support agent should be denied escalation actions."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[Actions.ESCALATE_TO_ENGINEERING],
            user_context=context,
        )

        # Should not be allowed - action not permitted for role
        assert decision.allowed is False
        assert decision.requires_approval is True
        assert "Unauthorized" in decision.reason

    def test_support_lead_allowed_escalation(self):
        """Support lead should be allowed escalation."""
        context = SecurityContext(
            user_id="lead-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_LEAD,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[Actions.ESCALATE_TO_ENGINEERING],
            user_context=context,
        )

        assert decision.allowed is True

    def test_admin_allowed_all_actions(self):
        """Admin should be allowed most actions."""
        context = SecurityContext(
            user_id="admin-1",
            tenant_id="acme",
            roles=(Roles.ADMIN,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[
                Actions.READ_TICKET,
                Actions.CLASSIFY,
                Actions.RESPOND,
                Actions.ESCALATE_TO_ENGINEERING,
                Actions.ACCESS_CUSTOMER_DATA,
                Actions.CREATE_INCIDENT,
            ],
            user_context=context,
        )

        assert decision.allowed is True

    def test_multiple_roles_combined_permissions(self):
        """User with multiple roles should have combined permissions."""
        context = SecurityContext(
            user_id="multi-role",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT, Roles.SECURITY),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[
                Actions.RESPOND,  # From support_agent
                Actions.ESCALATE_TO_SECURITY,  # From security
            ],
            user_context=context,
        )

        assert decision.allowed is True

    # Action-based approval tests

    def test_delete_data_requires_approval(self):
        """Delete customer data should always require approval."""
        context = SecurityContext(
            user_id="admin-1",
            tenant_id="acme",
            roles=(Roles.ADMIN,),
        )

        decision = self.engine.evaluate(
            severity="P4",  # Low severity
            proposed_actions=[Actions.DELETE_CUSTOMER_DATA],
            user_context=context,
        )

        # Allowed but requires approval
        # Note: Admin doesn't have DELETE_CUSTOMER_DATA in permissions
        # so this should fail RBAC
        assert decision.requires_approval is True

    def test_page_oncall_requires_approval(self):
        """Paging on-call should require approval."""
        context = SecurityContext(
            user_id="admin-1",
            tenant_id="acme",
            roles=(Roles.ADMIN,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[Actions.PAGE_ONCALL],
            user_context=context,
        )

        assert decision.requires_approval is True

    # Edge cases

    def test_empty_actions_allowed(self):
        """Empty action list should be allowed."""
        context = SecurityContext(
            user_id="agent-1",
            tenant_id="acme",
            roles=(Roles.SUPPORT_AGENT,),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[],
            user_context=context,
        )

        assert decision.allowed is True
        assert decision.requires_approval is False

    def test_no_roles_denied(self):
        """User with no roles should be denied actions."""
        context = SecurityContext(
            user_id="no-role",
            tenant_id="acme",
            roles=(),
        )

        decision = self.engine.evaluate(
            severity="P3",
            proposed_actions=[Actions.RESPOND],
            user_context=context,
        )

        assert decision.allowed is False

    def test_policy_decision_to_dict(self):
        """PolicyDecision should serialize to dict correctly."""
        decision = PolicyDecision(
            allowed=True,
            requires_approval=True,
            reason="Test reason",
            risk_level="high",
        )

        result = decision.to_dict()

        assert result["allowed"] is True
        assert result["requires_approval"] is True
        assert result["reason"] == "Test reason"
        assert result["risk_level"] == "high"
