# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-01-15

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
  - Action recommendations
  - Policy-gated response generation
  - Full audit trail

- **API Layer**
  - FastAPI async server
  - Health check endpoints
  - Ticket triage endpoint
  - OpenAPI documentation

- **Infrastructure**
  - Docker Compose setup
  - PostgreSQL with pgvector
  - Multi-stage Dockerfile
  - GitHub Actions CI/CD

- **Documentation**
  - Architecture documentation
  - STRIDE threat model
  - Data sovereignty patterns
  - ADRs for Trust Layer and Policy Engine
  - Quickstart and production deployment guides

- **Security**
  - Security scanning workflows
  - Dependency auditing
  - Container scanning
  - Responsible disclosure policy

### Security

- All LLM outputs treated as untrusted data
- PII redaction mandatory before LLM calls
- Policy engine gates all tool/action execution
- Audit logs capture all operations

### Notes

This is the initial release of the Enterprise AI Platform Reference Implementation.
It demonstrates production-grade patterns for secure, auditable AI systems.

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
