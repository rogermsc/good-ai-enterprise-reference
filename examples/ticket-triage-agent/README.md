# Ticket Triage Agent Examples

This directory contains example payloads for testing the Ticket Triage Agent.

## Overview

The Ticket Triage Agent demonstrates:
1. **PII Redaction** — Sensitive data tokenized before LLM processing
2. **Severity Classification** — P0-P4 based on content analysis
3. **Policy Enforcement** — RBAC and severity-based approval workflows
4. **Audit Logging** — Complete operation records

## Example Payloads

### P0 - Critical Severity (Data Leak)

File: `payloads/p0_data_leak.json`

This simulates a data breach scenario. Expected behavior:
- Severity: P0
- Approval Required: Yes
- Response: Not generated (pending approval)
- PII: CPF redacted

### P2 - Medium Severity (Password Reset)

File: `payloads/p2_password_reset.json`

This simulates a routine password reset request. Expected behavior:
- Severity: P3 (classified as question/help)
- Approval Required: No
- Response: Generated
- PII: Email redacted

### P3 - Low Severity (General Question)

File: `payloads/p3_general_question.json`

This simulates a general product question. Expected behavior:
- Severity: P3/P4
- Approval Required: No
- Response: Generated
- PII: None

## Running Examples

### Prerequisites

Start the services:
```bash
docker-compose -f infrastructure/docker-compose.yml up -d
```

### Using curl.sh

```bash
# Run all examples
./examples/ticket-triage-agent/curl.sh

# Or run individually
./examples/ticket-triage-agent/curl.sh p0
./examples/ticket-triage-agent/curl.sh p2
./examples/ticket-triage-agent/curl.sh p3
```

### Manual Testing

```bash
# P0 - Data Leak (requires approval)
curl -X POST http://localhost:8000/tickets/triage \
  -H "Content-Type: application/json" \
  -H "X-User-Id: agent-001" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Roles: support_agent" \
  -d @examples/ticket-triage-agent/payloads/p0_data_leak.json

# P2 - Password Reset
curl -X POST http://localhost:8000/tickets/triage \
  -H "Content-Type: application/json" \
  -H "X-User-Id: agent-001" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Roles: support_agent" \
  -d @examples/ticket-triage-agent/payloads/p2_password_reset.json

# P3 - General Question
curl -X POST http://localhost:8000/tickets/triage \
  -H "Content-Type: application/json" \
  -H "X-User-Id: agent-001" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Roles: support_agent" \
  -d @examples/ticket-triage-agent/payloads/p3_general_question.json
```

## Understanding the Response

### Approved (No Approval Required)

```json
{
  "ticket_id": "TKT-2026-003",
  "severity": "P3",
  "actions": ["classify", "respond"],
  "policy_decision": {
    "allowed": true,
    "requires_approval": false,
    "reason": "All policy checks passed",
    "risk_level": "low"
  },
  "response": "Thank you for contacting us...",
  "approval_required": false,
  "audit_log_id": "..."
}
```

### Pending Approval (P0/P1)

```json
{
  "ticket_id": "TKT-2026-001",
  "severity": "P0",
  "actions": ["escalate_to_security", "create_incident", "page_oncall"],
  "policy_decision": {
    "allowed": true,
    "requires_approval": true,
    "reason": "P0 (Critical) severity requires manager approval",
    "risk_level": "critical"
  },
  "response": null,
  "approval_required": true,
  "audit_log_id": "..."
}
```

## Authentication Headers

All requests require:

| Header | Description | Example |
|--------|-------------|---------|
| `X-User-Id` | User identifier | `agent-001` |
| `X-Tenant-Id` | Tenant/org identifier | `acme-corp` |
| `X-Roles` | Comma-separated roles | `support_agent,support_lead` |

### Available Roles

- `support_agent` — Basic ticket operations
- `support_lead` — Escalation capabilities
- `admin` — Full access
- `security` — Security operations

## Verifying PII Redaction

When you submit a ticket with PII (CPF, email, phone), the system:

1. **Redacts** the PII before sending to LLM
2. **Stores** the token map in the audit log
3. **Restores** PII in the final response (if generated)

To verify, check the audit log:
```sql
SELECT
    ticket_id,
    redacted_input,
    token_map
FROM audit_logs
WHERE ticket_id = 'TKT-2026-001';
```

The `redacted_input` will contain tokens like `[PII_CPF_1]` instead of actual CPF numbers.
