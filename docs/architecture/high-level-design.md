# High-Level Design

## Overview

The Good AI Enterprise Reference Implementation demonstrates a production-grade architecture for deploying AI agents in enterprise environments. The system prioritizes security, auditability, and policy compliance over raw performance.

## Design Principles

1. **Defense in Depth** — Multiple layers of security controls
2. **Zero Trust LLM** — Model outputs are untrusted data
3. **Audit Everything** — Immutable logs for compliance
4. **Policy as Code** — All access decisions are programmatic
5. **Fail Closed** — Deny by default, require explicit approval

## System Components

### Application Layer

The application layer consists of:

- **FastAPI Server** — Async HTTP API for ticket processing
- **LangGraph Agents** — Stateful multi-step workflows
- **Typed Models** — Pydantic models for all data structures

### Trust Layer

The Trust Layer is the core security component:

```
┌────────────────────────────────────────────────────────────────┐
│                        TRUST LAYER                              │
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │     PII      │    │    Policy    │    │    Audit     │      │
│  │   Redactor   │───▶│    Engine    │───▶│    Logger    │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────────────────────────────────────────────┐      │
│  │                    LLM GATEWAY                        │      │
│  │  • Provider abstraction                               │      │
│  │  • Request/response logging                           │      │
│  │  • Cost tracking                                      │      │
│  │  • Mock mode for testing                              │      │
│  └──────────────────────────────────────────────────────┘      │
└────────────────────────────────────────────────────────────────┘
```

#### PII Redactor

- Tokenizes sensitive data (CPF, CNPJ, emails, phones)
- Maintains token map for restoration
- Ensures LLM never sees raw PII

#### Policy Engine

- Evaluates proposed actions against RBAC rules
- Enforces severity-based approval requirements
- Returns structured policy decisions

#### Audit Logger

- Records all operations to Postgres
- Stores redacted inputs, policy decisions, outputs
- Tracks latency and estimated costs

#### LLM Gateway

- Abstracts LLM provider differences
- Operates in mock mode without API key
- Accepts only pre-redacted prompts

### Data Layer

- **PostgreSQL** with pgvector extension
- **Audit Logs** — Immutable operation records
- **Token Maps** — Stored as JSONB for PII restoration

## Request Flow

1. HTTP request arrives at FastAPI
2. Security middleware extracts auth context
3. Agent workflow begins:
   - Ticket ingested
   - PII redacted and tokenized
   - Severity classified via LLM
   - Actions recommended
   - Policy engine evaluates
   - If approved: response generated
   - If not: returns pending approval
4. Audit log written
5. Response returned to client

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Framework | FastAPI (async) |
| Agents | LangGraph |
| Database | PostgreSQL + pgvector |
| Container | Docker |
| CI/CD | GitHub Actions |
| Linting | Ruff |

## Scalability Considerations

This reference implementation is designed for clarity over performance. For production scale:

- Add connection pooling (asyncpg with pgbouncer)
- Implement caching for policy decisions
- Use message queues for async processing
- Deploy with Kubernetes for horizontal scaling
- Add Redis for session state

## Security Boundaries

```
┌─────────────────────────────────────────────────────────────┐
│                    TRUST BOUNDARY 1                          │
│  User requests → API Gateway → Authentication                │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    TRUST BOUNDARY 2                          │
│  Authenticated request → Trust Layer → Policy Check          │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    TRUST BOUNDARY 3                          │
│  Approved request → LLM Gateway → External Provider          │
└─────────────────────────────────────────────────────────────┘
```

Each boundary requires explicit approval to cross.
