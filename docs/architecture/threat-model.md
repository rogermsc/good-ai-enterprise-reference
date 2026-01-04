# Threat Model

## Overview

This document provides a STRIDE-based threat analysis for the Enterprise AI Platform. The primary security assumption is that **LLMs are untrusted processors** — their outputs must be validated, sanitized, and policy-checked before execution.

## System Assets

| Asset | Sensitivity | Description |
|-------|-------------|-------------|
| Customer PII | Critical | CPF, CNPJ, emails, phone numbers |
| Ticket Content | High | Support ticket text, context |
| Policy Decisions | High | Approval/denial records |
| Audit Logs | Critical | Immutable compliance records |
| API Keys | Critical | LLM provider credentials |
| Internal Tools | High | Database access, notifications |

## STRIDE Analysis

### Spoofing

| Threat | Risk | Mitigation |
|--------|------|------------|
| Unauthorized API access | High | Header-based auth (demo), OAuth/OIDC (production) |
| Tenant impersonation | Critical | Tenant ID validation, audit logging |
| LLM response spoofing | Medium | TLS to providers, response validation |

**Controls:**
- All requests require authentication headers
- Tenant isolation enforced at query level
- Audit logs capture auth context

### Tampering

| Threat | Risk | Mitigation |
|--------|------|------------|
| Prompt injection | Critical | Input validation, output sanitization |
| Policy bypass | Critical | Policy engine as mandatory gateway |
| Audit log modification | Critical | Append-only logging, checksums (roadmap) |
| Token map manipulation | High | Database-level access controls |

**Controls:**
- Policy engine evaluates ALL proposed actions
- No direct tool execution without approval
- Audit logs written before response returned

### Repudiation

| Threat | Risk | Mitigation |
|--------|------|------------|
| Denial of LLM requests | Medium | Complete audit logging |
| Policy decision disputes | High | Structured policy decision records |
| Action attribution | High | User/tenant context in all logs |

**Controls:**
- Every operation logged with:
  - User ID, Tenant ID, Roles
  - Timestamp, Latency
  - Redacted input, Token map
  - Policy decision, Final output

### Information Disclosure

| Threat | Risk | Mitigation |
|--------|------|------------|
| PII in LLM prompts | Critical | Mandatory PII redaction |
| PII in LLM responses | High | Output validation (roadmap) |
| Log data exposure | High | Log access controls |
| API key leakage | Critical | Environment-only, never logged |
| Model training on data | Critical | Opt-out flags, provider agreements |

**Controls:**
- PII redactor tokenizes sensitive data before LLM
- Token maps stored separately from LLM interaction
- API keys loaded from environment only
- Logs store redacted content only

### Denial of Service

| Threat | Risk | Mitigation |
|--------|------|------------|
| API flooding | Medium | Rate limiting (production) |
| LLM cost exhaustion | High | Cost tracking, budget limits (roadmap) |
| Large payload attacks | Medium | Request size limits |
| Recursive agent loops | High | Step limits, timeout enforcement |

**Controls:**
- Agent graph has explicit step limits
- Cost estimation logged per request
- Timeout enforcement on LLM calls

### Elevation of Privilege

| Threat | Risk | Mitigation |
|--------|------|------------|
| Role escalation | Critical | RBAC in policy engine |
| Tool abuse | Critical | Policy approval for all tools |
| SSRF via LLM | High | No URL fetching without approval |
| Command injection | Critical | No shell execution from LLM |

**Controls:**
- Policy engine enforces RBAC
- All tool calls require explicit policy approval
- P0/P1 severity tickets require human approval
- No dynamic code execution

## LLM-Specific Threats

### Prompt Injection

**Attack:** Malicious input manipulates LLM behavior
**Example:** Ticket body contains "Ignore previous instructions..."
**Mitigation:**
- Treat all LLM output as untrusted
- Policy engine validates proposed actions
- No direct tool execution from LLM suggestions

### Data Exfiltration via LLM

**Attack:** LLM trained on or logs sensitive data
**Mitigation:**
- PII redaction before LLM processing
- Provider data processing agreements
- Audit logs capture what LLM received

### Hallucination Risks

**Attack:** LLM generates plausible but incorrect information
**Mitigation:**
- Human approval for high-severity actions
- Structured output validation
- Response templates for customer communication

### Model Supply Chain

**Attack:** Compromised or manipulated model weights
**Mitigation:**
- Use established providers (OpenAI, Anthropic)
- Version pinning for model selection
- Mock mode for testing without real models

### Tool Abuse / SSRF

**Attack:** LLM suggests malicious tool parameters
**Mitigation:**
- Policy engine validates all tool parameters
- Allowlists for URLs, database queries
- No dynamic endpoint construction

## Trust Boundaries

```
┌─────────────────────────────────────────────────────────┐
│  EXTERNAL (Untrusted)                                    │
│  • User requests                                         │
│  • Ticket content                                        │
│  • LLM responses                                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  TRUST LAYER (Validation)                                │
│  • Authentication check                                  │
│  • PII redaction                                         │
│  • Policy evaluation                                     │
│  • Audit logging                                         │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  INTERNAL (Trusted after validation)                     │
│  • Database operations                                   │
│  • Tool execution                                        │
│  • Response generation                                   │
└─────────────────────────────────────────────────────────┘
```

## Roadmap Controls

The following controls are documented for production implementation:

| Control | Priority | Description |
|---------|----------|-------------|
| Output sanitization | High | Validate LLM responses for injection |
| Audit log checksums | High | Cryptographic integrity verification |
| Budget enforcement | Medium | Hard limits on LLM spend per tenant |
| Rate limiting | Medium | Request throttling per user/tenant |
| Output filtering | Medium | Block sensitive data in responses |
| Anomaly detection | Low | ML-based unusual behavior detection |
| Model fingerprinting | Low | Detect model substitution attacks |

## Incident Response

For security incidents involving this system:

1. **Contain** — Disable affected tenant/user access
2. **Preserve** — Export audit logs for analysis
3. **Analyze** — Review policy decisions and tool calls
4. **Remediate** — Update policies, rotate credentials
5. **Report** — Notify affected parties per regulations

## Assumptions

1. PostgreSQL database is properly secured
2. Network segmentation isolates components
3. Container runtime is patched and configured securely
4. LLM provider implements reasonable security measures
5. Operators follow security best practices

## References

- OWASP Top 10 for LLM Applications
- NIST AI Risk Management Framework
- MITRE ATLAS (Adversarial Threat Landscape for AI Systems)
