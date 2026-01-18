"""
Policy Engine for action authorization.

The Policy Engine evaluates proposed actions against organizational policies,
enforcing:
- Severity-based approval requirements (P0/P1 require approval)
- Role-based access control (RBAC)
- Data access restrictions

All LLM-suggested actions must pass policy evaluation before execution.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum

from src.core.security import Roles, SecurityContext


class Severity(str, Enum):
    """Ticket severity levels."""

    P0 = "P0"  # Critical - Production down, data breach
    P1 = "P1"  # High - Major feature broken, security issue
    P2 = "P2"  # Medium - Feature degraded, workaround available
    P3 = "P3"  # Low - Minor issue, cosmetic
    P4 = "P4"  # Info - Question, feature request


class RiskLevel(str, Enum):
    """Risk assessment levels."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class PolicyDecision:
    """
    Result of policy evaluation.

    Attributes:
        allowed: Whether the action is permitted
        requires_approval: Whether human approval is needed
        reason: Explanation for the decision
        risk_level: Assessed risk level
    """

    allowed: bool
    requires_approval: bool
    reason: str
    risk_level: str

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "risk_level": self.risk_level,
        }


# Action definitions
class Actions:
    """Standard action identifiers."""

    # Basic actions
    READ_TICKET = "read_ticket"
    CLASSIFY = "classify"
    RESPOND = "respond"

    # Escalation actions
    ESCALATE_TO_ENGINEERING = "escalate_to_engineering"
    ESCALATE_TO_SECURITY = "escalate_to_security"
    ESCALATE_TO_MANAGEMENT = "escalate_to_management"

    # Customer actions
    NOTIFY_CUSTOMER = "notify_customer"
    REFUND_CUSTOMER = "refund_customer"

    # Data actions
    ACCESS_CUSTOMER_DATA = "access_customer_data"
    MODIFY_CUSTOMER_DATA = "modify_customer_data"
    DELETE_CUSTOMER_DATA = "delete_customer_data"

    # Incident actions
    CREATE_INCIDENT = "create_incident"
    PAGE_ONCALL = "page_oncall"


# Role-based action permissions
ROLE_PERMISSIONS: dict[str, set[str]] = {
    Roles.SUPPORT_AGENT: {
        Actions.READ_TICKET,
        Actions.CLASSIFY,
        Actions.RESPOND,
        Actions.NOTIFY_CUSTOMER,
    },
    Roles.SUPPORT_LEAD: {
        Actions.READ_TICKET,
        Actions.CLASSIFY,
        Actions.RESPOND,
        Actions.NOTIFY_CUSTOMER,
        Actions.ESCALATE_TO_ENGINEERING,
        Actions.ESCALATE_TO_MANAGEMENT,
        Actions.REFUND_CUSTOMER,
    },
    Roles.ADMIN: {
        Actions.READ_TICKET,
        Actions.CLASSIFY,
        Actions.RESPOND,
        Actions.NOTIFY_CUSTOMER,
        Actions.ESCALATE_TO_ENGINEERING,
        Actions.ESCALATE_TO_SECURITY,
        Actions.ESCALATE_TO_MANAGEMENT,
        Actions.REFUND_CUSTOMER,
        Actions.ACCESS_CUSTOMER_DATA,
        Actions.MODIFY_CUSTOMER_DATA,
        Actions.CREATE_INCIDENT,
        Actions.PAGE_ONCALL,
    },
    Roles.SECURITY: {
        Actions.READ_TICKET,
        Actions.CLASSIFY,
        Actions.ESCALATE_TO_SECURITY,
        Actions.ACCESS_CUSTOMER_DATA,
        Actions.CREATE_INCIDENT,
        Actions.PAGE_ONCALL,
    },
}

# Actions that always require approval
APPROVAL_REQUIRED_ACTIONS: set[str] = {
    Actions.DELETE_CUSTOMER_DATA,
    Actions.MODIFY_CUSTOMER_DATA,
    Actions.REFUND_CUSTOMER,
    Actions.PAGE_ONCALL,
}


