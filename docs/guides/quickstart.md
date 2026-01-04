# Quickstart Guide

Get the Enterprise AI Reference running locally in under 5 minutes.

## Prerequisites

- Docker & Docker Compose
- Git
- curl (for testing)

Optional:
- Python 3.11+ (for local development)
- OpenAI API key (for live LLM calls)

## Step 1: Clone the Repository

```bash
git clone https://github.com/wearegoodai/good-ai-enterprise-reference.git
cd good-ai-enterprise-reference
```

## Step 2: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Optional: Edit .env to add your OpenAI API key
# OPENAI_API_KEY=sk-your-key-here
```

Without an API key, the system runs in **mock mode** — deterministic responses based on keyword heuristics.

## Step 3: Start Services

```bash
docker-compose -f infrastructure/docker-compose.yml up --build
```

This starts:
- **api**: FastAPI server on port 8000
- **postgres**: PostgreSQL with pgvector on port 5432

Wait for the message:
```
api_1       | INFO:     Uvicorn running on http://0.0.0.0:8000
```

## Step 4: Verify Health

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "environment": "development"
}
```

## Step 5: Submit a Test Ticket

### Low Severity (P3)

```bash
curl -X POST http://localhost:8000/tickets/triage \
  -H "Content-Type: application/json" \
  -H "X-User-Id: agent-001" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Roles: support_agent" \
  -d '{
    "ticket_id": "TKT-2026-001",
    "subject": "How do I reset my password?",
    "body": "I forgot my password and need help resetting it. My email is user@example.com",
    "customer_email": "user@example.com",
    "source": "email"
  }'
```

Expected: Full response generated (low severity, no approval needed)

### High Severity (P0)

```bash
curl -X POST http://localhost:8000/tickets/triage \
  -H "Content-Type: application/json" \
  -H "X-User-Id: agent-001" \
  -H "X-Tenant-Id: acme-corp" \
  -H "X-Roles: support_agent" \
  -d '{
    "ticket_id": "TKT-2026-002",
    "subject": "URGENT: Data breach suspected",
    "body": "We found unauthorized access to customer database. CPF numbers may be exposed: 123.456.789-00",
    "customer_email": "security@customer.com",
    "source": "email"
  }'
```

Expected: `approval_required: true` (P0 severity triggers policy check)

## Step 6: Explore the Response

```json
{
  "ticket_id": "TKT-2026-002",
  "severity": "P0",
  "actions": ["escalate_to_security", "notify_customer", "create_incident"],
  "policy_decision": {
    "allowed": true,
    "requires_approval": true,
    "reason": "P0 severity requires manager approval before customer response",
    "risk_level": "critical"
  },
  "response": null,
  "approval_required": true,
  "audit_log_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

Note:
- PII (CPF) was redacted before LLM processing
- Policy engine flagged for approval
- Response not generated (awaiting approval)
- Audit log created

## Step 7: Stop Services

```bash
docker-compose -f infrastructure/docker-compose.yml down
```

Add `-v` to also remove the database volume:
```bash
docker-compose -f infrastructure/docker-compose.yml down -v
```

## Next Steps

- [Architecture Overview](../architecture/high-level-design.md)
- [Threat Model](../architecture/threat-model.md)
- [Production Deployment](production-deploy.md)
- [Example Payloads](../../examples/ticket-triage-agent/README.md)

## Troubleshooting

### Port Already in Use

```bash
# Check what's using port 8000
lsof -i :8000

# Or use different ports in docker-compose
API_PORT=8001 docker-compose up
```

### Database Connection Failed

```bash
# Check postgres is running
docker-compose ps

# View postgres logs
docker-compose logs postgres
```

### OpenAI API Errors

- Verify API key is set in `.env`
- Check API key has sufficient credits
- System falls back to mock mode on API errors
