# Data Flow

## Overview

This document describes the complete data flow for ticket triage operations, from initial request through response delivery.

## Request Lifecycle

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CLIENT REQUEST                                 │
│  POST /tickets/triage                                                    │
│  Headers: X-User-Id, X-Tenant-Id, X-Roles                               │
│  Body: { ticket_id, subject, body, customer_email, source }             │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        1. AUTHENTICATION                                 │
│  • Extract auth context from headers                                     │
│  • Validate required fields present                                      │
│  • Create SecurityContext(user_id, tenant_id, roles)                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        2. TICKET INGESTION                               │
│  • Parse ticket payload                                                  │
│  • Create TicketState with raw content                                  │
│  • Initialize workflow metadata                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        3. PII REDACTION                                  │
│  • Scan for CPF patterns: XXX.XXX.XXX-XX                                │
│  • Scan for CNPJ patterns: XX.XXX.XXX/XXXX-XX                           │
│  • Scan for email addresses                                              │
│  • Scan for phone numbers                                                │
│  • Replace with tokens: [PII_CPF_1], [PII_EMAIL_2], etc.                │
│  • Store token_map: { "[PII_CPF_1]": "123.456.789-00" }                 │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     4. SEVERITY CLASSIFICATION                           │
│  • Send REDACTED ticket to LLM Gateway                                  │
│  • Prompt: "Classify severity: P0-P4"                                   │
│  • LLM returns severity classification                                   │
│  • Parse and validate response                                           │
│  • Mock mode: keyword-based classification                               │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     5. ACTION RECOMMENDATION                             │
│  • Send REDACTED ticket + severity to LLM                               │
│  • Prompt: "Recommend actions for this ticket"                          │
│  • LLM returns action suggestions                                        │
│  • Parse into structured action list                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        6. POLICY CHECK                                   │
│  • Evaluate: policy_engine.evaluate(                                    │
│      ticket=state.ticket,                                                │
│      proposed_actions=state.actions,                                     │
│      user_context=security_context                                       │
│    )                                                                     │
│  • Check severity rules: P0/P1 require approval                         │
│  • Check RBAC rules: role-based action permissions                      │
│  • Check data access rules: customer data triggers approval             │
│  • Return PolicyDecision(allowed, requires_approval, reason, risk)      │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
                    ▼                               ▼
┌────────────────────────────┐    ┌────────────────────────────────────────┐
│  7a. REQUIRES APPROVAL     │    │  7b. APPROVED                          │
│  • Skip response generation │    │  • Generate customer response          │
│  • Set status: "pending"    │    │  • Use REDACTED context                │
│  • Return approval_required │    │  • Restore PII in final response       │
└────────────────────────────┘    │  • Set status: "complete"              │
                    │              └────────────────────────────────────────┘
                    │                               │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        8. AUDIT LOG                                      │
│  • Write to audit_logs table:                                           │
│    - ticket_id, user_id, tenant_id                                      │
│    - redacted_input (never raw PII)                                     │
│    - token_map (encrypted in production)                                │
│    - model_name, provider                                                │
│    - severity, actions                                                   │
│    - policy_decision (JSON)                                             │
│    - final_response                                                      │
│    - latency_ms, cost_estimate                                          │
│    - created_at                                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        9. RESPONSE                                       │
│  {                                                                       │
│    "ticket_id": "TKT-2026-001",                                         │
│    "severity": "P1",                                                     │
│    "actions": ["escalate_to_engineering", "notify_customer"],           │
│    "policy_decision": {                                                  │
│      "allowed": true,                                                    │
│      "requires_approval": true,                                          │
│      "reason": "P1 severity requires manager approval",                 │
│      "risk_level": "high"                                                │
│    },                                                                    │
│    "response": null,                                                     │
│    "approval_required": true,                                            │
│    "audit_log_id": "550e8400-e29b-41d4-a716-446655440000"               │
│  }                                                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

## Data States

| Stage | Data State | PII Visible | Logged |
|-------|------------|-------------|--------|
| Input | Raw | Yes | No |
| Post-Redaction | Tokenized | No (tokens only) | Yes |
| LLM Processing | Tokenized | No | Yes |
| Policy Check | Tokenized | No | Yes |
| Response Generation | Tokenized | No | Yes |
| Final Response | Restored (if approved) | Yes | No (only redacted) |

## Token Map Lifecycle

```
1. CREATION (PII Redaction)
   Input: "Contact: maria@acme.com, CPF: 123.456.789-00"
   Output: "Contact: [PII_EMAIL_1], CPF: [PII_CPF_2]"
   Token Map: {
     "[PII_EMAIL_1]": "maria@acme.com",
     "[PII_CPF_2]": "123.456.789-00"
   }

2. STORAGE (Audit Log)
   Token map stored as JSONB in audit_logs table
   Associated with ticket_id and audit_log_id

3. USAGE (Response Restoration)
   If policy approved:
     Template: "We've updated your account [PII_EMAIL_1]"
     Restored: "We've updated your account maria@acme.com"

4. RETENTION (Compliance)
   Token maps retained per data retention policy
   Enables audit trail reconstruction
```

## Error Handling

| Error Type | Handling | Logged |
|------------|----------|--------|
| Authentication failure | 401 response | Yes |
| Invalid payload | 400 response | Yes |
| LLM timeout | Fallback to mock | Yes |
| Policy denial | 403 response | Yes |
| Database error | 500 response, retry | Yes |

## Async Considerations

All I/O operations are async:
- Database connections use asyncpg
- LLM calls use httpx async client
- Audit logging is awaited before response

This ensures non-blocking operation under load.
