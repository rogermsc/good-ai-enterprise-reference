# Audit Logging

## Overview

The audit logging system provides an immutable record of all AI operations for compliance, debugging, and security analysis.

## What Gets Logged

Every ticket triage operation records:

| Field | Type | Description |
|-------|------|-------------|
| `audit_id` | UUID | Unique identifier for this log entry |
| `ticket_id` | String | Source ticket identifier |
| `user_id` | String | Authenticated user performing action |
| `tenant_id` | String | Tenant/organization identifier |
| `redacted_input` | Text | Ticket content with PII tokenized |
| `token_map` | JSONB | Mapping of tokens to original PII |
| `model_name` | String | LLM model used (e.g., gpt-4) |
| `provider` | String | LLM provider (e.g., openai) |
| `severity` | String | Classified severity (P0-P4) |
| `actions` | JSONB | Recommended actions |
| `policy_decision` | JSONB | Full policy engine response |
| `final_response` | Text | Generated customer response (redacted) |
| `latency_ms` | Integer | Total processing time |
| `cost_estimate` | Decimal | Estimated API cost |
| `created_at` | Timestamp | When operation occurred |

## Log Entry Example

```json
{
  "audit_id": "550e8400-e29b-41d4-a716-446655440000",
  "ticket_id": "TKT-2026-001",
  "user_id": "agent-001",
  "tenant_id": "acme-corp",
  "redacted_input": "Customer [PII_EMAIL_1] reports database outage. CPF: [PII_CPF_2]",
  "token_map": {
    "[PII_EMAIL_1]": "encrypted:abc123...",
    "[PII_CPF_2]": "encrypted:def456..."
  },
  "model_name": "gpt-4",
  "provider": "openai",
  "severity": "P0",
  "actions": [
    "escalate_to_engineering",
    "notify_customer",
    "create_incident"
  ],
  "policy_decision": {
    "allowed": true,
    "requires_approval": true,
    "reason": "P0 severity requires manager approval",
    "risk_level": "critical"
  },
  "final_response": null,
  "latency_ms": 1250,
  "cost_estimate": 0.0045,
  "created_at": "2026-01-15T10:30:00Z"
}
```

## Storage Schema

```sql
CREATE TABLE audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    redacted_input TEXT NOT NULL,
    token_map JSONB,
    model_name VARCHAR(50),
    provider VARCHAR(50),
    severity VARCHAR(10),
    actions JSONB,
    policy_decision JSONB NOT NULL,
    final_response TEXT,
    latency_ms INTEGER,
    cost_estimate DECIMAL(10, 6),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    -- Indexes for common queries
    INDEX idx_audit_logs_ticket_id (ticket_id),
    INDEX idx_audit_logs_tenant_id (tenant_id),
    INDEX idx_audit_logs_created_at (created_at),
    INDEX idx_audit_logs_severity (severity)
);
```

## Compliance Features

### Immutability

- Logs are append-only
- No UPDATE or DELETE operations permitted
- Production: use database-level restrictions

### Encryption

- `token_map` should be encrypted at rest
- Production: use column-level encryption or KMS
- Reference implementation stores plaintext for demo

### Retention

- Define retention policy per regulatory requirement
- LGPD: retain for legal compliance period
- Implement automated archival/deletion

### Access Control

- Audit log access restricted to compliance roles
- All access to logs is itself logged
- Production: implement row-level security

## Query Patterns

### By Ticket

```sql
SELECT * FROM audit_logs
WHERE ticket_id = 'TKT-2026-001'
ORDER BY created_at DESC;
```

### By Tenant (Last 7 Days)

```sql
SELECT * FROM audit_logs
WHERE tenant_id = 'acme-corp'
  AND created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;
```

### High Severity Operations

```sql
SELECT * FROM audit_logs
WHERE severity IN ('P0', 'P1')
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

### Policy Denials

```sql
SELECT * FROM audit_logs
WHERE policy_decision->>'allowed' = 'false'
ORDER BY created_at DESC;
```

### Cost Analysis

```sql
SELECT
    tenant_id,
    DATE(created_at) as date,
    SUM(cost_estimate) as total_cost,
    COUNT(*) as operations
FROM audit_logs
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY tenant_id, DATE(created_at)
ORDER BY date DESC, total_cost DESC;
```

## Integration Points

### Audit Log Writer

```python
from src.core.audit_log import write_audit_log

audit_id = await write_audit_log(
    conn=db_connection,
    payload=AuditLogPayload(
        ticket_id=state.ticket_id,
        user_id=context.user_id,
        tenant_id=context.tenant_id,
        redacted_input=state.redacted_content,
        token_map=state.token_map,
        model_name=config.model_name,
        provider=config.llm_provider,
        severity=state.severity,
        actions=state.actions,
        policy_decision=state.policy_decision,
        final_response=state.response,
        latency_ms=elapsed_ms,
        cost_estimate=estimate_cost(state),
    )
)
```

### Audit Log Reader (Production Extension)

```python
# Example: Compliance dashboard query
async def get_tenant_audit_summary(
    tenant_id: str,
    start_date: datetime,
    end_date: datetime
) -> AuditSummary:
    """Get audit summary for compliance reporting."""
    ...
```

## Production Recommendations

1. **Encryption**
   - Encrypt token_map with tenant-specific keys
   - Use cloud KMS for key management
   - Implement key rotation

2. **Partitioning**
   - Partition by created_at (monthly)
   - Improves query performance
   - Simplifies retention management

3. **Replication**
   - Replicate to read replicas for queries
   - Consider cross-region replication for DR

4. **Monitoring**
   - Alert on high policy denial rates
   - Monitor log write latency
   - Track storage growth

5. **Export**
   - Implement compliance report generation
   - Support CSV/JSON export
   - Integrate with SIEM systems
