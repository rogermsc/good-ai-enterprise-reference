# ADR-0002: Policy Engine Design

## Status

Accepted

## Date

2026-01-01

## Context

AI agents can recommend and execute actions with significant business impact. Without explicit controls:

1. Agents may take actions beyond their authorization
2. High-risk operations proceed without human review
3. Different users get inconsistent access to capabilities
4. There's no clear record of why actions were allowed/denied

We need a mechanism to evaluate proposed actions against organizational policies before execution.

## Decision

We implement a **Policy Engine** as a separate component that evaluates all proposed actions. The Policy Engine:

### Core Principles

1. **Explicit Approval**: No action executes without policy evaluation
2. **Separation of Concerns**: Policy logic separate from agent logic
3. **Structured Decisions**: Returns typed decisions with reasoning
4. **Fail Closed**: Uncertain cases require approval

### Decision Model

```python
@dataclass
class PolicyDecision:
    allowed: bool           # Can the action proceed?
    requires_approval: bool # Needs human review?
    reason: str            # Explanation for decision
    risk_level: str        # critical, high, medium, low
```

### Policy Rules

#### Severity-Based Rules

| Severity | Requires Approval | Rationale |
|----------|-------------------|-----------|
| P0 (Critical) | Yes | Production impact, data breach |
| P1 (High) | Yes | Significant customer impact |
| P2 (Medium) | No | Standard support issues |
| P3 (Low) | No | General questions |
| P4 (Info) | No | Informational requests |

#### RBAC Rules

| Role | Allowed Actions |
|------|-----------------|
| support_agent | read_ticket, classify, respond |
| support_lead | above + escalate, reassign |
| admin | above + access_customer_data |

#### Data Access Rules

| Data Type | Rule |
|-----------|------|
| Customer PII | Requires approval |
| Financial data | Requires approval + audit |
| Public data | Allowed |

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      POLICY ENGINE                               │
│                                                                   │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Severity Rules │  │   RBAC Rules    │  │ Data Access     │  │
│  │                 │  │                 │  │    Rules        │  │
│  │  P0/P1 → Approve│  │  Role → Actions │  │  PII → Approve  │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │                    │                    │            │
│           └────────────────────┼────────────────────┘            │
│                                ▼                                  │
│                    ┌─────────────────────┐                       │
│                    │  Decision Aggregator │                       │
│                    │  (Most restrictive   │                       │
│                    │   rule wins)         │                       │
│                    └─────────────────────┘                       │
│                                │                                  │
│                                ▼                                  │
│                    ┌─────────────────────┐                       │
│                    │   PolicyDecision    │                       │
│                    └─────────────────────┘                       │
└─────────────────────────────────────────────────────────────────┘
```

## Implementation

```python
def evaluate(
    ticket: Ticket,
    proposed_actions: list[str],
    user_context: SecurityContext
) -> PolicyDecision:
    """
    Evaluate proposed actions against policy rules.
    Returns most restrictive applicable decision.
    """
    decisions = []

    # Check severity rules
    decisions.append(check_severity_rules(ticket.severity))

    # Check RBAC rules
    decisions.append(check_rbac_rules(proposed_actions, user_context.roles))

    # Check data access rules
    decisions.append(check_data_access_rules(proposed_actions, ticket))

    # Return most restrictive
    return aggregate_decisions(decisions)
```

## Consequences

### Positive

- **Explicit Control**: Every action has clear authorization
- **Auditability**: Policy decisions logged with reasoning
- **Flexibility**: Rules can be updated without agent changes
- **Consistency**: Same rules apply across all agents
- **Safety**: High-risk actions require human review

### Negative

- **Latency**: Policy evaluation adds processing time
- **Maintenance**: Rules require ongoing updates
- **Complexity**: Another component to understand
- **False Negatives**: Overly strict rules block valid actions

### Neutral

- Policy rules need documentation
- Staff training on approval workflows
- Integration with approval systems (future)

## Alternatives Considered

### 1. Inline Policy Checks

Embedding policy logic in each agent node.

**Rejected because:**
- Duplicated logic across agents
- Inconsistent enforcement
- Harder to audit
- No central policy view

### 2. LLM-Based Policy

Using LLM to evaluate policies.

**Rejected because:**
- Non-deterministic decisions
- Slower evaluation
- Potential for prompt injection
- Audit complexity

### 3. External Policy Service

Using OPA, Cedar, or similar.

**Considered for future:**
- More sophisticated rule language
- Better policy management UI
- Adds operational complexity
- Overkill for MVP

## Future Enhancements

1. **Policy as Code**: Define rules in configuration files
2. **Approval Workflows**: Integration with ticketing systems
3. **Dynamic Rules**: Adjust based on time, load, risk scores
4. **Policy Analytics**: Track rule hit rates, false positives
5. **External Engines**: Migrate to OPA/Cedar for complex policies

## References

- [Open Policy Agent (OPA)](https://www.openpolicyagent.org/)
- [AWS Cedar](https://www.cedarpolicy.com/)
- [NIST Access Control Guidelines](https://csrc.nist.gov/publications/detail/sp/800-162/final)
