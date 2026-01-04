# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with this repository.

## Project Overview

Enterprise AI Platform Reference Implementation demonstrating production-grade patterns for building secure, compliant AI systems. Features a Trust Layer architecture that ensures all LLM interactions pass through security gates.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Server                         │
├─────────────────────────────────────────────────────────────┤
│                     Trust Layer                             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐    │
│  │ PII Redactor│→ │Policy Engine │→ │   LLM Gateway   │    │
│  └─────────────┘  └──────────────┘  └─────────────────┘    │
│         ↓                ↓                   ↓              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                   Audit Logger                       │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│              LangGraph Agent Orchestration                  │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌───────────┐     │
│  │ Ingest  │→ │PII Redact│→ │Classify│→ │Policy Check│     │
│  └─────────┘  └──────────┘  └────────┘  └───────────┘     │
│                                               ↓             │
│  ┌─────────────┐  ┌────────────────┐  ┌─────────────┐     │
│  │ Audit Write │← │Generate Response│← │Recommend Act│     │
│  └─────────────┘  └────────────────┘  └─────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Principles

1. **LLM output is untrusted** - All LLM responses are validated before use
2. **No direct tool execution** - Agents propose actions; policy engine approves
3. **PII never reaches LLM** - Tokenization before, restoration after
4. **Immutable audit trail** - Every decision is logged for compliance

## Directory Structure

```
src/
├── api/              # FastAPI routes and server
│   ├── server.py     # Application entry point
│   └── routes/       # API endpoints
├── agents/           # LangGraph agent implementations
│   └── ticket_triage/
│       ├── graph.py  # LangGraph workflow definition
│       ├── models.py # Pydantic state models
│       └── nodes.py  # Workflow node implementations
├── core/             # Trust Layer components
│   ├── audit_log.py  # Immutable audit logging
│   ├── config.py     # Settings management
│   ├── llm_gateway.py# LLM interaction gateway
│   ├── pii_redaction.py # PII detection/tokenization
│   ├── policy_engine.py # RBAC and approval logic
│   └── security.py   # Security context
└── db/               # Database connection pooling
```

## Common Commands

```bash
# Install dependencies
pip install -e ".[dev]"

# Run linting
ruff check src/ tests/
ruff format src/ tests/

# Run tests
pytest tests/ -v

# Start development server
uvicorn src.api.server:app --reload

# Start with Docker Compose
docker-compose -f infrastructure/docker-compose.yml up
```

## Testing Patterns

- Tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- Mock LLM provider via `LLM_PROVIDER=mock` environment variable
- SecurityContext fixtures in `tests/conftest.py`
- Unit tests focus on Trust Layer components

## Code Style

- Python 3.11+ with type hints
- Pydantic v2 for data validation (use `ConfigDict`, not class-based `Config`)
- `datetime.now(UTC)` instead of deprecated `datetime.utcnow()`
- `ruff` for linting and formatting
- Iterable unpacking preferred: `[*list, item]` over `list + [item]`

## Security Considerations

- Never log database credentials or secrets
- PII patterns: CPF, CNPJ, Cédula, email, phone
- Policy engine enforces RBAC for all agent actions
- P0/P1 severity always requires human approval
