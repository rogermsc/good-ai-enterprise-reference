# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-01-06

### Added

- **Trust Layer Architecture**
  - LLM Gateway with provider abstraction (OpenAI, mock mode)
  - Policy Engine with RBAC and severity-based approval workflows
  - PII Redactor with support for CPF, CNPJ, Cédula, email, phone
  - Audit Logger with PostgreSQL storage

- **Ticket Triage Agent**
  - LangGraph-based stateful workflow
  - Automatic PII redaction before LLM processing
  - Severity classification (P0-P4)
  - Action recommendations with policy gating
  - Human-in-the-loop approval workflows
  - Webhook notifications for external integrations
  - Full audit trail

- **Approval System**
  - Request/approve/reject workflow
  - Priority levels (Critical, High, Medium, Low)
  - Self-approval prevention
  - Expiration handling

- **Webhook System**
  - HMAC-SHA256 signed payloads
  - Retry with exponential backoff
  - Event types: ticket, approval, system events

- **API Layer**
  - FastAPI async server
  - JWT authentication with role validation
  - Health check endpoints
  - Ticket triage, approvals, and webhooks endpoints
  - OpenAPI documentation

- **Infrastructure**
  - Docker Compose setup
  - PostgreSQL with pgvector
  - Multi-stage Dockerfile
  - GitHub Actions CI/CD (lint, test, build)

- **Documentation**
  - Architecture documentation
  - STRIDE threat model
  - Data sovereignty patterns
  - ADRs for Trust Layer and Policy Engine
  - Quickstart and production deployment guides

- **Testing**
  - 343 unit tests
  - Deterministic tests (mock LLM provider)
  - pytest-asyncio for async testing

### Security

- All LLM outputs treated as untrusted data
- PII redaction mandatory before LLM calls
- Policy engine gates all tool/action execution
- Audit logs capture all operations
- Role validation prevents spoofing
- CORS properly configured for credentials
- JWT refresh token validation fixed

### Known Limitations

- Token refresh returns empty roles (requires user service integration)
- Rate limiting not implemented
- Budget enforcement not implemented
- Kubernetes manifests not included

---

## [Unreleased]

### Planned

- Output sanitization for LLM responses
- Rate limiting implementation
- Budget enforcement for LLM costs
- Kubernetes manifests
- OpenTelemetry integration
- Policy as Code (OPA integration)
- Approval workflow UI