class PolicyEngine:
    """
    Evaluates proposed actions against organizational policies.

    The engine applies multiple rule types:
    1. Severity rules - P0/P1 tickets require approval
    2. RBAC rules - Actions must match user roles
    3. Data access rules - Sensitive data requires approval

    Example:
        engine = PolicyEngine()
        decision = engine.evaluate(
            severity="P0",
            proposed_actions=["escalate_to_engineering", "notify_customer"],
            user_context=SecurityContext(user_id="agent-1", tenant_id="acme", roles=["support_agent"]),
        )
    """

    def __init__(
        self,
        role_permissions: dict[str, set[str]] | None = None,
        approval_actions: set[str] | None = None,
    ):
        """
        Initialize policy engine.

        Args:
            role_permissions: Custom role-to-action mappings
            approval_actions: Custom set of actions requiring approval
        """
        self.role_permissions = role_permissions or ROLE_PERMISSIONS
        self.approval_actions = approval_actions or APPROVAL_REQUIRED_ACTIONS

    def evaluate(
        self,
        severity: str,
        proposed_actions: Sequence[str],
        user_context: SecurityContext,
    ) -> PolicyDecision:
        """
        Evaluate proposed actions against all policy rules.

        Args:
            severity: Ticket severity (P0-P4)
            proposed_actions: List of actions to evaluate
            user_context: User's security context

        Returns:
            PolicyDecision with authorization result
        """
        # Collect all applicable rules
        decisions: list[PolicyDecision] = []

        # Rule 1: Severity-based approval
        severity_decision = self._check_severity_rules(severity)
        decisions.append(severity_decision)

        # Rule 2: RBAC check
        rbac_decision = self._check_rbac_rules(proposed_actions, user_context)
        decisions.append(rbac_decision)

        # Rule 3: Action-specific approval requirements
        action_decision = self._check_action_rules(proposed_actions)
        decisions.append(action_decision)

        # Aggregate: most restrictive wins
        return self._aggregate_decisions(decisions)

    def _check_severity_rules(self, severity: str) -> PolicyDecision:
        """Check severity-based approval requirements."""
        if severity in (Severity.P0.value, Severity.P0):
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="P0 (Critical) severity requires manager approval before customer response",
                risk_level=RiskLevel.CRITICAL.value,
            )

        if severity in (Severity.P1.value, Severity.P1):
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason="P1 (High) severity requires review before customer response",
                risk_level=RiskLevel.HIGH.value,
            )

        if severity in (Severity.P2.value, Severity.P2):
            return PolicyDecision(
                allowed=True,
                requires_approval=False,
                reason="P2 (Medium) severity - standard processing",
                risk_level=RiskLevel.MEDIUM.value,
            )

        # P3, P4, or unknown
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason=f"{severity} severity - standard processing",
            risk_level=RiskLevel.LOW.value,
        )

    def _check_rbac_rules(
        self,
        proposed_actions: Sequence[str],
        user_context: SecurityContext,
    ) -> PolicyDecision:
        """Check role-based access control."""
        # Collect all allowed actions for user's roles
        allowed_actions: set[str] = set()
        for role in user_context.roles:
            if role in self.role_permissions:
                allowed_actions.update(self.role_permissions[role])

        # Check for unauthorized actions
        unauthorized = [
            action for action in proposed_actions
            if action not in allowed_actions
        ]

        if unauthorized:
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                reason=f"Unauthorized actions for role(s) {user_context.roles}: {unauthorized}",
                risk_level=RiskLevel.HIGH.value,
            )

        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason="All actions authorized for user role(s)",
            risk_level=RiskLevel.LOW.value,
        )

    def _check_action_rules(
        self,
        proposed_actions: Sequence[str],
    ) -> PolicyDecision:
        """Check action-specific approval requirements."""
        approval_needed = [
            action for action in proposed_actions
            if action in self.approval_actions
        ]

        if approval_needed:
            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason=f"Actions requiring approval: {approval_needed}",
                risk_level=RiskLevel.HIGH.value,
            )

        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason="No special approval requirements",
            risk_level=RiskLevel.LOW.value,
        )

    def _aggregate_decisions(
        self,
        decisions: list[PolicyDecision],
    ) -> PolicyDecision:
        """Aggregate multiple decisions, most restrictive wins."""
        # If any decision denies, deny overall
        denied = [d for d in decisions if not d.allowed]
        if denied:
            # Return the first denial reason
            return denied[0]

        # If any decision requires approval, require approval
        approval_required = [d for d in decisions if d.requires_approval]
        if approval_required:
            # Combine reasons and take highest risk
            reasons = [d.reason for d in approval_required]
            risk_order = [
                RiskLevel.CRITICAL.value,
                RiskLevel.HIGH.value,
                RiskLevel.MEDIUM.value,
                RiskLevel.LOW.value,
            ]
            highest_risk = RiskLevel.LOW.value
            for d in approval_required:
                if risk_order.index(d.risk_level) < risk_order.index(highest_risk):
                    highest_risk = d.risk_level

            return PolicyDecision(
                allowed=True,
                requires_approval=True,
                reason=" | ".join(reasons),
                risk_level=highest_risk,
            )

        # All allowed, no approval needed
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            reason="All policy checks passed",
            risk_level=RiskLevel.LOW.value,
        )
