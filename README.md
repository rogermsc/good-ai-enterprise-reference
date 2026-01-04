# Enterprise AI Platform: Reference Implementation (2026)

<p align="center">
  <strong>Good AI — Trust Layer Architecture</strong><br>
  <em>Production-grade patterns for secure, auditable, policy-governed AI systems</em>
</p>

---

**Maintainer:** Roger Simões, CEO & Chief Architect @ [Good AI](https://wearegoodai.com)

> **Disclaimer:** This is a reference implementation demonstrating enterprise AI architecture patterns.
> It is provided for educational and evaluation purposes. Adapt security controls, compliance measures,
> and operational practices to your specific regulatory and organizational requirements before production use.

---

## What Is This?

This repository demonstrates how to build enterprise AI systems that are:

- **Secure by Design** — LLM outputs treated as untrusted data; all tool calls gated by policy
- **Auditable** — Every inference logged with redacted inputs, policy decisions, and costs
- **Compliant** — Data sovereignty patterns, PII redaction, role-based access control
- **Observable** — Structured logging, latency tracking, cost estimation hooks
- **Production-Ready** — Docker Compose, CI/CD, typed Python, async FastAPI

The core innovation is the **Trust Layer**: a gateway that sits between your application and LLM providers, enforcing policies, redacting PII, and maintaining audit trails.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         APPLICATION LAYER                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐     │
│  │   Web UI    │  │   API       │  │   CLI       │  │   Agents    │     │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘     │
└─────────┼────────────────┼────────────────┼────────────────┼────────────┘
          │                │                │                │
          ▼                ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          TRUST LAYER                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                         LLM GATEWAY                                  ││
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            ││
│  │  │   PII    │  │  Policy  │  │  Audit   │  │  Cost    │            ││
│  │  │ Redactor │─▶│  Engine  │─▶│  Logger  │─▶│ Tracker  │            ││
│  │  └──────────┘  └──────────┘  └──────────┘  └──────────┘            ││
│  └─────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         LLM PROVIDERS                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                      │
│  │   OpenAI    │  │  Anthropic  │  │   Azure     │                      │
│  └─────────────┘  └─────────────┘  └─────────────┘                      │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Key Components

### Trust Layer

| Component | Purpose |
|-----------|---------|
| **LLM Gateway** | Single point of control for all LLM interactions |
| **Policy Engine** | RBAC + severity-based approval gating |
| **PII Redactor** | Tokenizes sensitive data before LLM processing |
| **Audit Logger** | Immutable record of all operations |

### Demo Agent: Ticket Triage

A LangGraph-based agent that:
1. Ingests support tickets
2. Redacts PII (CPF, CNPJ, emails, phones)
3. Classifies severity (P0-P4)
4. Recommends actions
5. Enforces policy (P0/P1 require approval)
6. Generates customer response
7. Logs everything

---

## Quickstart

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)
- Optional: OpenAI API key for live LLM calls

### Run with Docker Compose

```bash
# Clone the repository
git clone https://github.com/wearegoodai/good-ai-enterprise-reference.git
cd good-ai-enterprise-reference

# Copy environment configuration
cp .env.example .env

# Optional: Add your OpenAI API key to .env
# OPENAI_API_KEY=sk-...

# Start services
docker-compose -f infrastructure/docker-compose.yml up --build

# In another terminal, test the API
curl http://localhost:8000/health
```

### Submit a Ticket

```bash
curl -X POST http://localhost:8000/tickets/triage \
  -H "Content-Type: application/json" \
  -H "X-User-Id: agent-001" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Roles: support_agent" \
  -d '{
    "ticket_id": "TKT-2026-001",
    "subject": "Urgent: Production database down",
    "body": "Our production database is not responding. Customer data may be affected. Contact: maria.silva@acme.com, CPF: 123.456.789-00",
    "customer_email": "customer@example.com",
    "source": "email"
  }'
```

---

## What This Proves

This reference implementation demonstrates that enterprise AI systems can be:

| Requirement | How We Address It |
|-------------|-------------------|
| **Zero Trust LLM** | All model outputs treated as untrusted; tool calls require policy approval |
| **Data Protection** | PII redacted before LLM sees data; tokenization enables restoration |
| **Audit Compliance** | Every operation logged with full context, policy decisions, costs |
| **RBAC** | Role-based policy engine gates sensitive operations |
| **Sovereignty** | Patterns for data residency and cross-border processing |
| **Observability** | Structured logs, latency tracking, cost estimation |

---

## Enterprise Readiness Checklist

- [x] Audit logging with immutable records
- [x] PII redaction with reversible tokenization
- [x] Role-based access control (RBAC)
- [x] Policy engine with approval workflows
- [x] Severity-based escalation (P0/P1 gating)
- [x] Mock mode for development/testing
- [x] Typed models (Pydantic)
- [x] Async FastAPI architecture
- [x] Docker Compose deployment
- [x] CI/CD pipeline
- [x] Security scanning
- [x] Threat model documentation
- [ ] Kubernetes manifests (see production guide)
- [ ] Secrets manager integration (documented)
- [ ] Observability stack (OpenTelemetry hooks ready)

---

## Documentation

| Document | Description |
|----------|-------------|
| [High-Level Design](docs/architecture/high-level-design.md) | System architecture |
| [Threat Model](docs/architecture/threat-model.md) | STRIDE analysis |
| [Data Flow](docs/architecture/data-flow.md) | Request lifecycle |
| [Data Sovereignty](docs/compliance/data-sovereignty.md) | Residency patterns |
| [Audit Logging](docs/compliance/audit-logging.md) | Compliance logging |
| [ADR-0001: Trust Layer](docs/decisions/adr-0001-trust-layer.md) | Why Trust Layer |
| [ADR-0002: Policy Engine](docs/decisions/adr-0002-policy-engine.md) | Policy design |
| [Quickstart](docs/guides/quickstart.md) | Getting started |
| [Production Deploy](docs/guides/production-deploy.md) | Production guidance |

---

## Project Structure

```
good-ai-enterprise-reference/
├── src/
│   ├── agents/           # LangGraph agents
│   │   └── ticket_triage/
│   ├── api/              # FastAPI server
│   ├── core/             # Trust Layer components
│   └── db/               # Database layer
├── tests/                # Unit tests
├── docs/                 # Documentation
├── infrastructure/       # Docker, Compose
└── examples/             # Sample payloads
```

---

## Development

```bash
# Install dependencies
make setup

# Run linting
make lint

# Run tests
make test

# Run locally (requires Postgres)
make run
```

---

## Security

See [SECURITY.md](SECURITY.md) for:
- Responsible disclosure process
- Security best practices
- Supported versions

---

## License

Apache 2.0 — See [LICENSE](LICENSE)

---

## About Good AI

[Good AI](https://wearegoodai.com) builds enterprise AI infrastructure that organizations can trust.
We believe AI systems must be secure, auditable, and governed by clear policies.

**Contact:** hello@wearegoodai.com

---

<p align="center">
  <em>Built with trust in mind.</em>
</p>
