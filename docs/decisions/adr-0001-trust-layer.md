# ADR-0001: Trust Layer Architecture

## Status

Accepted

## Date

2026-01-01

## Context

Enterprise AI systems must balance capability with control. Large Language Models present unique challenges:

1. **Unpredictable Outputs**: LLMs can generate unexpected, harmful, or policy-violating content
2. **Data Exposure**: Prompts may contain sensitive data sent to third-party APIs
3. **Tool Abuse**: Agentic systems may execute actions beyond intended scope
4. **Audit Requirements**: Regulated industries require complete operation records
5. **Cost Control**: Unbounded LLM usage can lead to significant expenses

Traditional application security patterns assume trusted code with untrusted inputs. AI systems invert this: the code (model) is also untrusted.

## Decision

We implement a **Trust Layer** as the mandatory gateway between application logic and LLM interactions. The Trust Layer consists of:

### 1. PII Redactor

- Tokenizes sensitive data before LLM processing
- Supports restoration for approved responses
- Patterns: CPF, CNPJ, Cédula, email, phone

### 2. Policy Engine

- Evaluates all proposed actions before execution
- Implements RBAC for role-based permissions
- Enforces severity-based approval requirements
- Returns structured decisions with reasoning

### 3. Audit Logger

- Records every operation with full context
- Stores redacted inputs (never raw PII in logs)
- Captures policy decisions and outcomes
- Tracks latency and estimated costs

### 4. LLM Gateway

- Single point of control for LLM calls
- Accepts only pre-redacted prompts
- Supports mock mode for testing
- Abstracts provider differences

## Architecture

```
Application Request
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│                     TRUST LAYER                            │
│                                                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│  │   PII    │─▶│  Policy  │─▶│  Audit   │─▶│   LLM    │  │
│  │ Redactor │  │  Engine  │  │  Logger  │  │ Gateway  │  │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  │
│                                                            │
└───────────────────────────────────────────────────────────┘
        │
        ▼
   LLM Provider
```

## Consequences

### Positive

- **Security**: All LLM interactions are controlled and validated
- **Compliance**: Complete audit trail for regulatory requirements
- **Data Protection**: PII never reaches external LLMs
- **Control**: Policy engine prevents unauthorized actions
- **Observability**: Centralized logging and cost tracking
- **Testability**: Mock mode enables testing without LLM calls

### Negative

- **Latency**: Additional processing adds ~10-50ms overhead
- **Complexity**: More components to maintain and monitor
- **False Positives**: PII patterns may over-redact
- **Coupling**: All LLM operations depend on Trust Layer

### Neutral

- Requires team education on Trust Layer patterns
- Policy rules need ongoing maintenance
- Token maps add storage requirements

## Alternatives Considered

### 1. Direct LLM Integration

Calling LLM APIs directly from application code.

**Rejected because:**
- No centralized control
- Audit logging inconsistent
- PII protection ad-hoc
- Policy enforcement scattered

### 2. LLM Proxy Service

External service (e.g., commercial gateway) for LLM management.

**Rejected because:**
- Additional vendor dependency
- Less control over policy logic
- May not support all requirements
- Cost concerns

### 3. Prompt Engineering Only

Relying on system prompts for security.

**Rejected because:**
- Prompts can be bypassed
- No enforcement, only suggestion
- No audit trail
- No PII protection

## Implementation Notes

1. Trust Layer is implemented in `src/core/`
2. All agent nodes must use Trust Layer for LLM calls
3. Policy decisions are mandatory, not optional
4. Audit logging happens before response returned

## References

- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework)
- Internal Security Requirements Document
